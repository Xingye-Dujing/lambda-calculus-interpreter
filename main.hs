{-# LANGUAGE ScopedTypeVariables #-}
{-# LANGUAGE RecordWildCards #-}
{-# LANGUAGE BangPatterns #-}

-- ---------------------------------------------------------------------------
-- 最小 λ 演算解释器 / Minimal lambda calculus interpreter
-- 核心与 extension.hs 保持一致；不含定义与环境
-- The core mirrors extension.hs; it has no definitions or environment.
-- ---------------------------------------------------------------------------

import qualified Data.Set as Set
import Control.Applicative ((<|>))
import Control.Exception (catch, SomeException, AsyncException(..), throwIO)
import Control.Monad (void, when, unless, forM_, replicateM_, guard)
import Control.Monad.IO.Class (liftIO)
import Data.Char (isAlpha, isDigit, isSpace)
import Data.List (elemIndex, stripPrefix, isPrefixOf, foldl')
import System.Directory (getHomeDirectory)
import System.Environment (getArgs)
import System.Exit (exitFailure)
import System.IO (hSetEncoding, utf8, hIsTerminalDevice, stdout, stdin, stderr, hPutStrLn, hPutStr, hGetLine, hIsEOF)
import GHC.IO.Encoding (setLocaleEncoding)
import System.Console.Haskeline
import Text.ParserCombinators.ReadP

versionString :: String
versionString = "lambda-calculus-interpreter 2.2.3 (minimal)"

-- ---------------------------------------------------------------------------
-- 双语支持 Bilingual support
-- ---------------------------------------------------------------------------
data Lang = Zh | En | Both deriving (Eq, Show)

parseLang :: String -> Maybe Lang
parseLang s = lookup (map lower s)
  [ ("zh", Zh), ("cn", Zh), ("chinese", Zh), ("中文", Zh)
  , ("en", En), ("english", En), ("英文", En)
  , ("both", Both), ("bilingual", Both), ("双语", Both)
  ]
  where lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c

tr :: Lang -> String -> String -> String
tr Zh zh _    = zh
tr En _ en    = en
tr Both zh en = zh ++ " / " ++ en

type Msg = (String, String)

renderMsg :: Lang -> Msg -> String
renderMsg lang (zh, en) = tr lang zh en

-- ---------------------------------------------------------------------------
-- 表达式 Expression
-- ---------------------------------------------------------------------------
data Expr = Var String | Lam String Expr | App Expr Expr
  deriving (Eq, Ord, Show)

freeVars :: Expr -> Set.Set String
freeVars (Var x)      = Set.singleton x
freeVars (Lam x body) = Set.delete x (freeVars body)
freeVars (App f a)    = freeVars f `Set.union` freeVars a

freshVar :: String -> Set.Set String -> String
freshVar base avoid
  | base `Set.notMember` avoid = base
  | otherwise                  = freshVar (base ++ "'") avoid

-- 参数的自由的变量只算一次；不含 x 的子树直接共享，不作复制
-- The argument's free variables are computed once; subtrees without x are shared.
substRename :: String -> Expr -> Set.Set String -> Expr -> (Expr, Bool)
substRename x v fvV body =
  case go body of
    Just (e, renamed) -> (e, renamed)
    Nothing           -> (body, False)
  where
    go :: Expr -> Maybe (Expr, Bool)
    go (Var y)
      | x == y    = Just (v, False)
      | otherwise = Nothing
    go (App f a) = case (go f, go a) of
      (Nothing, Nothing) -> Nothing
      (mf, ma) ->
        let f'      = maybe f fst mf
            a'      = maybe a fst ma
            renamed = maybe False snd mf || maybe False snd ma
        in Just (App f' a', renamed)
    go (Lam y inner)
      | x == y                = Nothing
      | y `Set.notMember` fvV =
          fmap (\(b, r) -> (Lam y b, r)) (go inner)
      | otherwise             =
          -- x 不在体内时无需替换，也无需 α-重命名
          -- If x is not free in the body there is nothing to substitute and
          -- no reason to rename the binder.
          let fvInner = freeVars inner
          in if x `Set.notMember` fvInner
               then Nothing
               else
                 let y'      = freshVar y (fvInner `Set.union` fvV)
                     (b1, _) = substRename y (Var y') (Set.singleton y') inner
                     b2      = case go b1 of
                                 Just (b, _) -> b
                                 Nothing     -> b1
                 in Just (Lam y' b2, True)

-- ---------------------------------------------------------------------------
-- 求值策略 Evaluation strategies
-- ---------------------------------------------------------------------------
data Strategy = Applicative | Normal | CallByName | CallByValue
  deriving (Eq, Show)

strategyLabelZh :: Strategy -> String
strategyLabelZh Applicative = "应用序（最左最内）"
strategyLabelZh Normal      = "正规序（最左最外）"
strategyLabelZh CallByName  = "按名调用（弱）"
strategyLabelZh CallByValue = "按值调用（弱）"

strategyLabelEn :: Strategy -> String
strategyLabelEn Applicative = "applicative order (leftmost-innermost)"
strategyLabelEn Normal      = "normal order (leftmost-outermost)"
strategyLabelEn CallByName  = "call-by-name (weak)"
strategyLabelEn CallByValue = "call-by-value (weak)"

parseStrategy :: String -> Maybe Strategy
parseStrategy s = lookup (map lower s)
  [ ("applicative", Applicative), ("app", Applicative)
  , ("normal", Normal), ("no", Normal)
  , ("cbn", CallByName), ("byname", CallByName)
  , ("cbv", CallByValue), ("byvalue", CallByValue)
  ]
  where lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c

-- ---------------------------------------------------------------------------
-- 单步归约 One-Step Reduction
-- 每一步都返回“整个项”的新形态，方便前端做前后对比
-- Each step rewrites the whole term, so the frontend can diff before/after.
-- ---------------------------------------------------------------------------
data Reduction = Reduction
  { redRule :: String   -- β / β+α
  , redNote :: String   -- 人类可读说明 / human-readable note
  , redTerm :: Expr     -- 归约后的项 / resulting term
  }

data StepOut = StepOut { soWhole :: Expr, soRed :: Reduction }

betaStep :: String -> Expr -> Expr -> Reduction
betaStep x body arg =
  let (after, renamed) = substRename x arg (freeVars arg) body
      rule   = if renamed then "β+α" else "β"
      note   = "β 归约 β-reduction: (λ" ++ x ++ ". …) " ++ shorten 42 (pretty arg)
               ++ (if renamed then "  （先 α-重命名 α-rename 避免变量捕获 capture）" else "")
  in Reduction rule note after

-- 四种策略由四个开关描述，避免复制四份遍历
-- One traversal driven by four flags instead of four copies.
data Order = Order
  { underLambda :: Bool
  , redexFirst  :: Bool
  , argsToValue :: Bool
  , argsIfLam   :: Bool
  }

orderOf :: Strategy -> Order
orderOf Applicative = Order True  False False False
orderOf Normal      = Order True  True  False False
orderOf CallByName  = Order False True  False True
orderOf CallByValue = Order False False True  True

stepOnce :: Strategy -> Expr -> Maybe StepOut
stepOnce strat = go
  where
    Order{..} = orderOf strat

    go (App f a)
      | redexFirst, Lam x b <- f = contract x b a
      | otherwise =
          case go f of
            Just s -> Just s { soWhole = App (soWhole s) a }
            Nothing
              | argsIfLam, not (isLam f) -> Nothing
              | Just s <- go a -> Just s { soWhole = App f (soWhole s) }
              | Lam x b <- f, not argsToValue || isValue a -> contract x b a
              | otherwise -> Nothing
    go (Lam x b)
      | underLambda = do
          s <- go b
          return s { soWhole = Lam x (soWhole s) }
      | otherwise = Nothing
    go _ = Nothing

    contract x b a = let r = betaStep x b a in Just (StepOut (redTerm r) r)
    isLam (Lam _ _)   = True
    isLam _           = False
    isValue (Lam _ _) = True
    isValue (Var _)   = True
    isValue _         = False

-- ---------------------------------------------------------------------------
-- η 归约 / eta reduction
-- ---------------------------------------------------------------------------
etaRoot :: Expr -> Maybe Reduction
etaRoot (Lam x (App f (Var y)))
  | x == y && x `Set.notMember` freeVars f =
      Just (Reduction "η"
        ("η 归约 η-reduction: λ" ++ x ++ ". … " ++ x ++ " → …") f)
etaRoot _ = Nothing

etaStep :: Strategy -> Expr -> Maybe StepOut
etaStep strat = go
  where
    -- 与扩展版一致：用同一张 Order 表驱动，并遵守弱策略的参数规则
    -- Match the extended version: drive by the same Order table and honour
    -- the weak-strategy argument rules.
    Order{..} = orderOf strat
    go e@(Lam x b) =
      case etaRoot e of
        Just r -> Just (StepOut (redTerm r) r)
        Nothing
          | underLambda -> do
              s <- go b
              return s { soWhole = Lam x (soWhole s) }
          | otherwise -> Nothing
    go (App f a) =
      case go f of
        Just s  -> Just s { soWhole = App (soWhole s) a }
        Nothing
          | argsIfLam, not (isLam f) -> Nothing
          | Just s <- go a -> Just s { soWhole = App f (soWhole s) }
          | otherwise -> Nothing
    go _ = Nothing
    isLam (Lam _ _) = True
    isLam _         = False

stepFor :: Bool -> Strategy -> Expr -> Maybe StepOut
stepFor eta strat e =
  stepOnce strat e <|> (if eta then etaStep strat e else Nothing)

-- 弱首正规形：顶层 λ 或中性项（头变量）/ WHNF: a top-level lambda or a neutral term
isWHNF :: Expr -> Bool
isWHNF (Lam _ _) = True
isWHNF e = case headSpine e of
  (Lam _ _, _) -> False
  _            -> True

headSpine :: Expr -> (Expr, [Expr])
headSpine = go []
  where
    go acc (App f a) = go (a : acc) f
    go acc h         = (h, acc)

data TraceStep = TraceStep
  { tsIndex :: Int, tsAfter :: Expr, tsRule :: String, tsNote :: String }

data EvalResult = EvalResult
  { erFinal :: Expr, erSteps :: [TraceStep], erCount :: Int
  , erLimitHit :: Bool, erCycle :: Bool }

defaultLimit :: Int
defaultLimit = 10000

-- 轨迹上限：超出后仍给出精确步数，但只保留前若干步（与扩展版一致）
-- Trace cap: keep the exact count but only the first steps, like extension.hs.
traceLimit :: Int
traceLimit = 500

-- 有界循环检测：只记住前若干步里的小项（与扩展版一致）
-- Bounded cycle detection: remember small whole terms for the first steps,
-- matching the extended interpreter.
cycleCheckLimit :: Int
cycleCheckLimit = 2000

cycleTermLimit :: Int
cycleTermLimit = 400

-- 求值循环：keepTrace 为 False 时不保留轨迹（省内存）
-- Evaluation loop; with keepTrace=False the trace is dropped (saves memory).
evalUntil :: Bool -> Bool -> Int -> Strategy -> (Expr -> Bool) -> Expr -> EvalResult
evalUntil eta keepTrace limit strat done e0 =
  loop 1 e0 [] (Set.singleton e0) False
  where
    loop !n e !acc !seen !cyc
      | n > limit = EvalResult e (reverse acc) (n - 1) True cyc
      | done e    = EvalResult e (reverse acc) (n - 1) False cyc
      | otherwise = case stepFor eta strat e of
          Just s ->
            let e'   = soWhole s
                red  = soRed s
                acc' = if keepTrace && n <= traceLimit
                         then TraceStep n e' (redRule red) (redNote red) : acc
                         else acc
                track = n <= cycleCheckLimit && exprSize e' <= cycleTermLimit
                cyc'  = cyc || (track && Set.member e' seen)
                seen' = if track then Set.insert e' seen else seen
            in loop (n + 1) e' acc' seen' cyc'
          Nothing -> EvalResult e (reverse acc) (n - 1) False cyc

evalWith :: Bool -> Bool -> Int -> Strategy -> Expr -> EvalResult
evalWith eta keepTrace limit strat =
  evalUntil eta keepTrace limit strat (const False)

evalTraceWith :: Bool -> Int -> Strategy -> Expr -> EvalResult
evalTraceWith eta = evalWith eta True

evalFinal :: Bool -> Int -> Strategy -> Expr -> EvalResult
evalFinal eta = evalWith eta False

evalWHNF :: Bool -> Int -> Strategy -> Expr -> EvalResult
evalWHNF eta limit strat = evalUntil eta True limit strat isWHNF

-- ---------------------------------------------------------------------------
-- 语义提示 Semantic hints
-- ---------------------------------------------------------------------------
isChurchNumeral :: Expr -> Maybe Integer
isChurchNumeral (Lam f (Lam x body))
  -- 同名绑定会让内层 x 遮蔽 f，此时只有 0 仍成立
  -- A shadowing binder makes the inner x hide f, so only 0 can still hold.
  | f == x    = case body of
                  Var x' | x' == x -> Just 0
                  _                -> Nothing
  | otherwise = go 0 body
  where
    go n (Var x') | x' == x = Just n
    go n (App (Var f') rest) | f' == f = go (n + 1) rest
    go _ _ = Nothing
isChurchNumeral _ = Nothing

isChurchBoolean :: Expr -> Maybe Bool
isChurchBoolean (Lam t (Lam f (Var t'))) | t == t' && t /= f = Just True
isChurchBoolean (Lam _ (Lam f (Var f'))) | f == f' = Just False
isChurchBoolean _ = Nothing

valueHint :: Expr -> String
valueHint e = case (isChurchNumeral e, isChurchBoolean e) of
  (Just 0, Just False) -> "  (邱奇数 Church numeral 0 / Church 布尔值 boolean False)"
  (Just n, _)          -> "  (邱奇数 Church numeral " ++ show n ++ ")"
  (_, Just True)       -> "  (Church 布尔值 boolean True)"
  (_, Just False)      -> "  (Church 布尔值 boolean False)"
  _                    -> ""

-- ---------------------------------------------------------------------------
-- 打印 Printing
-- ---------------------------------------------------------------------------
pretty :: Expr -> String
pretty e = go 0 e ""
  where
    go :: Int -> Expr -> ShowS
    go _ (Var x)   = showString x
    go p (Lam x b) = showParen (p > 0)
      (showString "λ" . showString x . showString " → " . go 0 b)
    go p (App f a) = showParen (p > 1)
      (go 1 f . showChar ' ' . go 2 a)

-- 惰性截断：只强制前 n 个字符，巨型项不会先被完整打印
-- Lazy truncation: force only the first n characters.
shorten :: Int -> String -> String
shorten n s
  | n <= 0    = ""
  | otherwise = case splitAt n s of
      (pre, []) -> pre
      (pre, _)  -> take (n - 1) pre ++ "…"

treeLines :: Expr -> [String]
treeLines (Var x)   = ["• " ++ x]
treeLines (Lam x b) = ("λ " ++ x) : fork "└ " "  " (treeLines b)
treeLines (App f a) = "App" : fork "├ " "│ " (treeLines f) ++ fork "└ " "  " (treeLines a)

fork :: String -> String -> [String] -> [String]
fork _ _ []            = []
fork first rest (l:ls) = (first ++ l) : map (rest ++) ls

deBruijnView :: Expr -> String
deBruijnView e = go [] e ""
  where
    go bound (Var x) = case elemIndex x bound of
      Just i  -> showChar '#' . shows i
      Nothing -> showString x
    go bound (Lam x b) = showString "λ." . go (x : bound) b
    go bound (App f a) =
      showChar '(' . go bound f . showChar ' ' . go bound a . showChar ')'

-- 树/de Bruijn 视图的节点上限：缩进随深度增长，大项会撑爆输出
-- Node cap for tree/de Bruijn views; indentation grows with depth.
astBudget :: Int
astBudget = 400

exprSize :: Expr -> Int
exprSize (Var _)   = 1
exprSize (Lam _ b) = 1 + exprSize b
exprSize (App f a) = 1 + exprSize f + exprSize a

-- ---------------------------------------------------------------------------
-- 解析器 Parser
-- ---------------------------------------------------------------------------
spaces :: ReadP ()
spaces = void (greedyMany (satisfy isSpace))

ident :: ReadP String
ident = do
  c <- satisfy isAlpha
  cs <- munch (\ch -> isAlpha ch || isDigit ch || ch == '\'')
  return (c : cs)

-- ReadP 的 many/sepBy 会为每个前缀产生一个结果，嵌套起来组合数呈指数增长；
-- 这里只取最长的匹配，保证每个表达式只产生一个结果
-- ReadP's many/sepBy produce one result per prefix; nesting them multiplies the
-- alternatives exponentially, so keep only the longest match.
longestP :: ReadP a -> ReadP a
longestP p = do
  s <- look
  case readP_to_S p s of
    []    -> pfail
    (r:_) -> do
      let (_, rest) = r
          n = length s - length rest
      replicateM_ n get
      return (fst r)

-- 真正的贪心 many：每一步只吸收一个最长匹配，不产生任何分支；
-- ReadP 内建 many 会枚举每个前缀的结果，嵌套起来数目指数增长
-- A truly greedy many: every step absorbs one longest match without
-- branching; ReadP's built-in many enumerates one result per prefix.
greedyMany :: ReadP a -> ReadP [a]
greedyMany p = reverse <$> go []
  where
    go acc = do
      s <- look
      case readP_to_S p s of
        []           -> return acc
        ((x, rest) : _) ->
          let n = length s - length rest
          in if n <= 0
               then return acc
               else do
                 replicateM_ n get
                 go (x : acc)

greedySome :: ReadP a -> ReadP [a]
greedySome p = do
  x <- p
  xs <- greedyMany p
  return (x : xs)

-- greedy 的 `sepBy1`：第一个元素之后重复“sep 之后一个元素”
-- A greedy sepBy1: first element followed by repetitions of "sep element".
greedySepBy1 :: ReadP a -> ReadP s -> ReadP [a]
greedySepBy1 p sep = do
  x <- p
  xs <- greedyMany (sep *> p)
  return (x : xs)

-- greedy 的 `sepBy`：可以为空
-- A greedy sepBy: may be empty.
greedySepBy :: ReadP a -> ReadP s -> ReadP [a]
greedySepBy p sep = greedySepBy1 p sep <++ return []

parseExpr :: ReadP Expr
parseExpr = spaces *> longestP (parseLet <++ parseIf <++ parseLam <++ parseApp)

-- 分隔符接受 `.`、`→` 和 `->`
-- The delimiter accepts `.`, `→` and `->`.
lambdaSep :: ReadP ()
lambdaSep =
      void (char '.')
  <|> void (char '→')
  <|> (void (char '-') >> void (char '>'))

-- λ 的参数在遇到 `->` 时停止，因此 `\x->x` 与 `\x -> x` 都能解析
-- Lambda parameters stop before `->`, so both `\x->x` and `\x -> x` parse.
lamIdent :: ReadP String
lamIdent = do
  s <- look
  guard (not ("->" `isPrefixOf` s))
  c <- satisfy isAlpha
  cs <- go
  return (c : cs)
  where
    go = do
      rest <- look
      case rest of
        ('-':'>':_) -> return []
        (ch:_) | isAlpha ch || isDigit ch || ch == '\'' -> do
          _ <- get
          (ch :) <$> go
        _ -> return []


-- `in`、`then`、`else` 是保留字；遇到它们时原子解析失败
-- `in`, `then` and `else` are reserved: an atom fails there, ending the
-- enclosing expression.
notKeyword :: String -> ReadP ()
notKeyword kw = do
  r <- look
  let (pre, post) = splitAt (length kw) r
      boundary = null post || isSpace (head post)
              || head post `elem` ("().=,;" :: String)
  if pre == kw && boundary then pfail else return ()

-- if c then t else f 脱糖为 IF c t f
-- if c then t else f desugars to IF c t f.
parseIf :: ReadP Expr
parseIf = do
  _ <- string "if"
  _ <- munch1 isSpace
  c <- parseExpr
  spaces
  _ <- string "then"
  _ <- munch1 isSpace
  t <- parseExpr
  spaces
  _ <- string "else"
  _ <- munch1 isSpace
  f <- parseExpr
  return (App (App (App (Var "IF") c) t) f)

-- let x = e1; y = e2 in e3 支持顺序多绑定
-- let x = e1; y = e2 in e3 supports sequential multiple bindings.
parseLet :: ReadP Expr
parseLet = do
  _ <- string "let"
  _ <- munch1 isSpace
  binds <- greedySepBy1 parseBind (spaces *> char ';' <* spaces)
  spaces
  _ <- string "in"
  _ <- munch1 isSpace
  b <- parseExpr
  return (foldr (\(x, v) acc -> App (Lam x acc) v) b binds)
  where
    parseBind = do
      x <- ident
      spaces
      _ <- char '='
      spaces
      v <- parseExpr
      return (x, v)

-- 类型标注只做语法检查，归约时擦除；可用 :type expr : T 校验
-- A type annotation is syntax-checked and erased; :type expr : T verifies it.
typeTextP :: ReadP String
typeTextP = do
  a <- atom
  (do spaces
      void (string "->" <|> string "→")
      spaces
      b <- typeTextP
      return (a ++ " -> " ++ b)) <++ return a
  where
    atom =
      (do _ <- char '('
          spaces
          t <- typeTextP
          spaces
          _ <- char ')'
          return ("(" ++ t ++ ")"))
      <++ munch1 (\c -> isAlpha c || isDigit c || c `elem` ("_'" :: String))

parseLam :: ReadP Expr
parseLam = do
  void $ char '\\' <|> char 'λ'
  params <- greedySome $ lamIdent <* spaces
  lambdaSep
  spaces
  body <- parseExpr
  return $ foldr Lam body params

parseApp :: ReadP Expr
parseApp = foldl App <$> parseAtom <*> greedyMany (spaces *> parseAtom)

parseAtom :: ReadP Expr
parseAtom = notKeyword "in" *> notKeyword "then" *> notKeyword "else"
            *> (parseVar <++ parseList <++ parseParens)

parseVar :: ReadP Expr
parseVar = Var <$> ident

-- 列表字面量 [a, b] 脱糖为 CONS a (CONS b NIL)
-- List literal [a, b] desugars to CONS a (CONS b NIL).
parseList :: ReadP Expr
parseList = between (char '[') (char ']') $ do
  spaces
  es <- greedySepBy parseExpr (spaces *> char ',' <* spaces)
  return (foldr (\h t -> App (App (Var "CONS") h) t) (Var "NIL") es)

parseParens :: ReadP Expr
parseParens = between (char '(') (char ')') $ do
  spaces
  e <- parseExpr
  spaces
  (do _ <- char ':'
      spaces
      _ <- typeTextP
      spaces
      return e) <++ return e


data ParseError = ParseError { pePos :: Int, peMsg :: Msg }
  deriving (Show)

runParserFull :: ReadP a -> String -> Either ParseError a
runParserFull p s =
  let results  = readP_to_S (p <* spaces) s
      complete = [x | (x, rest) <- results, null rest]
  in case complete of
       (x:_) -> Right x
       []    -> Left (mkParseError s results)

mkParseError :: String -> [(a, String)] -> ParseError
mkParseError s results =
  let consumed = maximum (0 : [length s - length rest | (_, rest) <- results])
      pos      = consumed + 1
      (p, m)   = diagnose s (drop consumed s) pos
  in ParseError p m

diagnose :: String -> String -> Int -> (Int, Msg)
diagnose s rest pos
  | Just i <- unmatchedParen s =
      (i, ("括号不匹配：第 " ++ show i ++ " 列的括号没有闭合"
          , "Unbalanced parenthesis at column " ++ show i))
  | isLambdaStart && not (hasSeparator s) =
      (pos, ("Lambda 表达式缺少分隔符（形如 λx. body、λx → body 或 \\x -> body）"
            , "Lambda abstraction is missing '.', '→' or '->', e.g. λx. body"))
  | null rest =
      (pos, ("语法错误，请检查表达式结构", "Syntax error, please check the expression"))
  | otherwise =
      (pos, ("无法继续解析：" ++ shorten 18 rest, "Cannot parse at: " ++ shorten 18 rest))
  where
    isLambdaStart = case dropWhile isSpace s of
      ('λ':_)  -> True
      ('\\':_) -> True
      _        -> False
    hasSeparator t = '.' `elem` t || '→' `elem` t || "->" `isPrefixOf` dropWhile (/= '-') t

unmatchedParen :: String -> Maybe Int
unmatchedParen s = go [] (zip [1..] s)
  where
    go stack ((i, c):cs)
      | c == '(' = go (i : stack) cs
      | c == ')' = case stack of
          []     -> Just i
          (_:st) -> go st cs
      | otherwise = go stack cs
    go [] []    = Nothing
    go (i:_) [] = Just i

-- ---------------------------------------------------------------------------
-- 命令 Commands
-- ---------------------------------------------------------------------------
-- 行尾 `--` / `#` 注释：只在空白之后才算注释，避免切掉标识符里的运算符
-- Trailing `--` / `#` comments: only after whitespace, so operator names survive.
stripTrailingComment :: String -> String
stripTrailingComment = go []
  where
    go acc [] = reverse acc
    go acc ('-':'-':cs)
      | null acc || isSpace (head acc) = reverse acc
      | otherwise = go ('-':acc) ('-':cs)
    go acc ('#':cs)
      | null acc || isSpace (head acc) = reverse acc
      | otherwise = go ('#':acc) cs
    go acc (c:cs) = go (c:acc) cs

trim :: String -> String
trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse

data Command
  = Eval Expr
  | Trace Expr
  | Ast Expr
  | DbView Expr
  | Nf Expr
  | Whnf Expr
  | SetStrategy Strategy
  | SetSteps Int
  | SetEta Bool
  | SetLang Lang
  | Help
  | Quit

knownCommands :: [String]
knownCommands =
  [ ":help", ":trace", ":ast", ":db", ":nf", ":whnf"
  , ":strategy", ":steps", ":eta", ":lang", ":q" ]

parseCommand :: String -> Either ParseError Command
parseCommand raw
  | null s = Left (ParseError 1 ("空输入", "Empty input"))
  | s `elem` [":help", ":h", ":?"] = Right Help
  | s `elem` [":q", ":quit"] = Right Quit
  | Just rest <- stripPrefix ":lang " s =
      maybe (Left (ParseError 1
              ("未知语言，可用：zh / en / both", "Unknown language; use zh / en / both")))
            (Right . SetLang) (parseLang (trim rest))
  | Just rest <- stripPrefix ":strategy " s =
      maybe (Left (ParseError 1
              ("未知策略，可用：applicative / normal / cbn / cbv"
              , "Unknown strategy; use applicative / normal / cbn / cbv")))
            (Right . SetStrategy) (parseStrategy (trim rest))
  | Just rest <- stripPrefix ":steps " s =
      case reads (trim rest) :: [(Int, String)] of
        [(n, "")] | n > 0 -> Right (SetSteps n)
        _ -> Left (ParseError 1 ("用法：:steps <正整数>", "Usage: :steps <positive integer>"))
  | s == ":eta" = Right (SetEta True)
  | Just rest <- stripPrefix ":eta " s =
      case map lower (trim rest) of
        "on"    -> Right (SetEta True)
        "true"  -> Right (SetEta True)
        "1"     -> Right (SetEta True)
        "off"   -> Right (SetEta False)
        "false" -> Right (SetEta False)
        "0"     -> Right (SetEta False)
        _ -> Left (ParseError 1 ("用法：:eta on|off", "Usage: :eta on|off"))
  | Just rest <- stripPrefix ":trace " s = Trace <$> parseExpr' rest
  | Just rest <- stripPrefix ":ast " s = Ast <$> parseExpr' rest
  | Just rest <- stripPrefix ":db " s = DbView <$> parseExpr' rest
  | Just rest <- stripPrefix ":nf " s = Nf <$> parseExpr' rest
  | Just rest <- stripPrefix ":whnf " s = Whnf <$> parseExpr' rest
  | Just _ <- stripPrefix ":" s = Left (ParseError 1
      ( "未知命令 " ++ takeWhile (not . isSpace) s ++ "，输入 :help 查看全部命令"
      , "Unknown command " ++ takeWhile (not . isSpace) s ++ "; type :help for the full list" ))
  | otherwise = Eval <$> runParserFull parseExpr s
  where
    s = trim (stripTrailingComment raw)
    lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c
    parseExpr' src = case runParserFull parseExpr (trim src) of
      Left e  -> Left e { pePos = pePos e + (length s - length (trim src)) }
      Right x -> Right x

-- ---------------------------------------------------------------------------
-- 状态 State
-- ---------------------------------------------------------------------------
data ReplState = ReplState
  { rsStrategy :: Strategy
  , rsLimit    :: Int
  , rsEta      :: Bool
  , rsLang     :: Lang
  }

say :: ReplState -> String -> String -> String
say st zh en = renderMsg (rsLang st) (zh, en)

emit :: String -> String -> IO ()
emit kind text = putStrLn (decorate kind ++ text)
  where
    decorate "result" = "⇒ "
    decorate "step"   = "  → "
    decorate "warn"   = "⚠ "
    decorate "fail"   = "⚠ "
    decorate _        = ""

printEval :: ReplState -> EvalResult -> IO ()
printEval st res = do
  let final = erFinal res
      steps = erCount res
      stepTxt = if steps > 0
                  then "  (" ++ say st (show steps ++ " 步") (show steps ++ " steps") ++ ")"
                  else ""
      cycTxt = if erCycle res
                 then say st "（检测到重复项，疑似发散）"
                            " (a repeated term was detected; likely divergent)"
                 else ""
  if erLimitHit res
    then emit "warn" (pretty final ++ stepTxt ++ cycTxt ++ say st
           (" —— 已达到 " ++ show (rsLimit st) ++ " 步上限，归约未完成")
           (" -- step limit " ++ show (rsLimit st) ++ " reached, reduction incomplete"))
    else emit "result" (pretty final ++ stepTxt ++ valueHint final ++ cycTxt)

runCommand :: ReplState -> Command -> IO (Maybe ReplState)
runCommand st (Eval expr) = do
  printEval st (evalFinal (rsEta st) (rsLimit st) (rsStrategy st) expr)
  return (Just st)
runCommand st (Trace expr) = do
  let res = evalTraceWith (rsEta st) (rsLimit st) (rsStrategy st) expr
  putStrLn $ say st
    ("归约轨迹（" ++ strategyLabelZh (rsStrategy st) ++ "，共 " ++ show (erCount res) ++ " 步）")
    ("Reduction trace (" ++ strategyLabelEn (rsStrategy st) ++ ", " ++ show (erCount res) ++ " steps)")
  putStrLn $ "  0. " ++ pretty expr
  forM_ (erSteps res) $ \s -> do
    putStrLn $ "  " ++ show (tsIndex s) ++ ". [" ++ tsRule s ++ "] " ++ tsNote s
    putStrLn $ "       " ++ pretty (tsAfter s)
  when (erCount res > length (erSteps res)) $ putStrLn (say st
    "  ⚠ 轨迹较长，只显示前 500 步" "  ⚠ Long trace: only the first 500 steps are shown")
  when (erLimitHit res) $ putStrLn (say st
    "  ⚠ 已达到步数上限，归约未完成" "  ⚠ Step limit reached, reduction incomplete")
  return (Just st)
runCommand st (Ast expr)
  | exprSize expr <= astBudget = putStrLn (unlines (treeLines expr)) >> return (Just st)
  | otherwise = putStrLn (say st
      "  ⚠ 项过大，已省略语法树（节点上限 400）"
      "  ⚠ Term too large; AST omitted (400-node limit)") >> return (Just st)
runCommand st (DbView expr)
  | exprSize expr <= astBudget = putStrLn (deBruijnView expr) >> return (Just st)
  | otherwise = putStrLn (shorten 1000 (deBruijnView expr)) >> return (Just st)
runCommand st (Nf expr) = do
  printEval st (evalFinal (rsEta st) (rsLimit st) Normal expr)
  return (Just st)
runCommand st (Whnf expr) = do
  printEval st (evalWHNF (rsEta st) (rsLimit st) (rsStrategy st) expr)
  return (Just st)
runCommand st (SetStrategy s) = do
  emit "info" (say st
    ("求值策略：" ++ strategyLabelZh s)
    ("Strategy: " ++ strategyLabelEn s))
  return (Just st { rsStrategy = s })
runCommand st (SetSteps n) = do
  emit "info" (say st ("归约步数上限：" ++ show n) ("Reduction step limit: " ++ show n))
  return (Just st { rsLimit = n })
runCommand st (SetEta on) = do
  emit "info" (say st
    ("η 归约：" ++ if on then "开启" else "关闭")
    ("Eta reduction: " ++ if on then "on" else "off"))
  return (Just st { rsEta = on })
runCommand st (SetLang l) = do
  emit "info" (tr l "语言已切换为中文。" "Language switched to English.")
  return (Just st { rsLang = l })
runCommand st Help = putStrLn (helpMessage (rsLang st)) >> return (Just st)
runCommand _ Quit = return Nothing

helpMessage :: Lang -> String
helpMessage lang = unlines $ map (renderMsg lang)
  [ ("λ 演算解释器（最小版）", "λ Calculus interpreter (minimal)")
  , ("", "")
  , ("用法: ./main [--lang zh|en|both] [-v]", "Usage: ./main [--lang zh|en|both] [-v]")
  , ("", "")
  , ("命令:", "Commands:")
  , ("  :trace <表达式>  显示完整归约轨迹", "  :trace <expr>    show the full reduction trace")
  , ("  :ast <表达式>    显示语法树", "  :ast <expr>      show the syntax tree")
  , ("  :db <表达式>     de Bruijn 索引视图", "  :db <expr>       de Bruijn index view")
  , ("  :nf <表达式>     归约到正规形", "  :nf <expr>       reduce to normal form")
  , ("  :whnf <表达式>   归约到弱首正规形", "  :whnf <expr>     reduce to weak head normal form")
  , ("  :strategy <名称> 切换求值策略", "  :strategy <name> switch evaluation strategy")
  , ("  :steps <n>       设置归约步数上限", "  :steps <n>       set the reduction step limit")
  , ("  :eta on|off      开启/关闭 η 归约", "  :eta on|off      turn eta reduction on/off")
  , ("  :lang <值>       切换语言 zh/en/both", "  :lang <v>        switch language zh/en/both")
  , ("  :help            显示本帮助", "  :help            show this help")
  , ("  :q               退出", "  :q               quit")
  , ("", "")
  , ("抽象: λx.body、λx → body 或 \\x -> body；应用: f a（左结合）；括号: (expr)",
     "Abstraction: λx.body, λx → body or \\x -> body; application: f a (left-assoc); grouping: (expr)")
  , ("let: let x = e1 in e2；类型标注: (e : T)；行尾 -- / # 注释",
     "let: let x = e1 in e2; annotation: (e : T); trailing -- / # comments")
  , ("REPL 中行尾 \\ 或圆括号/方括号未闭合会续行",
     "A trailing \\ or open parentheses/brackets continue the REPL line")
  ]

-- ---------------------------------------------------------------------------
-- REPL
-- ---------------------------------------------------------------------------
handleLine :: ReplState -> String -> IO (Maybe ReplState)
handleLine st line =
  case parseCommand line of
    Left err -> do
      putStrLn (renderMsg (rsLang st)
        ( "解析错误: 第 " ++ show (pePos err) ++ " 列 — " ++ fst (peMsg err)
        , "Parse error at column " ++ show (pePos err) ++ " -- " ++ snd (peMsg err) ))
      return (Just st)
    Right cmd -> runCommand st cmd

replSettings :: ReplState -> Maybe FilePath -> Settings IO
replSettings st hist =
  setComplete (completeWord Nothing " \t(),.\\λ→" (completeFn st))
              (defaultSettings { historyFile = hist })

completeFn :: ReplState -> String -> IO [Completion]
completeFn _ left = return $ map simpleCompletion (filter (left `isPrefixOf`) knownCommands)

historyPath :: IO (Maybe FilePath)
historyPath = do
  r <- catch (Right <$> getHomeDirectory)
             (\(e :: SomeException) -> return (Left (show e)))
  return $ either (const Nothing) (Just . (++ "/.lambda_history")) r

-- REPL 多行输入：行尾反斜杠或圆括号/方括号未闭合时继续读下一行
-- Multi-line REPL input: a trailing backslash or open parentheses/brackets continue the line.
parenBalance :: String -> Int
parenBalance = foldl' step 0
  where
    step d '(' = d + 1
    step d '[' = d + 1
    step d ')' = d - 1
    step d ']' = d - 1
    step d _   = d

readReplLine :: InputT IO (Maybe String)
readReplLine = do
  term <- liftIO (hIsTerminalDevice stdin)
  go term [] 0 (0 :: Int)
  where
    go term acc depth n
      | n >= 20 = return (Just (unwords (reverse acc)))
      | otherwise = do
          m <- readOneLine term (if null acc then "λ> " else "  … ")
          case m of
            Nothing -> return Nothing
            Just raw ->
              let t    = reverse (dropWhile isSpace (reverse (stripTrailingComment raw)))
                  (body, cont) = case reverse t of
                                   ('\\':rest) -> (reverse rest, True)
                                   _           -> (t, False)
                  acc'   = trim body : acc
                  depth' = depth + parenBalance body
              in if cont || depth' > 0
                   then go term acc' depth' (n + 1)
                   else return (Just (unwords (reverse acc')))
    -- 管道输入按句柄编码读取：Haskeline 会用控制台代码页解码，UTF-8 会被弄乱
    -- Piped input is read with the handle's encoding; Haskeline would decode it
    -- with the console code page and garble UTF-8.
    readOneLine term prompt
      | term = getInputLine prompt
      | otherwise = do
          liftIO (hPutStr stdout prompt)
          atEof <- liftIO (hIsEOF stdin)
          if atEof then return Nothing else Just <$> liftIO (hGetLine stdin)

repl :: ReplState -> InputT IO ()
repl st = do
  minput <- readReplLine
  case minput of
    Nothing    -> return ()
    Just input -> do
      -- 与扩展版一致：Ctrl+C 只中断当前计算，REPL 继续运行
      -- Match the extended REPL: Ctrl+C interrupts only the current command.
      me <- liftIO $ handleLine st input `catch` \(e :: AsyncException) ->
        case e of
          UserInterrupt -> do
            emit "warn" (say st "已中断当前计算。" "Interrupted.")
            return (Just st)
          _ -> throwIO e
      forM_ me repl

-- 解析命令行；未知选项直接报错，避免拼写错误被静默忽略
-- Parse the command line; unknown options are errors instead of being ignored.
parseArgs :: [String] -> Either String (Lang, Bool, Bool)
parseArgs = go Both False False
  where
    go lang help version [] = Right (lang, help, version)
    go lang _ version ("--help":xs)    = go lang True version xs
    go lang _ version ("-h":xs)        = go lang True version xs
    go lang help _ ("--version":xs)    = go lang help True xs
    go lang help _ ("-v":xs)           = go lang help True xs
    go _ help version ("--lang":xs) = case xs of
      (v:rest) -> case parseLang v of
        Just l  -> go l help version rest
        Nothing -> Left ("未知语言 / unknown language: " ++ v)
      [] -> Left "缺少 --lang 的值 / missing value for --lang"
    go _ help version (x:xs)
      | Just v <- stripPrefix "--lang=" x =
          case parseLang v of
            Just l  -> go l help version xs
            Nothing -> Left ("未知语言 / unknown language: " ++ v)
      | "-" `isPrefixOf` x = Left ("未知选项 / unknown option: " ++ x)
      | otherwise = Left ("无法识别的参数 / unexpected argument: " ++ x)

main :: IO ()
main = do
  args <- getArgs
  case parseArgs args of
    Left err -> do
      hPutStrLn stderr err
      exitFailure
    Right (lang, help, version) -> do
      -- 每个流按各自是否为终端决定编码；非交互输入还要设置 locale 编码，
      -- 因为 Haskeline 用 locale 编码读取管道输入
      -- Give each stream its own decision: a piped or redirected stream uses
      -- UTF-8, an interactive one keeps the console code page, and the locale
      -- encoding follows because Haskeline reads piped input through it.
      inTerm  <- hIsTerminalDevice stdin
      outTerm <- hIsTerminalDevice stdout
      errTerm <- hIsTerminalDevice stderr
      unless inTerm $ do
        hSetEncoding stdin utf8
        setLocaleEncoding utf8
      unless outTerm $ hSetEncoding stdout utf8
      unless errTerm $ hSetEncoding stderr utf8
      if help
        then putStrLn (helpMessage lang)
        else if version
          then putStrLn versionString
          else do
            let st0 = ReplState Applicative defaultLimit False lang
            hist <- historyPath
            runInputT (replSettings st0 hist) (repl st0)

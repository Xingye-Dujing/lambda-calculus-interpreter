{-# LANGUAGE ScopedTypeVariables #-}
{-# LANGUAGE RecordWildCards #-}
{-# LANGUAGE LambdaCase #-}

import qualified Data.Map.Strict as Map
import qualified Data.Set as Set
import Control.Applicative ((<|>))
import Control.Exception (catch, SomeException)
import Control.Monad (void, when, unless, forM_, forM, guard)
import Control.Monad.IO.Class (liftIO)
import Data.Char (isAlpha, isDigit, isSpace, ord)
import Data.List (elemIndex, find, stripPrefix, isPrefixOf, intercalate, foldl')
import Numeric (showHex)
import System.Environment (getArgs)
import System.IO
import System.Console.Haskeline
import Text.ParserCombinators.ReadP

-- ---------------------------------------------------------------------------
-- 双语支持 Bilingual Support
-- ---------------------------------------------------------------------------
data Lang = Zh | En | Both deriving (Eq, Show)

parseLang :: String -> Maybe Lang
parseLang s = lookup (map lower s)
  [ ("zh", Zh), ("cn", Zh), ("chinese", Zh), ("中文", Zh)
  , ("en", En), ("english", En), ("英文", En)
  , ("both", Both), ("bilingual", Both), ("双语", Both)
  ]
  where lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c

-- 中文 / English 二选一或并列
tr :: Lang -> String -> String -> String
tr Zh zh _  = zh
tr En _ en  = en
tr Both zh en = zh ++ " / " ++ en

type Msg = (String, String)

renderMsg :: Lang -> Msg -> String
renderMsg lang (zh, en) = tr lang zh en

-- ---------------------------------------------------------------------------
-- 表达式定义 Expression Definitions
-- ---------------------------------------------------------------------------
data Expr = Var String | Lam String Expr | App Expr Expr
  deriving (Eq, Show)

type Env = Map.Map String Expr

-- ---------------------------------------------------------------------------
-- 自由变量 Free Variables
-- ---------------------------------------------------------------------------
freeVars :: Expr -> Set.Set String
freeVars (Var x)      = Set.singleton x
freeVars (Lam x body) = Set.delete x (freeVars body)
freeVars (App f a)    = freeVars f `Set.union` freeVars a

-- ---------------------------------------------------------------------------
-- 新变量 Fresh Variable
-- ---------------------------------------------------------------------------
freshVar :: String -> Set.Set String -> String
freshVar base avoid
  | base `Set.notMember` avoid = base
  | otherwise                  = freshVar (base ++ "'") avoid

-- ---------------------------------------------------------------------------
-- 无捕获替换 Capture-Avoiding Substitution
-- ---------------------------------------------------------------------------
subst :: String -> Expr -> Expr -> Expr
subst x v (Var y)
  | x == y    = v
  | otherwise = Var y
subst x v (App e1 e2) = App (subst x v e1) (subst x v e2)
subst x v (Lam y body)
  | x == y    = Lam y body
  | y `Set.notMember` fvV = Lam y (subst x v body)
  | otherwise = Lam y' (subst x v body')
  where
    fvV      = freeVars v
    y'       = freshVar y (freeVars body `Set.union` fvV)
    body'    = subst y (Var y') body

-- ---------------------------------------------------------------------------
-- α 等价（de Bruijn 化后比较）Alpha Equivalence
-- ---------------------------------------------------------------------------
data DB = DVar Int | DFree String | DLam String DB | DApp DB DB
  deriving (Eq)

-- 绑定变量转成索引，自由变量保留名字，因此可以直接判断 α 等价
-- Bound variables become indices; free variables keep their names, so α-equivalence is structural equality.
toDB :: [String] -> Expr -> DB
toDB bound (Var x) = maybe (DFree x) DVar (elemIndex x bound)
toDB bound (Lam x b) = DLam x (toDB (x : bound) b)
toDB bound (App f a) = DApp (toDB bound f) (toDB bound a)

alphaEq :: Expr -> Expr -> Bool
alphaEq a b = toDB [] a == toDB [] b

-- ---------------------------------------------------------------------------
-- 求值策略 Evaluation Strategies
-- ---------------------------------------------------------------------------
data Strategy = Applicative | Normal | CallByName | CallByValue
  deriving (Eq, Show)

strategyId :: Strategy -> String
strategyId Applicative = "applicative"
strategyId Normal      = "normal"
strategyId CallByName  = "cbn"
strategyId CallByValue = "cbv"

strategyLabel :: Strategy -> String
strategyLabel Applicative = "应用序（最左最内）"
strategyLabel Normal      = "正规序（最左最外）"
strategyLabel CallByName  = "按名调用（弱）"
strategyLabel CallByValue = "按值调用（弱）"

parseStrategy :: String -> Maybe Strategy
parseStrategy s = lookup (map lower s)
  [ ("applicative", Applicative), ("app", Applicative), ("value", Applicative)
  , ("normal", Normal), ("no", Normal), ("lazy", Normal)
  , ("cbn", CallByName), ("byname", CallByName), ("name", CallByName)
  , ("cbv", CallByValue), ("byvalue", CallByValue)
  ]
  where lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c

-- ---------------------------------------------------------------------------
-- 单步归约 One-Step Reduction
-- 每一步都返回「整个项」的新形态，方便前端做前后对比
-- Each step rewrites the whole term, so the frontend can diff before/after.
-- ---------------------------------------------------------------------------
data Reduction = Reduction
  { redRule :: String   -- β / β+α
  , redNote :: String   -- 人类可读说明 / human-readable note
  , redTerm :: Expr     -- 归约后的项 / resulting term
  }

data StepOut = StepOut { soWhole :: Expr, soRed :: Reduction }

-- 替换时是否需要先 α-重命名（与 subst 的分支条件保持一致）
alphaNeeded :: String -> Expr -> Expr -> Bool
alphaNeeded x body arg = go body
  where
    fvA = freeVars arg
    go (Lam y b)
      | y /= x && y `Set.member` fvA && x `Set.member` freeVars b = True
      | otherwise = go b
    go (App f a) = go f || go a
    go _         = False

betaStep :: String -> Expr -> Expr -> Reduction
betaStep x body arg =
  let needs  = alphaNeeded x body arg
      after  = subst x arg body
      rule   = if needs then "β+α" else "β"
      note   = "β 归约 β-reduction: (λ" ++ x ++ ". …) " ++ shorten 42 (pretty arg)
               ++ (if needs then "  （先 α-重命名 α-rename 避免变量捕获 capture）" else "")
  in Reduction rule note after

-- 求值策略只影响四件事 / a strategy is four booleans:
--   · 是否归约 λ 体内   reduce under lambdas
--   · 是否先试根 redex   contract at the root before descending
--   · 参数是否必须先成为值 require the argument to be a value
--   · 函数不是 λ 时是否还归约参数 reduce the argument when the head is not a λ
data Order = Order
  { underLambda :: Bool
  , redexFirst  :: Bool
  , argsToValue :: Bool
  , argsIfLam   :: Bool
  }

orderOf :: Strategy -> Order
orderOf Applicative = Order True  False False False
orderOf Normal      = Order True  True  False False
orderOf CallByName  = Order False True  False False
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

data TraceStep = TraceStep
  { tsIndex  :: Int
  , tsBefore :: Expr
  , tsAfter  :: Expr
  , tsRule   :: String
  , tsNote   :: String
  }

data EvalResult = EvalResult
  { erFinal    :: Expr
  , erSteps    :: [TraceStep]
  , erCount    :: Int
  , erLimitHit :: Bool
  }

defaultLimit :: Int
defaultLimit = 10000

-- 求值循环：keepTrace 为 False 时不保留轨迹（省内存）
-- Evaluation loop; with keepTrace=False the trace is dropped (saves memory).
eval :: Bool -> Int -> Strategy -> Expr -> EvalResult
eval keepTrace limit strat e0 = loop 1 e0 []
  where
    loop n e acc
      | n > limit = EvalResult e (reverse acc) (n - 1) True
      | otherwise = case stepOnce strat e of
          Just s ->
            let red  = soRed s
                acc' = if keepTrace
                         then TraceStep n e (soWhole s) (redRule red) (redNote red) : acc
                         else acc
            in loop (n + 1) (soWhole s) acc'
          Nothing -> EvalResult e (reverse acc) (n - 1) False

evalTrace :: Int -> Strategy -> Expr -> EvalResult
evalTrace = eval True

-- ---------------------------------------------------------------------------
-- 宏展开（带绑定集与展开燃料）Macro Expansion
-- ---------------------------------------------------------------------------
expandFuel :: Int
expandFuel = 20000

expand :: Int -> Env -> Set.Set String -> Expr -> Expr
expand fuel _ _ e | fuel <= 0 = e
expand fuel env bound (Var x)
  | x `Set.member` bound = Var x
  | Just e <- Map.lookup x env = expand (fuel - 1) env bound e
  | otherwise = Var x
expand fuel env bound (Lam x body) = Lam x (expand fuel env (Set.insert x bound) body)
expand fuel env bound (App f a)    = App (expand fuel env bound f) (expand fuel env bound a)

expandTop :: Env -> Expr -> Expr
expandTop env = expand expandFuel env Set.empty

-- ---------------------------------------------------------------------------
-- 语义提示 Semantic Hints：Church 编码 / 组合子
-- ---------------------------------------------------------------------------
isChurchNumeral :: Expr -> Maybe Integer
isChurchNumeral (Lam f (Lam x body)) = go 0 body
  where
    go n (Var x')   | x' == x = Just n
    go n (App (Var f') rest) | f' == f = go (n + 1) rest
    go _ _ = Nothing
isChurchNumeral _ = Nothing

isChurchBoolean :: Expr -> Maybe Bool
isChurchBoolean (Lam t (Lam _ (Var t'))) | t == t' = Just True
isChurchBoolean (Lam _ (Lam f (Var f'))) | f == f' = Just False
isChurchBoolean _ = Nothing

unapply :: Expr -> (Expr, [Expr])
unapply = go []
  where
    go acc (App f a) = go (a : acc) f
    go acc x         = (x, acc)

isChurchPair :: Expr -> Maybe (Expr, Expr)
isChurchPair (Lam f body) =
  case unapply body of
    (Var g, [a, b]) | g == f -> Just (a, b)
    _ -> Nothing
isChurchPair _ = Nothing

-- 已知组合子（用 α 等价比较）/ known combinators, compared by α-equivalence
combinators :: [(String, Expr)]
combinators =
  [ ("I", Lam "x" (Var "x"))
  , ("K", Lam "x" (Lam "y" (Var "x")))
  , ("S", Lam "x" (Lam "y" (Lam "z" (App (App (Var "x") (Var "z")) (App (Var "y") (Var "z"))))))
  , ("B", Lam "x" (Lam "y" (Lam "z" (App (Var "x") (App (Var "y") (Var "z"))))))
  , ("C", Lam "x" (Lam "y" (Lam "z" (App (App (Var "x") (Var "z")) (Var "y")))))
  , ("W", Lam "x" (Lam "y" (App (App (Var "x") (Var "y")) (Var "y"))))
  ]

combinatorOf :: Expr -> Maybe String
combinatorOf e = fst <$> find (alphaEq e . snd) combinators

valueHint :: Lang -> Expr -> String
valueHint lang e = case (isChurchNumeral e, isChurchBoolean e, isChurchPair e) of
  (Just 0, Just False, _) -> "  " ++ tr lang
    "(邱奇数 0 / Church 布尔值 False)"
    "(Church numeral 0 / Church boolean False)"
  (Just n, _, _) -> "  " ++ tr lang
    ("邱奇数 " ++ show n) ("Church numeral " ++ show n)
  (_, Just True, _) -> "  " ++ tr lang
    "(Church 布尔值 True / K 组合子)"
    "(Church boolean True / K combinator)"
  (_, Just False, _) -> "  " ++ tr lang
    "(Church 布尔值 False)" "(Church boolean False)"
  (_, _, Just (a, b)) -> "  " ++ tr lang
    ("(Church 序对 " ++ shorten 20 (pretty a) ++ ", " ++ shorten 20 (pretty b) ++ ")")
    ("(Church pair " ++ shorten 20 (pretty a) ++ ", " ++ shorten 20 (pretty b) ++ ")")
  _ -> case combinatorOf e of
         Just n  -> "  " ++ tr lang
           ("(" ++ n ++ " 组合子)") ("(" ++ n ++ " combinator)")
         Nothing -> ""

-- ---------------------------------------------------------------------------
-- 美观打印 Pretty Printing
-- ---------------------------------------------------------------------------
pretty :: Expr -> String
pretty = go 0
  where
    go :: Int -> Expr -> String
    go _ (Var x) = x
    go p (Lam x body) = let s = "λ" ++ x ++ " → " ++ go 0 body
                        in if p > 0 then "(" ++ s ++ ")" else s
    go p (App f a) = let s = go 1 f ++ " " ++ go 2 a
                     in if p > 1 then "(" ++ s ++ ")" else s

shorten :: Int -> String -> String
shorten n s
  | length s <= n = s
  | otherwise     = take (max 0 (n - 1)) s ++ "…"

-- ---------------------------------------------------------------------------
-- 语法树渲染 Render Syntax Tree
-- ---------------------------------------------------------------------------
treeLines :: Expr -> [String]
treeLines (Var x)     = ["• " ++ x]
treeLines (Lam x b)   = ("λ " ++ x) : fork "└ " "  " (treeLines b)
treeLines (App f a)   = "App" : fork "├ " "│ " (treeLines f) ++ fork "└ " "  " (treeLines a)

fork :: String -> String -> [String] -> [String]
fork _ _ []       = []
fork first rest (l:ls) = (first ++ l) : map (rest ++) ls

-- de Bruijn 索引视图
deBruijnView :: Expr -> String
deBruijnView = go []
  where
    go bound (Var x) = maybe x (('#' :) . show) (elemIndex x bound)
    go bound (Lam x b) = "λ." ++ go (x : bound) b
    go bound (App f a) = "(" ++ go bound f ++ " " ++ go bound a ++ ")"

-- ---------------------------------------------------------------------------
-- 解析器 Parser
-- ---------------------------------------------------------------------------
spaces :: ReadP ()
spaces = skipMany (satisfy isSpace)

isOperatorChar :: Char -> Bool
isOperatorChar ch = ch `elem` ("+*-/%^?!<>|&~#$" :: String)

ident :: ReadP String
ident = do
  c <- satisfy (\ch -> isAlpha ch || isOperatorChar ch)
  cs <- munch (\ch -> isAlpha ch || isDigit ch || ch `elem` ("_'" :: String) || isOperatorChar ch)
  return (c : cs)

parseExpr :: ReadP Expr
parseExpr = spaces *> (parseLam <++ parseApp)

parseLam :: ReadP Expr
parseLam = do
  void $ char '\\' <|> char 'λ'
  params <- many1 $ ident <* spaces
  void $ char '.'
  spaces
  body <- parseExpr
  return $ foldr Lam body params

parseApp :: ReadP Expr
parseApp = foldl App <$> parseAtom <*> many (spaces *> parseAtom)

parseAtom :: ReadP Expr
parseAtom = parseNum <++ parseVar <++ parseParens

parseNum :: ReadP Expr
parseNum = do
  ds <- munch1 isDigit
  guard (length ds <= 4)
  return $ churchNumeral (read ds)

churchNumeral :: Integer -> Expr
churchNumeral n = Lam "f" . Lam "x" $
  iterate (App (Var "f")) (Var "x") !! fromIntegral n

parseVar :: ReadP Expr
parseVar = Var <$> ident

parseParens :: ReadP Expr
parseParens = between (char '(') (char ')') $ spaces *> parseExpr <* spaces

-- 带位置信息的解析错误 / parse error with a 1-based column
data ParseError = ParseError
  { pePos :: Int      -- 1 起算的列号 / 1-based column
  , peMsg :: Msg
  }
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
      leftover = drop consumed s
      (p, m)   = diagnose s leftover pos
  in ParseError p m

diagnose :: String -> String -> Int -> (Int, Msg)
diagnose s rest pos
  | Just i <- unmatchedParen s =
      (i, ( "括号不匹配：第 " ++ show i ++ " 列的括号没有闭合"
          , "Unbalanced parenthesis at column " ++ show i ))
  | isLambdaStart && not ('.' `elem` s) =
      (pos, ( "Lambda 表达式缺少 '.' 分隔符（形如 λx. body）"
            , "Lambda abstraction is missing '.', e.g. λx. body" ))
  | Just (i, c) <- firstIllegal s =
      (i, ( "非法字符 '" ++ [c] ++ "'，只允许 λ \\ → . 字母 数字 ' _ 和括号"
           , "Illegal character '" ++ [c] ++ "'; expected λ \\ → . letters digits ' _ or parentheses" ))
  | null rest =
      (pos, ("语法错误，请检查表达式结构", "Syntax error, please check the expression"))
  | otherwise =
      (pos, ( "无法继续解析：" ++ shorten 18 rest
            , "Cannot parse at: " ++ shorten 18 rest ))
  where
    isLambdaStart = case dropWhile isSpace s of
      ('λ':_) -> True
      ('\\':_) -> True
      _ -> False

-- 找到第一个未匹配的右括号或未闭合的左括号
-- First unmatched right parenthesis, or the last unclosed left one.
unmatchedParen :: String -> Maybe Int
unmatchedParen s = go [] (zip [1..] s)
  where
    go stack ((i, c):cs)
      | c == '(' = go (i : stack) cs
      | c == ')' = case stack of
          []     -> Just i            -- 多余的右括号 / stray ')'
          (_:st) -> go st cs
      | otherwise = go stack cs
    go [] []       = Nothing
    go (i:_) []    = Just i           -- 未闭合的左括号 / unclosed '('

firstIllegal :: String -> Maybe (Int, Char)
firstIllegal s = case [(i, c) | (i, c) <- zip [1..] s, not (isLegal c)] of
  (x:_) -> Just x
  []    -> Nothing
  where
    isLegal c = isAlpha c || isDigit c || isSpace c
             || c `elem` ("λ\\→().=_'" :: String)
             || isOperatorChar c

-- ---------------------------------------------------------------------------
-- 解析赋值 / 命令 Parse Assignment and Commands
-- ---------------------------------------------------------------------------
trim :: String -> String
trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse

isValidVarName :: String -> Bool
isValidVarName [] = False
isValidVarName (c:cs) = isValidFirst c && all isValidRest cs
  where
    isValidFirst ch = isAlpha ch || isOperatorChar ch
    isValidRest  ch = isAlpha ch || isDigit ch || ch `elem` ("_'" :: String) || isOperatorChar ch

parseAssignment :: String -> Either ParseError (String, Expr)
parseAssignment str =
  let (beforeEq, rest) = break (== '=') str
      name = trim beforeEq
  in if null rest
       then Left (ParseError 1 ("缺少 '='", "Missing '='"))
       else if not (isValidVarName name)
         then Left (ParseError 1
                    ( "非法变量名 '" ++ name ++ "'（需字母或运算符开头）"
                    , "Invalid name '" ++ name ++ "' (must start with a letter or operator)" ))
         else
           let afterEq = drop 1 rest
               lead    = length afterEq - length (dropWhile isSpace afterEq)
               exprStr = trim afterEq
               offset  = length beforeEq + 1 + lead
           in case runParserFull parseExpr exprStr of
                Left e  -> Left e { pePos = pePos e + offset }
                Right x -> Right (name, x)

data Command
  = Eval Expr
  | Define String Expr
  | LoadFile FilePath
  | ShowEnv
  | DeleteDef String
  | ResetEnv
  | SetStrategy Strategy
  | SetSteps Int
  | Trace Expr
  | Ast Expr
  | DbView Expr
  | TypeOf Expr
  | Begin Expr
  | StepCmd
  | RunCmd
  | EndCmd
  | SetLang Lang
  | Help
  | Quit

knownCommands :: [(String, Msg)]
knownCommands =
  [ (":help", ("显示帮助", "show help"))
  , (":load", ("加载定义文件", "load a definitions file"))
  , (":let", ("定义变量", "define a variable"))
  , (":env", ("显示当前环境", "show the environment"))
  , (":del", ("删除一个定义", "delete a definition"))
  , (":reset", ("重置为预定义环境", "reset to the prelude"))
  , (":strategy", ("切换求值策略", "switch evaluation strategy"))
  , (":steps", ("设置归约步数上限", "set the reduction step limit"))
  , (":trace", ("显示完整归约轨迹", "show the full reduction trace"))
  , (":ast", ("显示语法树", "show the syntax tree"))
  , (":db", ("de Bruijn 索引视图", "de Bruijn index view"))
  , (":type", ("推断简单类型", "infer the simple type"))
  , (":begin", ("开始交互式归约", "start interactive reduction"))
  , (":step", ("归约一步", "reduce one step"))
  , (":run", ("归约到底", "reduce to the end"))
  , (":end", ("结束交互式归约", "end interactive reduction"))
  , (":lang", ("切换语言 zh/en/both", "switch language zh/en/both"))
  , (":q", ("退出", "quit"))
  ]

parseCommand :: String -> Either ParseError Command
parseCommand raw
  | null s = Left (ParseError 1 ("空输入", "Empty input"))
  | Just rest <- stripPrefix ":load " s = Right $ LoadFile (trim rest)
  | Just rest <- stripPrefix ":let " s = uncurry Define <$> parseAssignment rest
  | s == ":env" = Right ShowEnv
  | s == ":reset" = Right ResetEnv
  | s `elem` [":help", ":h", ":?"] = Right Help
  | s `elem` [":q", ":quit"] = Right Quit
  | s == ":step" = Right StepCmd
  | s == ":run" = Right RunCmd
  | s == ":end" = Right EndCmd
  | Just rest <- stripPrefix ":lang " s =
      maybe (Left (ParseError 1
              ("未知语言，可用：zh / en / both", "Unknown language; use zh / en / both")))
            (Right . SetLang) (parseLang (trim rest))
  | Just rest <- stripPrefix ":delete " s = deleteDef rest
  | Just rest <- stripPrefix ":del " s = deleteDef rest
  | Just rest <- stripPrefix ":strategy " s =
      maybe (Left (ParseError 1
              ("未知策略，可用：applicative / normal / cbn / cbv"
              , "Unknown strategy; use applicative / normal / cbn / cbv")))
            (Right . SetStrategy) (parseStrategy (trim rest))
  | Just rest <- stripPrefix ":steps " s =
      case reads (trim rest) :: [(Int, String)] of
        [(n, "")] | n > 0   -> Right (SetSteps n)
                  | otherwise -> Left (ParseError 1
                      ("步数上限必须是正整数", "The step limit must be a positive integer"))
        _ -> Left (ParseError 1 ("用法：:steps <正整数>", "Usage: :steps <positive integer>"))
  | Just rest <- stripPrefix ":trace " s = Trace <$> parseExpr' rest
  | Just rest <- stripPrefix ":ast " s = Ast <$> parseExpr' rest
  | Just rest <- stripPrefix ":db " s = DbView <$> parseExpr' rest
  | Just rest <- stripPrefix ":type " s = TypeOf <$> parseExpr' rest
  | Just rest <- stripPrefix ":begin " s = Begin <$> parseExpr' rest
  | Just _ <- stripPrefix ":" s = Left (ParseError 1
      ( "未知命令 " ++ takeWhile (not . isSpace) s ++ "，输入 :help 查看全部命令"
      , "Unknown command " ++ takeWhile (not . isSpace) s ++ "; type :help for the full list" ))
  | otherwise = case parseAssignment s of
      Right (name, expr) -> Right (Define name expr)
      Left err
        | '=' `elem` s -> Left err
        | otherwise    -> Eval <$> runParserFull parseExpr s
  where
    s = trim raw
    deleteDef rest =
      let name = trim rest
      in if null name
           then Left (ParseError 1 ("用法：:del <名字>", "Usage: :del <name>"))
           else Right (DeleteDef name)
    parseExpr' src = case runParserFull parseExpr (trim src) of
      Left e  -> Left e { pePos = pePos e + (length s - length (trim src)) }
      Right x -> Right x

-- ---------------------------------------------------------------------------
-- 简单类型推断 Simple Type Inference (Hindley–Milner)
-- ---------------------------------------------------------------------------
data Ty = TVar String | TArr Ty Ty deriving (Eq)

prettyTy :: Ty -> String
prettyTy = go 0
  where
    go :: Int -> Ty -> String
    go _ (TVar t) = t
    go p (TArr a b) =
      let s = go 1 a ++ " → " ++ go 0 b
      in if p > 0 then "(" ++ s ++ ")" else s

normalizeNames :: Ty -> Ty
normalizeNames t = fst (go t Map.empty)
  where
    go (TVar v) m = case Map.lookup v m of
      Just n  -> (TVar n, m)
      Nothing -> let n = "t" ++ show (Map.size m)
                 in (TVar n, Map.insert v n m)
    go (TArr a b) m =
      let (a', m1) = go a m
          (b', m2) = go b m1
      in (TArr a' b', m2)

freeTyVars :: Ty -> Set.Set String
freeTyVars (TVar v)   = Set.singleton v
freeTyVars (TArr a b) = freeTyVars a `Set.union` freeTyVars b

-- 把内部类型变量名（_seed_n）改写为 t0/t1，方便阅读
-- Rewrite internal type variable names (_seed_n) to t0/t1 for readability.
scrubTyNames :: String -> String
scrubTyNames = go Map.empty 0
  where
    go :: Map.Map String String -> Int -> String -> String
    go _ _ [] = []
    go m n (c:cs)
      | c == '_' =
          case span isDigit cs of
            (d1, '_':rest) | not (null d1) ->
              case span isDigit rest of
                (d2, rest') | not (null d2) ->
                  let key = '_' : d1 ++ "_" ++ d2
                  in case Map.lookup key m of
                       Just nm -> nm ++ go m n rest'
                       Nothing ->
                         let nm = "t" ++ show n
                         in nm ++ go (Map.insert key nm m) (n + 1) rest'
                _ -> '_' : go m n cs
            _ -> '_' : go m n cs
      | otherwise = c : go m n cs

data Scheme = Forall [String] Ty

data TISt = TISt { tiSeed :: Int, tiNext :: Int, tiSub :: Map.Map String Ty }

newtype TI a = TI { unTI :: TISt -> Either String (a, TISt) }

instance Functor TI where
  fmap f (TI g) = TI $ \s -> fmap (\(a, s') -> (f a, s')) (g s)

instance Applicative TI where
  pure a = TI $ \s -> Right (a, s)
  TI f <*> TI g = TI $ \s -> do
    (h, s1) <- f s
    (a, s2) <- g s1
    return (h a, s2)

instance Monad TI where
  TI g >>= f = TI $ \s -> do
    (a, s1) <- g s
    unTI (f a) s1

failTI :: String -> TI a
failTI e = TI $ \_ -> Left e

freshTy :: TI Ty
freshTy = TI $ \s ->
  let nm = "_" ++ show (tiSeed s) ++ "_" ++ show (tiNext s)
  in Right (TVar nm, s { tiNext = tiNext s + 1 })

getSub :: TI (Map.Map String Ty)
getSub = TI $ \s -> Right (tiSub s, s)

extendSub :: String -> Ty -> TI ()
extendSub a t = TI $ \s -> Right ((), s { tiSub = Map.insert a t (tiSub s) })

applySub :: Ty -> TI Ty
applySub (TVar a) = do
  sub <- getSub
  case Map.lookup a sub of
    Nothing -> return (TVar a)
    Just t  -> do
      t' <- applySub t
      extendSub a t'
      return t'
applySub (TArr a b) = TArr <$> applySub a <*> applySub b

occursIn :: String -> Ty -> TI Bool
occursIn a t = do
  t' <- applySub t
  case t' of
    TVar b        -> return (a == b)
    TArr x y      -> (||) <$> occursIn a x <*> occursIn a y

unify :: Ty -> Ty -> TI ()
unify t1 t2 = do
  a <- applySub t1
  b <- applySub t2
  case a of
    TVar x -> bindVar x b
    TArr x1 y1 -> case b of
      TVar y     -> bindVar y a
      TArr x2 y2 -> unify x1 x2 >> unify y1 y2

bindVar :: String -> Ty -> TI ()
bindVar x t = do
  t' <- applySub t
  case t' of
    TVar y | y == x -> return ()
    _ -> do
      occ <- occursIn x t'
      if occ then failTI ("无限类型 infinite type: " ++ x ++ " occurs in " ++ prettyTy t')
             else extendSub x t'

type TypeEnv = Map.Map String Scheme

instantiate :: Scheme -> TI Ty
instantiate (Forall vars t) = do
  pairs <- forM vars $ \v -> do
    tv <- freshTy
    return (v, tv)
  return (substTy (Map.fromList pairs) t)

substTy :: Map.Map String Ty -> Ty -> Ty
substTy m (TVar v) = Map.findWithDefault (TVar v) v m
substTy m (TArr a b) = TArr (substTy m a) (substTy m b)

infer :: TypeEnv -> Expr -> TI Ty
infer env (Var x) = case Map.lookup x env of
  Just sc -> instantiate sc
  Nothing -> freshTy
infer env (Lam x body) = do
  tv <- freshTy
  tb <- infer (Map.insert x (Forall [] tv) env) body
  return (TArr tv tb)
infer env (App f a) = do
  tf <- infer env f
  ta <- infer env a
  tv <- freshTy
  unify tf (TArr ta tv)
  return tv

generalize :: TypeEnv -> Ty -> TI Scheme
generalize env t = do
  t' <- applySub t
  let envFree = Set.unions
        [ freeTyVars ty `Set.difference` Set.fromList vs
        | Forall vs ty <- Map.elems env ]
  return (Forall (Set.toList (freeTyVars t' `Set.difference` envFree)) t')

runTI :: TI a -> Int -> Either String a
runTI m seed = case unTI m (TISt seed 0 Map.empty) of
  Left e       -> Left e
  Right (a, _) -> Right a

inferScheme :: TypeEnv -> Expr -> Either String Scheme
inferScheme tenv e = runTI (infer tenv e >>= generalize tenv) (Map.size tenv + 1)

-- ---------------------------------------------------------------------------
-- 预定义环境 Predefined Environment
-- ---------------------------------------------------------------------------
initEnv :: Env
initEnv = Map.fromList
  [ ("TRUE",  Lam "t" (Lam "f" (Var "t")))
  , ("FALSE", Lam "t" (Lam "f" (Var "f")))
  , ("NOT",   Lam "b" $ App (App (Var "b") (Var "FALSE")) (Var "TRUE"))
  , ("AND",   Lam "b1" $ Lam "b2" $ App (App (Var "b1") (Var "b2")) (Var "FALSE"))
  , ("OR",    Lam "b1" $ Lam "b2" $ App (App (Var "b1") (Var "TRUE")) (Var "b2"))
  , ("IF",    Lam "c" $ Lam "t" $ Lam "f" $ App (App (Var "c") (Var "t")) (Var "f"))
  , ("ZERO",  Lam "f" (Lam "x" (Var "x")))
  , ("ONE",   Lam "f" (Lam "x" (App (Var "f") (Var "x"))))
  , ("TWO",   Lam "f" (Lam "x" (App (Var "f") (App (Var "f") (Var "x")))))
  , ("THREE", Lam "f" (Lam "x" (App (Var "f") (App (Var "f") (App (Var "f") (Var "x"))))))
  , ("SUCC",  Lam "n" $ Lam "f" $ Lam "x" $ App (Var "f") (App (App (Var "n") (Var "f")) (Var "x")))
  , ("PLUS",  Lam "m" $ Lam "n" $ Lam "f" $ Lam "x" $ App (App (Var "m") (Var "f")) (App (App (Var "n") (Var "f")) (Var "x")))
  , ("MULT",  Lam "m" $ Lam "n" $ Lam "f" $ App (Var "m") (App (Var "n") (Var "f")))
  ]

initTypeEnv :: TypeEnv
initTypeEnv = buildTypeEnv Map.empty (Map.toList initEnv)

buildTypeEnv :: TypeEnv -> [(String, Expr)] -> TypeEnv
buildTypeEnv = foldl' step
  where
    step tenv (name, expr) = case inferScheme tenv expr of
      Right sc -> Map.insert name sc tenv
      Left _   -> tenv

-- ---------------------------------------------------------------------------
-- 输出 Reporter
-- ---------------------------------------------------------------------------
data ReplState = ReplState
  { rsEnv     :: Env
  , rsTypeEnv :: TypeEnv
  , rsStrategy :: Strategy
  , rsLimit   :: Int
  , rsJson    :: Bool
  , rsLang    :: Lang
  , rsCurrent :: Maybe Expr
  }

-- ---------------------------------------------------------------------------
-- 极简 JSON / a tiny JSON algebra
-- ---------------------------------------------------------------------------
data J = JStr String | JNum Int | JBool Bool | JArr [J] | JObj [(String, J)]

infixr 8 .=
(.=) :: String -> J -> (String, J)
k .= v = (k, v)

encode :: J -> String
encode = \case
  JStr s   -> quote s
  JNum n   -> show n
  JBool b  -> if b then "true" else "false"
  JArr xs  -> "[" ++ intercalate "," (map encode xs) ++ "]"
  JObj kvs -> "{" ++ intercalate "," [quote k ++ ":" ++ encode v | (k, v) <- kvs] ++ "}"

quote :: String -> String
quote s = "\"" ++ concatMap esc s ++ "\""
  where
    esc '"'  = "\\\""
    esc '\\' = "\\\\"
    esc '\n' = "\\n"
    esc '\r' = "\\r"
    esc '\t' = "\\t"
    esc c
      | ord c < 0x20 = "\\u" ++ replicate (4 - length h) '0' ++ h
      | otherwise    = [c]
      where h = showHex (ord c) ""

decorate :: String -> String
decorate "result" = "⇒ "
decorate "step"   = "  → "
decorate "warn"   = "⚠ "
decorate "fail"   = "⚠ "
decorate _        = ""

emit :: ReplState -> String -> String -> [(String, J)] -> IO ()
emit st kind text fields
  | rsJson st = putStrLn . encode $
      JObj (("kind" .= JStr kind) : ("text" .= JStr text) : fields)
  | otherwise = putStrLn (decorate kind ++ text)

traceField :: [TraceStep] -> (String, J)
traceField steps = "trace" .= JArr (map one (take 500 steps))
  where
    one s = JObj
      [ "n"      .= JNum (tsIndex s)
      , "rule"   .= JStr (tsRule s)
      , "note"   .= JStr (tsNote s)
      , "before" .= JStr (shorten 300 (pretty (tsBefore s)))
      , "after"  .= JStr (shorten 300 (pretty (tsAfter s))) ]

astField :: Expr -> (String, J)
astField e = "ast" .= JArr (map JStr (treeLines e))

treeField :: Expr -> (String, J)
treeField e = "tree" .= JArr (map JStr (treeLines e))

-- ---------------------------------------------------------------------------
-- 表格打印 Print Table
-- ---------------------------------------------------------------------------
padRight :: Int -> String -> String
padRight n s = s ++ replicate (max 0 (n - length s)) ' '

renderTable :: Lang -> [(String, String)] -> String
renderTable _ [] = ""
renderTable lang rows = unlines $
  [top, formatRow (renderMsg lang ("变量名", "Var Name"), renderMsg lang ("值", "Value")), mid]
  ++ map formatRow rows ++ [bottom]
  where
    col1Len = maximum $ length (renderMsg lang ("变量名", "Var Name")) : map (length . fst) rows
    col2Len = maximum $ length (renderMsg lang ("值", "Value")) : map (length . snd) rows
    mkBorder c1 c2 c3 = c1 : replicate (col1Len + 2) '─' ++ [c2] ++ replicate (col2Len + 2) '─' ++ [c3]
    top    = mkBorder '┌' '┬' '┐'
    mid    = mkBorder '├' '┼' '┤'
    bottom = mkBorder '└' '┴' '┘'
    formatRow (a, b) = "│ " ++ padRight col1Len a ++ " │ " ++ padRight col2Len b ++ " │"

-- ---------------------------------------------------------------------------
-- 文件加载 File Loading
-- ---------------------------------------------------------------------------
readFileSafe :: FilePath -> IO (Either String String)
readFileSafe path = catch (Right <$> readFile path)
  (\(e :: SomeException) -> return $ Left $ show e)

data LoadOutcome = LoadOutcome
  { loEnv     :: Env
  , loTypeEnv :: TypeEnv
  , loOk      :: [(String, Expr)]
  , loFail    :: [(Int, String)]
  }

loadDefinitionsFromFile :: Env -> TypeEnv -> FilePath -> IO (Either String LoadOutcome)
loadDefinitionsFromFile env0 tenv0 path = do
  contentOrErr <- readFileSafe path
  case contentOrErr of
    Left err -> return (Left err)
    Right content -> do
      let numbered = zip [1..] $ filter (not . null) $ lines content
      let start = LoadOutcome env0 tenv0 [] []
      let out = foldl' processLine start numbered
      return (Right out)
  where
    processLine acc (n, line) =
      case parseCommand line of
        Right (Define var expr) ->
          let expr' = expandTop (loEnv acc) expr
              env'  = Map.insert var expr' (loEnv acc)
              tenv' = case inferScheme (loTypeEnv acc) expr of
                Right sc -> Map.insert var sc (loTypeEnv acc)
                Left _   -> loTypeEnv acc
          in acc { loEnv = env', loTypeEnv = tenv', loOk = (var, expr') : loOk acc }
        _ -> acc { loFail = (n, line) : loFail acc }

-- ---------------------------------------------------------------------------
-- 命令执行 Command Execution
-- ---------------------------------------------------------------------------
runCommand :: ReplState -> Command -> IO (Maybe ReplState)
runCommand st (Eval expr) = do
  let e'    = expandTop (rsEnv st) expr
      res   = eval (rsJson st) (rsLimit st) (rsStrategy st) e'
      final = erFinal res
      hint  = valueHint (rsLang st) final
      steps = erCount res
      stepTxt = if steps > 0
                  then "  (" ++ say st (show steps ++ " 步") (show steps ++ " steps") ++ ")"
                  else ""
      text  = pretty final ++ stepTxt ++ hint
      mty   = either (const "") (prettyScheme (rsLang st))
                       (inferScheme (rsTypeEnv st) expr)
      fields = [ "steps"    .= JNum steps
               , "term"     .= JStr (pretty final)
               , "limitHit" .= JBool (erLimitHit res)
               , "hint"     .= JStr hint
               , "strategy" .= JStr (strategyId (rsStrategy st))
               , astField final
               , "db"       .= JStr (deBruijnView final) ]
               ++ [ "type" .= JStr mty | not (null mty) ]
               ++ [ traceField (erSteps res) | not (null (erSteps res)) ]
  if erLimitHit res
    then emit st "warn" (text ++ say st
          (" —— 已达到 " ++ show (rsLimit st) ++ " 步上限，归约未完成")
          (" -- step limit " ++ show (rsLimit st) ++ " reached, reduction incomplete")) fields
    else emit st "result" text fields
  return (Just st)
runCommand st (Define var expr) = do
  let expr' = expandTop (rsEnv st) expr
      env'  = Map.insert var expr' (rsEnv st)
      (tenv', mty) = case inferScheme (rsTypeEnv st) expr of
        Right sc -> (Map.insert var sc (rsTypeEnv st), Just (prettyScheme (rsLang st) sc))
        Left _   -> (rsTypeEnv st, Nothing)
      fields = [ "name"  .= JStr var
               , "value" .= JStr (pretty expr') ]
               ++ [ "type" .= JStr ty | Just ty <- [mty] ]
  emit st "define" ("defined " ++ var ++ " = " ++ pretty expr') fields
  return (Just st { rsEnv = env', rsTypeEnv = tenv' })
runCommand st (LoadFile path) = do
  res <- loadDefinitionsFromFile (rsEnv st) (rsTypeEnv st) path
  case res of
    Left err -> do
      emit st "fail" (say st ("文件加载错误: " ++ err) ("File load error: " ++ err)) []
      return (Just st)
    Right out -> do
      forM_ (reverse (loOk out)) $ \(name, ex) ->
        emit st "define" ("defined " ++ name ++ " = " ++ pretty ex)
          [ "name" .= JStr name
          , "value" .= JStr (pretty ex) ]
      forM_ (reverse (loFail out)) $ \(n, line) ->
        emit st "error" (say st
          ("解析错误: 第 " ++ show n ++ " 行: " ++ shorten 60 line)
          ("Parse error on line " ++ show n ++ ": " ++ shorten 60 line))
          [ "line" .= JNum n ]
      emit st "info" (say st
        ("成功加载 " ++ show (length (loOk out)) ++ " 个定义，失败 " ++ show (length (loFail out)) ++ " 行")
        ("Loaded " ++ show (length (loOk out)) ++ " definitions, " ++ show (length (loFail out)) ++ " lines failed"))
        [ "loaded" .= JNum (length (loOk out))
        , "failed" .= JNum (length (loFail out)) ]
      return $ Just st { rsEnv = loEnv out, rsTypeEnv = loTypeEnv out }
runCommand st ShowEnv = do
  let rows = [(n, pretty e) | (n, e) <- Map.toList (rsEnv st)]
  if null rows
    then emit st "info" (say st "当前环境为空。" "The environment is empty.") []
    else if rsJson st
      then emit st "env" "" [ "rows" .= JArr
             [ JObj ["name" .= JStr a, "value" .= JStr b] | (a, b) <- rows ] ]
      else putStr (renderTable (rsLang st) rows) >> hFlush stdout
  return (Just st)
runCommand st (DeleteDef name)
  | Map.member name (rsEnv st) = do
      emit st "info" (say st ("已删除 " ++ name) ("Deleted " ++ name)) []
      return $ Just st { rsEnv = Map.delete name (rsEnv st)
                       , rsTypeEnv = Map.delete name (rsTypeEnv st) }
  | otherwise = do
      emit st "fail" (say st ("未找到定义：" ++ name) ("Definition not found: " ++ name)) []
      return (Just st)
runCommand st ResetEnv = do
  emit st "info" (say st "环境已重置为预定义状态。" "Environment reset to the prelude.") []
  return $ Just st { rsEnv = initEnv, rsTypeEnv = initTypeEnv, rsCurrent = Nothing }
runCommand st (SetStrategy s) = do
  emit st "info" (say st
    ("求值策略：" ++ strategyLabel s ++ "（" ++ strategyId s ++ "）")
    ("Strategy: " ++ strategyLabelEn s ++ " (" ++ strategyId s ++ ")"))
    [ "strategy" .= JStr (strategyId s) ]
  return $ Just st { rsStrategy = s }
runCommand st (SetSteps n) = do
  emit st "info" (say st ("归约步数上限：" ++ show n) ("Reduction step limit: " ++ show n))
    [ "limit" .= JNum n ]
  return $ Just st { rsLimit = n }
runCommand st (Trace expr) = do
  let e'  = expandTop (rsEnv st) expr
      res = evalTrace (rsLimit st) (rsStrategy st) e'
      fields = [ "final"    .= JStr (pretty (erFinal res))
               , "steps"    .= JNum (erCount res)
               , "limitHit" .= JBool (erLimitHit res)
               , "strategy" .= JStr (strategyId (rsStrategy st))
               , traceField (erSteps res) ]
  if rsJson st
    then emit st "trace" "" fields
    else do
      putStrLn $ say st
        ("归约轨迹（" ++ strategyLabel (rsStrategy st) ++ "，共 " ++ show (erCount res) ++ " 步）")
        ("Reduction trace (" ++ strategyLabelEn (rsStrategy st) ++ ", " ++ show (erCount res) ++ " steps)")
      putStrLn $ "  0. " ++ pretty e'
      forM_ (erSteps res) $ \s -> do
        putStrLn $ "  " ++ show (tsIndex s) ++ ". " ++ tsNote s
        putStrLn $ "       " ++ pretty (tsAfter s)
      when (erLimitHit res) $ putStrLn (say st
        "  ⚠ 已达到步数上限，归约未完成"
        "  ⚠ Step limit reached, reduction incomplete")
  return (Just st)
runCommand st (Ast expr) = do
  let e' = expandTop (rsEnv st) expr
  if rsJson st
    then emit st "ast" "" [treeField e']
    else putStrLn (unlines (treeLines e'))
  return (Just st)
runCommand st (DbView expr) = do
  let e' = expandTop (rsEnv st) expr
  emit st "db" (deBruijnView e')
    [ astField e'
    , "term" .= JStr (pretty e') ]
  return (Just st)
runCommand st (TypeOf expr) = do
  case inferScheme (rsTypeEnv st) expr of
    Left err0 -> do
      let err = scrubTyNames err0
      emit st "fail" (say st ("无法类型化：" ++ err) ("Cannot type: " ++ err)) []
      return (Just st)
    Right sc -> do
      let ty = prettyScheme (rsLang st) sc
      if rsJson st
        then emit st "type" ty [ "type" .= JStr ty ]
        else putStrLn (say st ("类型：" ++ ty) ("Type: " ++ ty))
      return (Just st)
runCommand st (Begin expr) = do
  let e' = expandTop (rsEnv st) expr
      fields = [ "steps" .= JNum 0
               , "term" .= JStr (pretty e')
               , "strategy" .= JStr (strategyId (rsStrategy st)) ]
  if rsJson st
    then emit st "term" (pretty e') fields
    else putStrLn (say st
      ("开始手动归约：" ++ pretty e' ++ "\n  用 :step 归约一步，:run 归约到底，:end 结束。")
      ("Manual reduction started: " ++ pretty e' ++ "\n  Use :step to reduce one step, :run to finish, :end to stop."))
  return $ Just st { rsCurrent = Just e' }
runCommand st StepCmd = case rsCurrent st of
  Nothing -> do
    emit st "fail" (say st
      "当前没有进行中的归约，先用 :begin <表达式> 开始。"
      "No reduction in progress; start one with :begin <expr>.") []
    return (Just st)
  Just e -> case stepOnce (rsStrategy st) e of
    Nothing -> do
      emit st "info" (say st ("已是正规形：" ++ pretty e) ("Already in normal form: " ++ pretty e)) []
      return (Just st)
    Just (StepOut whole red) -> do
      emit st "step" (pretty whole)
        [ "rule"   .= JStr (redRule red)
        , "note"   .= JStr (redNote red)
        , "before" .= JStr (pretty e)
        , "term"   .= JStr (pretty whole) ]
      return $ Just st { rsCurrent = Just whole }
runCommand st RunCmd = case rsCurrent st of
  Nothing -> do
    emit st "fail" (say st
      "当前没有进行中的归约，先用 :begin <表达式> 开始。"
      "No reduction in progress; start one with :begin <expr>.") []
    return (Just st)
  Just e -> do
    let res = evalTrace (rsLimit st) (rsStrategy st) e
        final = erFinal res
    emit st "result" (pretty final ++ valueHint (rsLang st) final)
      [ "steps"    .= JNum (erCount res)
      , "limitHit" .= JBool (erLimitHit res)
      , "term"     .= JStr (pretty final) ]
    return $ Just st { rsCurrent = Nothing }
runCommand st EndCmd = do
  emit st "info" (say st "已结束手动归约。" "Manual reduction ended.") []
  return $ Just st { rsCurrent = Nothing }
runCommand st (SetLang l) = do
  emit st "info" (tr l "语言已切换为中文。" "Language switched to English.") []
  return $ Just st { rsLang = l }
runCommand st Help = do
  if rsJson st
    then emit st "help" (helpMessage (rsLang st)) []
    else putStrLn (helpMessage (rsLang st))
  return (Just st)
runCommand _ Quit = return Nothing

strategyLabelEn :: Strategy -> String
strategyLabelEn Applicative = "applicative order (leftmost-innermost)"
strategyLabelEn Normal      = "normal order (leftmost-outermost)"
strategyLabelEn CallByName  = "call-by-name (weak)"
strategyLabelEn CallByValue = "call-by-value (weak)"

say :: ReplState -> String -> String -> String
say st zh en = renderMsg (rsLang st) (zh, en)

prettyScheme :: Lang -> Scheme -> String
prettyScheme lang (Forall vars t0) =
  let base = prettyTy (normalizeNames t0)
      poly = case lang of
        Zh   -> "（多态）"
        En   -> " (polymorphic)"
        Both -> "（多态） / (polymorphic)"
  in base ++ (if null vars then "" else poly)

-- ---------------------------------------------------------------------------
-- 帮助信息 Help Message
-- ---------------------------------------------------------------------------
helpMessage :: Lang -> String
helpMessage lang = unlines $ map (renderMsg lang) helpLines
  where
    helpLines =
      [ ( "λ 演算解释器 - Church 编码 / 归约轨迹 / 类型推断"
        , "λ Calculus interpreter - Church encodings / reduction traces / type inference" )
      , ("", "")
      , ("用法:", "Usage:")
      , ("  ./extension [选项] [文件]", "  ./extension [options] [file]")
      , ("", "")
      , ("选项:", "Options:")
      , ("  -h, --help       显示此帮助信息并退出", "  -h, --help       show this help and exit")
      , ("     --batch       批处理模式（从 stdin 逐行读取，供 Web 后端使用）"
        , "     --batch       batch mode (one command per stdin line, used by the web backend)")
      , ("     --json        以 JSON Lines 输出，便于程序消费"
        , "     --json        emit JSON Lines for programmatic use")
      , ("     --lang <值>   输出语言：zh / en / both（默认 both）"
        , "     --lang <v>    output language: zh / en / both (default both)")
      , ("", "")
      , ("参数:", "Arguments:")
      , ("  文件              启动时自动加载文件中的定义（每行格式: name = expr）"
        , "  file              load definitions on startup (one `name = expr` per line)")
      , ("", "")
      , ("REPL 内建命令:", "REPL commands:")
      ]
      ++ [ ( "  " ++ padRight 17 cmd ++ zh, "  " ++ padRight 17 cmd ++ en )
         | (cmd, (zh, en)) <- knownCommands ]
      ++
      [ ("", "")
      , ("表达式语法:", "Expression syntax:")
      , ("  - 变量: 字母或特定运算符开头，后可跟字母/数字/下划线/单引号/特定运算符 (+ - * / % ^ ? ! < > | & ~ # $)"
        , "  - variable: starts with a letter or allowed operator char, then letters/digits/_/'/operators")
      , ("  - 定义变量：name = expr", "  - definition: name = expr")
      , ("  - 抽象: λx.body 或 \\x.body，多个参数可写为 λx y.body"
        , "  - abstraction: λx.body or \\x.body; multiple params as λx y.body")
      , ("  - 应用: f a，左结合", "  - application: f a, left-associative")
      , ("  - 括号: (expr)", "  - grouping: (expr)")
      , ("  - 邱奇数: 直接输入数字 (0-9999) 自动转为 Church 编码"
        , "  - Church numerals: a literal number (0-9999) becomes its Church encoding")
      , ("", "")
      , ("预定义环境包含: TRUE, FALSE, NOT, AND, OR, IF, ZERO, ONE, TWO, THREE, SUCC, PLUS, MULT"
        , "Prelude: TRUE, FALSE, NOT, AND, OR, IF, ZERO, ONE, TWO, THREE, SUCC, PLUS, MULT")
      ]

-- ---------------------------------------------------------------------------
-- REPL
-- ---------------------------------------------------------------------------
handleLine :: ReplState -> String -> IO (Maybe ReplState)
handleLine st line =
  case parseCommand line of
    Left err -> do
      emit st "error"
        (renderMsg (rsLang st)
          ( "解析错误: 第 " ++ show (pePos err) ++ " 列 — " ++ fst (peMsg err)
          , "Parse error at column " ++ show (pePos err) ++ " -- " ++ snd (peMsg err) ))
        [ "pos" .= JNum (pePos err) ]
      return (Just st)
    Right cmd -> runCommand st cmd

replSettings :: ReplState -> Settings IO
replSettings st =
  setComplete (completeWord Nothing " \t" (completeFn st)) defaultSettings

completeFn :: ReplState -> String -> IO [Completion]
completeFn st left = return $ map simpleCompletion
  (filter (left `isPrefixOf`) candidates)
  where
    candidates = Map.keys (rsEnv st) ++ map fst knownCommands

repl :: ReplState -> InputT IO ()
repl st = do
  minput <- getInputLine "λ> "
  case minput of
    Nothing     -> return ()
    Just input  -> do
      me <- liftIO $ handleLine st input
      forM_ me repl

-- ---------------------------------------------------------------------------
-- 批处理模式 Batch Mode（供 Web 后端保持长会话）
-- ---------------------------------------------------------------------------
rsSentinel :: String
rsSentinel = [toEnum 0x1e]

batchLoop :: ReplState -> IO ()
batchLoop st = do
  atEnd <- hIsEOF stdin
  if atEnd
    then return ()
    else do
      line <- getLine
      mst <- handleLine st line
      hFlush stdout
      putStrLn rsSentinel
      hFlush stdout
      case mst of
        Nothing  -> return ()
        Just st' -> batchLoop st'

-- ---------------------------------------------------------------------------
-- 主程序 Main Program
-- ---------------------------------------------------------------------------
main :: IO ()
main = do
  args <- getArgs
  let json  = "--json"  `elem` args || "-j" `elem` args
      batch = "--batch" `elem` args
      lang  = maybe Both id (lookupFlag "--lang" args >>= parseLang)
      files = positional args
      lookupFlag flag xs = case dropWhile (/= flag) xs of
        (_:v:_) -> Just v
        _       -> Nothing
  if any (`elem` ["-h", "--help"]) args
    then putStrLn (helpMessage lang)
    else do
      term <- hIsTerminalDevice stdout
      when (batch || not term) $ do
        hSetEncoding stdin utf8
        hSetEncoding stdout utf8
        hSetEncoding stderr utf8
      when batch $ hSetBuffering stdout LineBuffering
      let st0 = ReplState initEnv initTypeEnv Applicative defaultLimit json lang Nothing
      st1 <- case files of
        (f:_) -> do
          res <- loadDefinitionsFromFile initEnv initTypeEnv f
          case res of
            Left err -> do
              putStrLn (renderMsg lang
                ("文件加载错误: " ++ err, "File load error: " ++ err))
              return st0
            Right out -> do
              unless (null (loOk out)) $
                putStrLn $ renderMsg lang
                  ( "成功加载 " ++ show (length (loOk out)) ++ " 个定义"
                  , "Loaded " ++ show (length (loOk out)) ++ " definitions" )
              forM_ (reverse (loFail out)) $ \(n, line) ->
                putStrLn $ renderMsg lang
                  ( "第 " ++ show n ++ " 行解析失败: " ++ shorten 60 line
                  , "Line " ++ show n ++ " failed to parse: " ++ shorten 60 line )
              return st0 { rsEnv = loEnv out, rsTypeEnv = loTypeEnv out }
        _ -> return st0
      if batch
        then batchLoop st1
        else runInputT (replSettings st1) (repl st1)
  where
    positional [] = []
    positional ("--lang":_:rest) = positional rest
    positional (a:rest)
      | "-" `isPrefixOf` a = positional rest
      | otherwise          = a : positional rest

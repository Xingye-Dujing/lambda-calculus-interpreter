{-# LANGUAGE ScopedTypeVariables #-}

-- ---------------------------------------------------------------------------
-- 最小 λ 演算解释器 / Minimal lambda calculus interpreter
-- 核心与 extension.hs 保持一致；不含定义与环境。
-- The core mirrors extension.hs; it has no definitions or environment.
-- ---------------------------------------------------------------------------

import qualified Data.Set as Set
import Control.Applicative ((<|>))
import Control.Monad (void, when, unless, forM_)
import Control.Monad.IO.Class (liftIO)
import Data.Char (isAlpha, isDigit, isSpace)
import Data.List (elemIndex, stripPrefix, isPrefixOf)
import System.Environment (getArgs)
import System.IO (hSetEncoding, utf8, hIsTerminalDevice, stdout, stdin, stderr)
import System.Console.Haskeline
import Text.ParserCombinators.ReadP

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
  deriving (Eq, Show)

freeVars :: Expr -> Set.Set String
freeVars (Var x)      = Set.singleton x
freeVars (Lam x body) = Set.delete x (freeVars body)
freeVars (App f a)    = freeVars f `Set.union` freeVars a

freshVar :: String -> Set.Set String -> String
freshVar base avoid
  | base `Set.notMember` avoid = base
  | otherwise                  = freshVar (base ++ "'") avoid

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
    fvV   = freeVars v
    y'    = freshVar y (freeVars body `Set.union` fvV)
    body' = subst y (Var y') body

-- ---------------------------------------------------------------------------
-- 求值策略 Evaluation strategies
-- ---------------------------------------------------------------------------
data Strategy = Applicative | Normal | CallByName | CallByValue
  deriving (Eq, Show)

strategyLabel :: Strategy -> String
strategyLabel Applicative = "应用序（最左最内） applicative (leftmost-innermost)"
strategyLabel Normal      = "正规序（最左最外） normal (leftmost-outermost)"
strategyLabel CallByName  = "按名调用 call-by-name"
strategyLabel CallByValue = "按值调用 call-by-value"

parseStrategy :: String -> Maybe Strategy
parseStrategy s = lookup (map lower s)
  [ ("applicative", Applicative), ("app", Applicative)
  , ("normal", Normal), ("no", Normal)
  , ("cbn", CallByName), ("byname", CallByName)
  , ("cbv", CallByValue), ("byvalue", CallByValue)
  ]
  where lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c

-- ---------------------------------------------------------------------------
-- 单步归约 One-step reduction
-- ---------------------------------------------------------------------------
data Reduction = Reduction { redNote :: String, redTerm :: Expr }
data StepOut   = StepOut { soWhole :: Expr, soRed :: Reduction }

betaStep :: String -> Expr -> Expr -> Reduction
betaStep x body arg =
  let after = subst x arg body
      note  = "β 归约 β-reduction: (λ" ++ x ++ ". …) " ++ shorten 42 (pretty arg)
  in Reduction note after

stepOnce :: Strategy -> Expr -> Maybe StepOut
stepOnce Applicative = go
  where
    go (Var _) = Nothing
    go (Lam x b) = do s <- go b; return s { soWhole = Lam x (soWhole s) }
    go (App f a) =
      case go f of
        Just s  -> Just s { soWhole = App (soWhole s) a }
        Nothing -> case go a of
          Just s  -> Just s { soWhole = App f (soWhole s) }
          Nothing -> case f of
            Lam x b -> let r = betaStep x b a in Just (StepOut (redTerm r) r)
            _       -> Nothing
stepOnce Normal = go
  where
    go (App (Lam x b) a) = let r = betaStep x b a in Just (StepOut (redTerm r) r)
    go (App f a) =
      case go f of
        Just s  -> Just s { soWhole = App (soWhole s) a }
        Nothing -> fmap (\s -> s { soWhole = App f (soWhole s) }) (go a)
    go (Lam x b) = do s <- go b; return s { soWhole = Lam x (soWhole s) }
    go _ = Nothing
stepOnce CallByName = go
  where
    go (App (Lam x b) a) = let r = betaStep x b a in Just (StepOut (redTerm r) r)
    go (App f a) =
      case go f of
        Just s  -> Just s { soWhole = App (soWhole s) a }
        Nothing -> fmap (\s -> s { soWhole = App f (soWhole s) }) (go a)
    go _ = Nothing
stepOnce CallByValue = go
  where
    go (App f a) =
      case f of
        Lam x b | isValue a -> let r = betaStep x b a in Just (StepOut (redTerm r) r)
        Lam _ _             -> fmap (\s -> s { soWhole = App f (soWhole s) }) (go a)
        _                   -> fmap (\s -> s { soWhole = App (soWhole s) a }) (go f)
    go _ = Nothing
    isValue (Lam _ _) = True
    isValue (Var _)   = True
    isValue _         = False

data TraceStep = TraceStep
  { tsIndex :: Int, tsAfter :: Expr, tsNote :: String }

data EvalResult = EvalResult
  { erFinal :: Expr, erSteps :: [TraceStep], erCount :: Int, erLimitHit :: Bool }

defaultLimit :: Int
defaultLimit = 10000

-- 求值循环：keepTrace 为 False 时不保留轨迹（省内存）。
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
                         then TraceStep n (soWhole s) (redNote red) : acc
                         else acc
            in loop (n + 1) (soWhole s) acc'
          Nothing -> EvalResult e (reverse acc) (n - 1) False

evalTrace :: Int -> Strategy -> Expr -> EvalResult
evalTrace = eval True

evalFinal :: Int -> Strategy -> Expr -> EvalResult
evalFinal = eval False

-- ---------------------------------------------------------------------------
-- 语义提示 Semantic hints
-- ---------------------------------------------------------------------------
isChurchNumeral :: Expr -> Maybe Integer
isChurchNumeral (Lam f (Lam x body)) = go 0 body
  where
    go n (Var x') | x' == x = Just n
    go n (App (Var f') rest) | f' == f = go (n + 1) rest
    go _ _ = Nothing
isChurchNumeral _ = Nothing

isChurchBoolean :: Expr -> Maybe Bool
isChurchBoolean (Lam t (Lam _ (Var t'))) | t == t' = Just True
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
pretty = go 0
  where
    go :: Int -> Expr -> String
    go _ (Var x) = x
    go p (Lam x b) = let s = "λ" ++ x ++ " → " ++ go 0 b
                     in if p > 0 then "(" ++ s ++ ")" else s
    go p (App f a) = let s = go 1 f ++ " " ++ go 2 a
                     in if p > 1 then "(" ++ s ++ ")" else s

shorten :: Int -> String -> String
shorten n s
  | length s <= n = s
  | otherwise     = take (max 0 (n - 1)) s ++ "…"

treeLines :: Expr -> [String]
treeLines (Var x)   = ["• " ++ x]
treeLines (Lam x b) = ("λ " ++ x) : fork "└ " "  " (treeLines b)
treeLines (App f a) = "App" : fork "├ " "│ " (treeLines f) ++ fork "└ " "  " (treeLines a)

fork :: String -> String -> [String] -> [String]
fork _ _ []            = []
fork first rest (l:ls) = (first ++ l) : map (rest ++) ls

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

ident :: ReadP String
ident = do
  c <- satisfy isAlpha
  cs <- munch (\ch -> isAlpha ch || isDigit ch || ch == '\'')
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
parseAtom = parseVar <++ parseParens

parseVar :: ReadP Expr
parseVar = Var <$> ident

parseParens :: ReadP Expr
parseParens = between (char '(') (char ')') $ spaces *> parseExpr <* spaces

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
  | isLambdaStart && not ('.' `elem` s) =
      (pos, ("Lambda 表达式缺少 '.' 分隔符（形如 λx. body）"
            , "Lambda abstraction is missing '.', e.g. λx. body"))
  | null rest =
      (pos, ("语法错误，请检查表达式结构", "Syntax error, please check the expression"))
  | otherwise =
      (pos, ("无法继续解析：" ++ shorten 18 rest, "Cannot parse at: " ++ shorten 18 rest))
  where
    isLambdaStart = case dropWhile isSpace s of
      ('λ':_)  -> True
      ('\\':_) -> True
      _        -> False

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
trim :: String -> String
trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse

data Command
  = Eval Expr
  | Trace Expr
  | Ast Expr
  | DbView Expr
  | SetStrategy Strategy
  | SetSteps Int
  | SetLang Lang
  | Help
  | Quit

knownCommands :: [String]
knownCommands =
  [ ":help", ":trace", ":ast", ":db", ":strategy", ":steps", ":lang", ":q" ]

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
  | Just rest <- stripPrefix ":trace " s = Trace <$> parseExpr' rest
  | Just rest <- stripPrefix ":ast " s = Ast <$> parseExpr' rest
  | Just rest <- stripPrefix ":db " s = DbView <$> parseExpr' rest
  | Just _ <- stripPrefix ":" s = Left (ParseError 1
      ( "未知命令 " ++ takeWhile (not . isSpace) s ++ "，输入 :help 查看全部命令"
      , "Unknown command " ++ takeWhile (not . isSpace) s ++ "; type :help for the full list" ))
  | otherwise = Eval <$> runParserFull parseExpr s
  where
    s = trim raw
    parseExpr' src = case runParserFull parseExpr (trim src) of
      Left e  -> Left e { pePos = pePos e + (length s - length (trim src)) }
      Right x -> Right x

-- ---------------------------------------------------------------------------
-- 状态 State
-- ---------------------------------------------------------------------------
data ReplState = ReplState
  { rsStrategy :: Strategy
  , rsLimit    :: Int
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

runCommand :: ReplState -> Command -> IO (Maybe ReplState)
runCommand st (Eval expr) = do
  let res   = evalFinal (rsLimit st) (rsStrategy st) expr
      final = erFinal res
      steps = erCount res
      stepTxt = if steps > 0 then "  (" ++ show steps ++ " 步 steps)" else ""
  if erLimitHit res
    then emit "warn" (pretty final ++ stepTxt ++ say st
           (" —— 已达到 " ++ show (rsLimit st) ++ " 步上限，归约未完成")
           (" -- step limit " ++ show (rsLimit st) ++ " reached, reduction incomplete"))
    else emit "result" (pretty final ++ stepTxt ++ valueHint final)
  return (Just st)
runCommand st (Trace expr) = do
  let res = evalTrace (rsLimit st) (rsStrategy st) expr
  putStrLn $ say st
    ("归约轨迹（" ++ strategyLabel (rsStrategy st) ++ "，共 " ++ show (erCount res) ++ " 步）")
    ("Reduction trace (" ++ strategyLabel (rsStrategy st) ++ ", " ++ show (erCount res) ++ " steps)")
  putStrLn $ "  0. " ++ pretty expr
  forM_ (erSteps res) $ \s -> do
    putStrLn $ "  " ++ show (tsIndex s) ++ ". " ++ tsNote s
    putStrLn $ "       " ++ pretty (tsAfter s)
  when (erLimitHit res) $ putStrLn (say st
    "  ⚠ 已达到步数上限，归约未完成" "  ⚠ Step limit reached, reduction incomplete")
  return (Just st)
runCommand st (Ast expr) = putStrLn (unlines (treeLines expr)) >> return (Just st)
runCommand st (DbView expr) = putStrLn (deBruijnView expr) >> return (Just st)
runCommand st (SetStrategy s) = do
  emit "info" (say st
    ("求值策略：" ++ strategyLabel s)
    ("Strategy: " ++ strategyLabel s))
  return (Just st { rsStrategy = s })
runCommand st (SetSteps n) = do
  emit "info" (say st ("归约步数上限：" ++ show n) ("Reduction step limit: " ++ show n))
  return (Just st { rsLimit = n })
runCommand st (SetLang l) = do
  emit "info" (tr l "语言已切换为中文。" "Language switched to English.")
  return (Just st { rsLang = l })
runCommand st Help = putStrLn (helpMessage (rsLang st)) >> return (Just st)
runCommand _ Quit = return Nothing

helpMessage :: Lang -> String
helpMessage lang = unlines $ map (renderMsg lang)
  [ ("λ 演算解释器（最小版）", "λ Calculus interpreter (minimal)")
  , ("", "")
  , ("用法: ./main [--lang zh|en|both]", "Usage: ./main [--lang zh|en|both]")
  , ("", "")
  , ("命令:", "Commands:")
  , ("  :trace <表达式>  显示完整归约轨迹", "  :trace <expr>    show the full reduction trace")
  , ("  :ast <表达式>    显示语法树", "  :ast <expr>      show the syntax tree")
  , ("  :db <表达式>     de Bruijn 索引视图", "  :db <expr>       de Bruijn index view")
  , ("  :strategy <名称> 切换求值策略", "  :strategy <name> switch evaluation strategy")
  , ("  :steps <n>       设置归约步数上限", "  :steps <n>       set the reduction step limit")
  , ("  :lang <值>       切换语言 zh/en/both", "  :lang <v>        switch language zh/en/both")
  , ("  :help            显示本帮助", "  :help            show this help")
  , ("  :q               退出", "  :q               quit")
  , ("", "")
  , ("抽象: λx.body 或 \\x.body；应用: f a（左结合）；括号: (expr)",
     "Abstraction: λx.body or \\x.body; application: f a (left-assoc); grouping: (expr)")
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

replSettings :: ReplState -> Settings IO
replSettings st = setComplete (completeWord Nothing " \t" (completeFn st)) defaultSettings

completeFn :: ReplState -> String -> IO [Completion]
completeFn _ left = return $ map simpleCompletion (filter (left `isPrefixOf`) knownCommands)

repl :: ReplState -> InputT IO ()
repl st = do
  minput <- getInputLine "λ> "
  case minput of
    Nothing    -> return ()
    Just input -> do
      me <- liftIO $ handleLine st input
      forM_ me repl

main :: IO ()
main = do
  args <- getArgs
  let lang = maybe Both id (lookupFlag "--lang" args >>= parseLang)
      lookupFlag flag xs = case dropWhile (/= flag) xs of
        (_:v:_) -> Just v
        _       -> Nothing
      st0 = ReplState Applicative defaultLimit lang
  if any (`elem` ["-h", "--help"]) args
    then putStrLn (helpMessage lang)
    else do
      -- 管道 / 重定向时统一用 UTF-8，避免 Windows 代码页问题。
      -- Use UTF-8 when piped or redirected, avoiding Windows code-page issues.
      term <- hIsTerminalDevice stdout
      unless term $ do
        hSetEncoding stdin utf8
        hSetEncoding stdout utf8
        hSetEncoding stderr utf8
      runInputT (replSettings st0) (repl st0)

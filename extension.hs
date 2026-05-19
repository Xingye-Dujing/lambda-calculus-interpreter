{-# LANGUAGE OverloadedStrings #-}

import qualified Data.Set as Set
import qualified Data.Map as Map
import Control.Applicative ((<|>))
import Control.Exception (catch, SomeException)
import Control.Monad (void, when, unless, forM_, foldM, guard)
import Control.Monad.IO.Class (liftIO)
import Data.Bifunctor (second)
import Data.Char (isAlpha, isDigit, isSpace)
import Data.List (isPrefixOf)
import System.Environment (getArgs)
import System.Console.Haskeline
import Text.ParserCombinators.ReadP

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
-- 完全 β-正规形（应用序）Full Beta-Normal Form (Applicative Order)
-- ---------------------------------------------------------------------------
nf :: Expr -> Expr
nf (Var x)       = Var x
nf (Lam x body)  = Lam x (nf body)
nf (App f a)     = case nf f of
  Lam x body -> nf (subst x (nf a) body)
  f'         -> App f' (nf a)

-- ---------------------------------------------------------------------------
-- 宏展开（带绑定集，避免捕获）Macro Expansion (with Binding Set, Capture-Avoiding)
-- ---------------------------------------------------------------------------
expand :: Env -> Set.Set String -> Expr -> Expr
expand env bound (Var x)
  | x `Set.member` bound = Var x
  | Just e <- Map.lookup x env = expand env bound e
  | otherwise = Var x
expand env bound (Lam x body) = Lam x (expand env (Set.insert x bound) body)
expand env bound (App f a)    = App (expand env bound f) (expand env bound a)

expandTop :: Env -> Expr -> Expr
expandTop env = expand env Set.empty

-- ---------------------------------------------------------------------------
-- 邱奇数/邱奇布尔值检测 Church Numeral / Church Boolean Detection
-- ---------------------------------------------------------------------------
isChurchNumeral :: Expr -> Maybe Integer
isChurchNumeral (Lam f (Lam x body)) = go 0 body
  where
    go n (Var x')   | x' == x = Just n
    go n (App (Var f') rest) | f' == f = go (n+1) rest
    go _ _ = Nothing
isChurchNumeral _ = Nothing

isChurchBoolean :: Expr -> Maybe Bool
isChurchBoolean (Lam t (Lam f (Var t'))) | t == t' = Just True
isChurchBoolean (Lam t (Lam f (Var f'))) | f == f' = Just False
isChurchBoolean _ = Nothing

valueHint :: Expr -> String
valueHint e = case (isChurchNumeral e, isChurchBoolean e) of
  (Just 0, Just False) -> "  (Church numeral 0 / Church boolean False)"
  (Just n, _)          -> "  (Church numeral " ++ show n ++ ")"
  (_, Just True)       -> "  (Church boolean True)"
  (_, Just False)      -> "  (Church boolean False)"
  _                    -> ""

-- ---------------------------------------------------------------------------
-- 美观打印 Pretty Printing
-- ---------------------------------------------------------------------------
pretty :: Expr -> String
pretty = go 0
  where
    go _ (Var x) = x
    go p (Lam x body) = let s = "λ" ++ x ++ " → " ++ go 0 body in if p > 0 then "(" ++ s ++ ")" else s
    go p (App f a) = let s = go 1 f ++ " " ++ go 2 a in if p > 1 then "(" ++ s ++ ")" else s

-- ---------------------------------------------------------------------------
-- 解析器 Parser
-- ---------------------------------------------------------------------------
spaces :: ReadP ()
spaces = void $ many $ satisfy isSpace

isOperatorChar :: Char -> Bool
isOperatorChar ch = ch `elem` ("+*-/%^?!<>|&~#$" :: String)

ident :: ReadP String
ident = do
  c <- satisfy (\ch -> isAlpha ch || isOperatorChar ch)
  cs <- munch (\ch -> isAlpha ch || isDigit ch || ch `elem` ("_'" :: String) || isOperatorChar ch)
  return (c:cs)

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
parseNum = churchNumeral . read <$> many1 (satisfy isDigit)

churchNumeral :: Integer -> Expr
churchNumeral 0 = Lam "f" (Lam "x" (Var "x"))
churchNumeral n = Lam "f" (Lam "x" $ go n)
  where go 1 = App (Var "f") (Var "x")
        go k = App (Var "f") (go (k-1))

parseVar :: ReadP Expr
parseVar = Var <$> ident

parseParens :: ReadP Expr
parseParens = between (char '(') (char ')') $ spaces *> parseExpr <* spaces

runParser :: ReadP a -> String -> Maybe a
runParser p s = case readP_to_S (p <* eof) s of
  [(x, "")] -> Just x
  _         -> Nothing

-- ---------------------------------------------------------------------------
-- 错误信息辅助 Error Message Helper
-- ---------------------------------------------------------------------------
parseErrorMsg :: String -> String
parseErrorMsg input
  | null input || all isSpace input = if null input then "空输入" else "仅包含空白字符"
  | otherwise = case break (=='.') trimmed of
      (_, "") | isLamStart -> "Lambda 表达式缺少 '.' 分隔符"
      _ | isLamStart -> "Lambda 抽象语法错误，请检查变量名或括号"
      _ -> case compare openParens closeParens of
        GT -> "括号不匹配：缺少 " ++ show (openParens - closeParens) ++ " 个右括号 ')'"
        LT -> "括号不匹配：缺少 " ++ show (closeParens - openParens) ++ " 个左括号 '('"
        EQ -> if not (all isLegalInExpr trimmed)
              then let illegal = head $ filter (not . isLegalInExpr) trimmed
                   in "非法字符 '" ++ [illegal] ++ "'，只允许 λ \\ → . 字母 数字 ' 和括号"
              else "语法错误，请检查表达式结构"
  where
    trimmed = dropWhile isSpace input
    openParens  = length $ filter (=='(') trimmed
    closeParens = length $ filter (==')') trimmed
    isLamStart = "λ" `isPrefixOf` trimmed || "\\" `isPrefixOf` trimmed
    isLegalInExpr c = isAlpha c || isDigit c || c `elem` ("λ\\ ().=" :: String)

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

-- ---------------------------------------------------------------------------
-- 命令处理 Command Handling
-- ---------------------------------------------------------------------------
data Command = Eval Expr | Define String Expr | LoadFile FilePath | ShowEnv | Quit

trim :: String -> String
trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse

isValidVarName :: String -> Bool
isValidVarName [] = False
isValidVarName (c:cs) = isValidFirst c && all isValidRest cs
  where
    isValidFirst ch = isAlpha ch || isOperatorChar ch
    isValidRest  ch = isAlpha ch || isDigit ch || ch `elem` ("_'" :: String) || isOperatorChar ch

parseAssignment :: String -> Maybe (String, Expr)
parseAssignment str = do
  let (beforeEq, afterEq) = break (=='=') str
  var <- guard (isValidVarName (trim beforeEq)) >> Just (trim beforeEq)
  expr <- runParser parseExpr (trim $ drop 1 afterEq)
  return (var, expr)

parseCommand :: Env -> String -> Maybe Command
parseCommand _ s
  | ":load " `isPrefixOf` s = Just $ LoadFile (trim $ drop 6 s)
  | ":let "  `isPrefixOf` s = uncurry Define <$> parseAssignment (drop 5 s)
  | ":env" == s = Just ShowEnv
  | ":q"   == s = Just Quit
  | otherwise   = case parseAssignment s of
      Just (var, expr) -> Just $ Define var expr
      Nothing          -> Eval <$> runParser parseExpr s

-- ---------------------------------------------------------------------------
-- 表格打印 Print Table
-- ---------------------------------------------------------------------------
padRight :: Int -> String -> String
padRight n s = s ++ replicate (n - length s) ' '

printTable :: [(String, String)] -> IO ()
printTable rows = unless (null rows) $ do
  let col1Len = maximum $ length ("Var Name" :: String) : map (length . fst) rows
      col2Len = maximum $ length ("Value" :: String)    : map (length . snd) rows
      mkBorder c1 c2 c3 = c1 : replicate (col1Len + 2) '─' ++ [c2] ++ replicate (col2Len + 2) '─' ++ [c3]
      top     = mkBorder '┌' '┬' '┐'
      mid     = mkBorder '├' '┼' '┤'
      bottom  = mkBorder '└' '┴' '┘'
      formatRow (a,b) = "│ " ++ padRight col1Len a ++ " │ " ++ padRight col2Len b ++ " │"
  putStrLn top
  putStrLn $ formatRow ("Var Name", "Value")
  putStrLn mid
  mapM_ (putStrLn . formatRow) rows
  putStrLn bottom

printDefinitions :: [(String, Expr)] -> IO ()
printDefinitions = printTable . map (second pretty)

-- ---------------------------------------------------------------------------
-- 环境打印 Print Environment
-- ---------------------------------------------------------------------------
showEnvPretty :: Env -> IO ()
showEnvPretty env
  | Map.null env = putStrLn "当前环境为空。"
  | otherwise    = printDefinitions $ Map.toList env

-- ---------------------------------------------------------------------------
-- 文件加载错误处理 File Loading Error Handling
-- ---------------------------------------------------------------------------
readFileSafe :: FilePath -> IO (Either String String)
readFileSafe path = catch (Right <$> readFile path) (\(e :: SomeException) -> return $ Left $ show e)

printLoadErrors :: [(Int, String)] -> IO ()
printLoadErrors [] = return ()
printLoadErrors failures = do
  putStrLn $ "\n！！！以下 " ++ show (length failures) ++ " 行解析失败（已忽略）："
  forM_ failures $ \(n, line) ->
    putStrLn $ "  第 " ++ show n ++ " 行: " ++ take 60 line ++ if length line > 60 then "..." else ""
  putStrLn ""

-- ---------------------------------------------------------------------------
-- 从文件加载定义 Load Definitions from File
-- ---------------------------------------------------------------------------
loadDefinitionsFromFile :: Env -> FilePath -> IO (Maybe Env)
loadDefinitionsFromFile env path = do
  contentOrErr <- readFileSafe path
  case contentOrErr of
    Left err -> putStrLn ("文件加载错误: " ++ err) >> return (Just env)
    Right content -> do
      let numberedLines = zip [1..] $ filter (not . null) $ lines content
      let (newEnv, successes, failures) = foldl processLine (env, [], []) numberedLines
      unless (null successes) $ do
        putStrLn $ "\n成功加载 " ++ show (length successes) ++ " 个定义："
        printDefinitions successes
      printLoadErrors failures
      return (Just newEnv)
  where
    processLine (accEnv, ok, err) (n, line) =
      case parseCommand accEnv line of
        Just (Define var expr) ->
          let expr' = expandTop accEnv expr
              newEnv = Map.insert var expr' accEnv
          in (newEnv, (var, expr') : ok, err)
        _ -> (accEnv, ok, (n, line) : err)

-- ---------------------------------------------------------------------------
-- 命令执行 Command Execution
-- ---------------------------------------------------------------------------
runCommand :: Env -> Command -> IO (Maybe Env)
runCommand env (Eval expr) = do
  let result = nf $ expandTop env expr
  putStrLn $ "⇒ " ++ pretty result ++ valueHint result
  return $ Just env

runCommand env (Define var expr) = do
  let expr' = expandTop env expr
  putStrLn $ "defined " ++ var ++ " = " ++ pretty expr'
  return $ Just $ Map.insert var expr' env

runCommand env (LoadFile path) = loadDefinitionsFromFile env path

runCommand env ShowEnv = showEnvPretty env >> return (Just env)

runCommand _ Quit = return Nothing

-- ---------------------------------------------------------------------------
-- 帮助信息 Help Message
-- ---------------------------------------------------------------------------
helpMessage :: String
helpMessage = unlines
  [ "λ 演算解释器 - Church 编码支持"
  , ""
  , "用法:"
  , "  ./extension [选项] [文件]"
  , ""
  , "选项:"
  , "  -h, --help       显示此帮助信息并退出"
  , ""
  , "参数:"
  , "  文件              启动时自动加载文件中的定义（每行格式: name = expr）"
  , ""
  , "REPL 内建命令:"
  , "  :load <文件>     加载定义文件"
  , "  :let name = expr 定义变量"
  , "  :env             显示当前环境中的所有定义"
  , "  :q               退出解释器"
  , ""
  , "表达式语法:"
  , "  - 变量: 字母或特定运算符开头，后可跟字母/数字/下划线/单引号/特定运算符 (+ - * / % ^ ? ! < > | & ~ # $)"
  , "  - 定义变量：name = expr"
  , "  - 抽象: λx.body 或 \\x.body，多个参数可写为 λx y.body"
  , "  - 应用: f a，左结合"
  , "  - 括号: (expr)"
  , "  - 邱奇数: 直接输入数字 (0,1,2,...,9) 自动转为 Church 编码"
  , ""
  , "预定义环境包含: TRUE, FALSE, NOT, AND, OR, IF, ZERO, ONE, TWO, THREE, SUCC, PLUS, MULT"
  ]

-- ---------------------------------------------------------------------------
-- REPL
-- ---------------------------------------------------------------------------
repl :: Env -> InputT IO ()
repl env = do
  minput <- getInputLine "λ> "
  case minput of
    Nothing       -> return ()
    Just ":q"     -> return ()
    Just input    -> do
      case parseCommand env input of
        Just cmd -> do
          me <- liftIO $ runCommand env cmd
          forM_ me repl
        Nothing -> do
          let errMsg = if '=' `elem` input && not (":let" `isPrefixOf` input)
                       then "赋值失败，请使用格式: name(字母或运算符开头，可含字母/数字/下划线/单引号/运算符) = expr"
                       else parseErrorMsg input
          outputStrLn $ "解析错误: " ++ errMsg
          repl env

-- ---------------------------------------------------------------------------
-- 主程序 Main Program
-- ---------------------------------------------------------------------------
main :: IO ()
main = do
  args <- getArgs
  if any (`elem` ["-h", "--help"]) args
    then putStrLn helpMessage
    else do
      startEnv <- case args of
        [file] -> do
          envMaybe <- loadDefinitionsFromFile initEnv file
          return $ fromMaybe initEnv envMaybe
        _ -> return initEnv
      runInputT defaultSettings $ repl startEnv
  where
    fromMaybe dflt Nothing  = dflt
    fromMaybe _   (Just x)  = x
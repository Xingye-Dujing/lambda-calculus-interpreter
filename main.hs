{-# LANGUAGE OverloadedStrings #-}   -- 仅为更好的字符串字面量，不影响核心逻辑

import qualified Data.Set as Set
import Data.Char (isAlpha, isSpace)
import Control.Applicative ((<|>))
import Control.Monad (void, when)
import Control.Monad.IO.Class (liftIO)
import Text.ParserCombinators.ReadP
import System.Console.Haskeline

-- 表达式定义 ----------------------------------------------------------------
data Expr = Var String | Lam String Expr | App Expr Expr
  deriving (Eq, Show)

-- 自由变量 ------------------------------------------------------------------
freeVars :: Expr -> Set.Set String
freeVars (Var x)   = Set.singleton x
freeVars (Lam x b) = Set.delete x (freeVars b)
freeVars (App f a) = freeVars f `Set.union` freeVars a

-- 生成新变量（避免捕获）-----------------------------------------------------
freshVar :: String -> Set.Set String -> String
freshVar base avoid
  | base `Set.notMember` avoid = base
  | otherwise                  = freshVar (base ++ "'") avoid

-- 无捕获替换 ----------------------------------------------------------------
subst :: String -> Expr -> Expr -> Expr
subst x v (Var y)
  | x == y    = v
  | otherwise = Var y
subst x v (App f a) = App (subst x v f) (subst x v a)
subst x v (Lam y body)
  | x == y    = Lam y body
  | y `Set.notMember` fvV = Lam y (subst x v body)
  | otherwise = Lam y' (subst x v body')
  where
    fvV     = freeVars v
    y'      = freshVar y (freeVars body `Set.union` fvV)
    body'   = subst y (Var y') body

-- 完全 β-正规形（应用序）---------------------------------------------------
nf :: Expr -> Expr
nf (Var x)   = Var x
nf (Lam x b) = Lam x (nf b)
nf (App f a) =
  let f' = nf f
      a' = nf a
  in case f' of
       Lam x b -> nf (subst x a' b)
       _       -> App f' a'

-- 美化打印（带括号优先级）---------------------------------------------------
pretty :: Expr -> String
pretty = go 0
  where
    go _ (Var x) = x
    go p (Lam x b) =
      let s = "λ" ++ x ++ " → " ++ go 0 b
      in if p > 0 then "(" ++ s ++ ")" else s
    go p (App f a) =
      let s = go 1 f ++ " " ++ go 2 a
      in if p > 1 then "(" ++ s ++ ")" else s

-- 解析器 --------------------------------------------------------------------
spaces :: ReadP ()
spaces = void $ many (satisfy isSpace)

ident :: ReadP String
ident = (:) <$> satisfy isAlpha <*> munch (\c -> isAlpha c || c == '\'')

betweenP :: ReadP a -> ReadP b -> ReadP c -> ReadP c
betweenP open close p = open *> p <* close

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
parseParens = betweenP (char '(') (char ')') (spaces *> parseExpr <* spaces)

runParser :: String -> Maybe Expr
runParser = fmap fst . listToMaybe . readP_to_S (parseExpr <* eof)
  where
    listToMaybe []    = Nothing
    listToMaybe (x:_) = Just x

-- 错误处理 ------------------------------------------------------------------
parseErrorMsg :: String -> String
parseErrorMsg input
  | null input || all isSpace input = if null input then "空输入" else "仅包含空白字符"
  | otherwise = "语法错误，请检查表达式"

-- REPL 命令处理 -------------------------------------------------------------
data Command = Eval Expr | Quit

parseCommand :: String -> Maybe Command
parseCommand ":q" = Just Quit
parseCommand s    = Eval <$> runParser s

runCommand :: Command -> IO Bool   -- 返回 True 继续, False 退出
runCommand Quit = return False
runCommand (Eval e) = do
  let result = nf e
  putStrLn $ "⇒ " ++ pretty result
  return True

-- REPL 主循环 ---------------------------------------------------------------
repl :: IO ()
repl = runInputT defaultSettings loop
  where
    loop :: InputT IO ()
    loop = do
      minput <- getInputLine "λ> "
      case minput of
        Nothing -> return ()
        Just input -> do
          case parseCommand input of
            Nothing -> outputStrLn $ "解析错误: " ++ parseErrorMsg input
            Just cmd -> do
              cont <- liftIO $ runCommand cmd
              when cont loop

-- 主程序 --------------------------------------------------------------------
main :: IO ()
main = repl
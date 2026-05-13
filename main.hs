import qualified Data.Set as Set -- qualified 必须有，否则会与 Prelude 有命名冲突
import Data.Char (isAlpha, isSpace)
import Control.Applicative ((<|>))
import Control.Monad (void)
import Text.ParserCombinators.ReadP
import System.Console.Haskeline

data Expr
  = Var String
  | Lam String Expr
  | App Expr Expr
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
  | y `Set.notMember` freeVarsV = Lam y (subst x v body)
  | otherwise =
      let y' = freshVar y (freeVars body `Set.union` freeVarsV)
          body' = subst y (Var y') body
      in Lam y' (subst x v body')
  where
    freeVarsV = freeVars v

-- 完全 β-正规形求值
nf :: Expr -> Expr
nf (Var x) = Var x
nf (Lam x body) = Lam x (nf body)
nf (App f a) =
  let f' = nf f
      a' = nf a
  in case f' of
       Lam x body -> nf (subst x a' body)
       _          -> App f' a'

spaces :: ReadP ()
spaces = void (many (satisfy isSpace))

ident :: ReadP String
ident = do
  c  <- satisfy isAlpha
  cs <- munch (\ch -> isAlpha ch || ch == '\'')
  return (c:cs)

parseExpr :: ReadP Expr
parseExpr = do
  spaces
  parseLam <++ parseApp

parseLam :: ReadP Expr
parseLam = do
  void (char '\\' <|> char 'λ')
  params <- many1 (do { x <- ident; spaces; return x })
  void (char '.')
  spaces
  body <- parseExpr
  return (foldr Lam body params)

parseApp :: ReadP Expr
parseApp = do
  first <- parseAtom
  rest <- many (spaces >> parseAtom)
  return (foldl App first rest)

parseAtom :: ReadP Expr
parseAtom = parseVar <++ parseParens

parseVar :: ReadP Expr
parseVar = Var <$> ident

parseParens :: ReadP Expr
parseParens = do
  void (char '(')
  e <- parseExpr
  spaces
  void (char ')')
  return e

runParser :: String -> Maybe Expr
runParser s = case readP_to_S (parseExpr <* eof) s of
  [(e, "")] -> Just e
  _         -> Nothing

prettyPrint :: Expr -> String
prettyPrint (Var x)      = x
prettyPrint (Lam x body) = "\\" ++ x ++ " -> " ++ prettyPrint body
prettyPrint (App e1 e2)  = "(" ++ prettyPrint e1 ++ " " ++ prettyPrint e2 ++ ")"

repl :: IO ()
repl = runInputT defaultSettings loop
  where
    loop :: InputT IO ()
    loop = do
      minput <- getInputLine "λ> "
      case minput of
        Nothing    -> return ()
        Just ":q"  -> return ()
        Just input -> do
          case runParser input of
            Nothing -> outputStrLn "解析错误"
            Just e  -> do
              let result = nf e
              outputStrLn ("⇒ " ++ prettyPrint result)
          loop

main :: IO ()
main = repl
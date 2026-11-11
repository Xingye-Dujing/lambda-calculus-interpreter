{-# LANGUAGE ScopedTypeVariables #-}
{-# LANGUAGE RecordWildCards #-}
{-# LANGUAGE LambdaCase #-}
{-# LANGUAGE BangPatterns #-}

import qualified Data.Map.Strict as Map
import qualified Data.IntMap.Strict as IM
import qualified Data.Set as Set
import Control.Applicative ((<|>))
import Control.Exception (catch, evaluate, mask_, throwIO, SomeException, AsyncException(..))
import Control.Monad (void, when, unless, forM_, forM, guard, foldM)
import Control.Monad.IO.Class (liftIO)
import Data.Char (isAlpha, isDigit, isSpace, ord, toLower)
import Data.List (elemIndex, find, stripPrefix, isPrefixOf, isInfixOf, intercalate, foldl', sort)
import Data.Maybe (fromMaybe)
import Numeric (showHex, showFFloat)
import System.Directory (getHomeDirectory)
import System.Environment (getArgs, lookupEnv)
import System.Exit (exitFailure, exitSuccess)
import System.IO
import System.Info (os)
import System.Process (callProcess)
import System.Timeout (timeout)
import GHC.Clock (getMonotonicTimeNSec)
import System.Console.Haskeline
import Text.ParserCombinators.ReadP

versionString :: String
versionString = "lambda-calculus-interpreter 2.2.1"

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

langId :: Lang -> String
langId Zh = "zh"
langId En = "en"
langId Both = "both"

-- ---------------------------------------------------------------------------
-- 表达式定义 Expression Definitions
-- ---------------------------------------------------------------------------
data Expr = Var String | Lam String Expr | App Expr Expr
  deriving (Eq, Ord, Show)

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
-- 参数的自由的变量只算一次，向下贯穿整次替换；同时把“是否发生过
-- α-重命名”作为返回值带出来，这样 β 步不需要再单独扫一遍项来判定规则
-- 返回 Nothing 表示该子树不含 x，调用方直接复用原树（共享而非复制）
-- Free variables of the argument are computed once and threaded through the
-- whole substitution; the same pass reports whether any α-renaming was needed,
-- so a β step no longer scans the term twice. Nothing means the subtree does
-- not contain x, so the caller reuses it instead of copying.
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
-- α 等价 Alpha Equivalence
-- ---------------------------------------------------------------------------
-- 不构造 de Bruijn 中间树，直接在两个绑定环境上同步下降：融合掉
-- toDB 的两棵树分配，等价判断变成一次结构比较
-- No intermediate de Bruijn tree: both binding environments are walked in
-- lockstep, so α-equivalence fuses the old toDB allocation away.
alphaEq :: Expr -> Expr -> Bool
alphaEq = go [] []
  where
    go env1 env2 (Var x) (Var y) =
      case (elemIndex x env1, elemIndex y env2) of
        (Nothing, Nothing) -> x == y
        (Just i, Just j)   -> i == j
        _                  -> False
    go env1 env2 (Lam x b1) (Lam y b2) = go (x : env1) (y : env2) b1 b2
    go env1 env2 (App f1 a1) (App f2 a2) =
      go env1 env2 f1 f2 && go env1 env2 a1 a2
    go _ _ _ _ = False

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
-- 每一步都返回“整个项”的新形态，方便前端做前后对比
-- Each step rewrites the whole term, so the frontend can diff before/after.
-- ---------------------------------------------------------------------------
data Reduction = Reduction
  { redRule :: String   -- β / β+α
  , redNote :: String   -- 人类可读说明 / human-readable note
  , redTerm :: Expr     -- 归约后的项 / resulting term
  }

data StepOut = StepOut { soWhole :: Expr, soRed :: Reduction }

-- 替换时是否需要先 α-重命名（与 substRename 的分支条件保持一致）
-- Whether substitution must rename a binder first (mirrors substRename).
alphaNeeded :: String -> Expr -> Expr -> Bool
alphaNeeded x body arg = go body
  where
    fvA = freeVars arg
    go (Lam y b)
      | y == x = False
      | y `Set.member` fvA && x `Set.member` freeVars b = True
      | otherwise = go b
    go (App f a) = go f || go a
    go _         = False

betaStep :: String -> Expr -> Expr -> Reduction
betaStep x body arg =
  let (after, renamed) = substRename x arg (freeVars arg) body
      rule   = if renamed then "β+α" else "β"
      note   = "β 归约 β-reduction: (λ" ++ x ++ ". …) " ++ shorten 42 (pretty arg)
               ++ (if renamed then "  （先 α-重命名 α-rename 避免变量捕获 capture）" else "")
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
-- η 归约与组合式单步 / eta reduction and the combined step
-- ---------------------------------------------------------------------------
-- η：λx. f x → f，前提是 x 不在 f 中自由出现
-- eta: λx. f x -> f when x is not free in f.
etaRoot :: Expr -> Maybe Reduction
etaRoot (Lam x (App f (Var y)))
  | x == y && x `Set.notMember` freeVars f =
      Just (Reduction "η"
        ("η 归约 η-reduction: λ" ++ x ++ ". … " ++ x ++ " → …") f)
etaRoot _ = Nothing

etaStep :: Strategy -> Expr -> Maybe StepOut
etaStep strat = go
  where
    Order{..} = orderOf strat
    -- 与 stepOnce 一致地遵守弱策略规则，避免 η 越过策略边界
    -- Honour the same weak-strategy rules as stepOnce, so eta does not
    -- silently reduce past the strategy boundary.
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

-- 先做 β，没有 β 再考虑 η / try beta first, then eta
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
  , erCycle    :: Bool
  }

defaultLimit :: Int
defaultLimit = 10000

-- 有界循环检测：只记住前若干步里的小项，避免为发散项白跑满步数
-- Bounded cycle detection: remember small whole terms for the first steps only,
-- so a divergent term is reported instead of silently burning the step budget.
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
                         then TraceStep n e e' (redRule red) (redNote red) : acc
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

-- 归约到弱首正规形 / reduce only to weak head normal form
evalWHNF :: Bool -> Int -> Strategy -> Expr -> EvalResult
evalWHNF eta limit strat = evalUntil eta True limit strat isWHNF

-- ---------------------------------------------------------------------------
-- 共享正规化（NBE 快速模式）/ Shared normalization (NBE fast mode)
-- ---------------------------------------------------------------------------
-- 小步引擎每一步都要重建整项；Church 算术里这会让每步代价随项增长。快速
-- 模式改用环境 + 闭包：绑定存进环境，参数作为共享 thunk 传递，同一次求值
-- 只算一次。它只给正规形，不产生轨迹或精确步数；燃料只用于挡住发散项
-- The small-step engine rebuilds the whole term every step, which grows with
-- Church arithmetic. Fast mode uses environments and closures instead: bindings
-- live in the environment and arguments are shared thunks, so each is evaluated
-- once. It yields a normal form only, with no trace or exact step count; the
-- fuel budget exists solely to stop divergent terms.
data DB = DVar Int | DFree String | DLam String DB | DApp DB DB

-- 惰性求值：参数是带 id 的 thunk，只在真正用到时求值并记忆结果，
-- 因此 Y 递归（如 rec fact）这类只有惰性求值才终止的项也能得到正规形
-- Lazy evaluation: arguments are thunks with ids, forced only when used and
-- memoized, so terms that only terminate lazily (e.g. rec fact via Y) also
-- reach a normal form.
data FastVal
  = FastLam String (Int -> FastM FastVal)   -- 参数是 thunk id / takes a thunk id
  | FastGen Int
  | FastFree String
  | FastApp FastVal Int                     -- 中性应用 + 参数 thunk / neutral app + arg thunk

data Thunk = Thunk DB [Int] | Done FastVal

data FastState = FastState
  { fsFuel  :: Int
  , fsNext  :: Int
  , fsStore :: IM.IntMap Thunk
  }

newtype FastM a = FastM { runFastM :: FastState -> Either () (a, FastState) }

instance Functor FastM where
  fmap f (FastM m) = FastM $ \s -> case m s of
    Left ()        -> Left ()
    Right (a, s')  -> Right (f a, s')

instance Applicative FastM where
  pure a = FastM $ \s -> Right (a, s)
  FastM mf <*> FastM ma = FastM $ \s -> case mf s of
    Left ()       -> Left ()
    Right (f, s1) -> case ma s1 of
      Left ()       -> Left ()
      Right (a, s2) -> Right (f a, s2)

instance Monad FastM where
  FastM m >>= k = FastM $ \s -> case m s of
    Left ()       -> Left ()
    Right (a, s1) -> case k a of FastM m' -> m' s1

-- 每发生一次 β 归约消耗一格燃料
-- One tick per β-contraction.
tick :: FastM ()
tick = FastM $ \s ->
  if fsFuel s <= 0 then Left () else Right ((), s { fsFuel = fsFuel s - 1 })

freshThunk :: DB -> [Int] -> FastM Int
freshThunk db env = FastM $ \s ->
  let i = fsNext s
  in Right (i, s { fsNext = i + 1, fsStore = IM.insert i (Thunk db env) (fsStore s) })

freshVal :: FastVal -> FastM Int
freshVal v = FastM $ \s ->
  let i = fsNext s
  in Right (i, s { fsNext = i + 1, fsStore = IM.insert i (Done v) (fsStore s) })

force :: Int -> FastM FastVal
force i = FastM $ \s -> case IM.lookup i (fsStore s) of
  Just (Done v)       -> Right (v, s)
  Just (Thunk db env) -> case runFastM (evalDB env db) s of
    Left ()       -> Left ()
    Right (v, s') -> Right (v, s' { fsStore = IM.insert i (Done v) (fsStore s') })
  Nothing             -> Right (FastFree "?", s)   -- 不可达 / unreachable

toDB :: [String] -> Expr -> DB
toDB bound (Var x)   = maybe (DFree x) DVar (elemIndex x bound)
toDB bound (Lam x b) = DLam x (toDB (x : bound) b)
toDB bound (App f a) = DApp (toDB bound f) (toDB bound a)

evalDB :: [Int] -> DB -> FastM FastVal
evalDB env (DVar i) =
  case drop i env of
    (t : _) -> force t
    []      -> pure (FastFree "?")   -- 不可达 / unreachable
evalDB _   (DFree x)  = pure (FastFree x)
evalDB env (DLam x b) = pure (FastLam x (\t -> evalDB (t : env) b))
evalDB env (DApp f a) = do
  vf <- evalDB env f
  t  <- freshThunk a env
  applyFast vf t

applyFast :: FastVal -> Int -> FastM FastVal
applyFast (FastLam _ f) t = tick >> f t
applyFast f t             = pure (FastApp f t)

quoteFast :: Set.Set String -> [String] -> FastVal -> FastM Expr
quoteFast _ bound (FastGen i) =
  let n = length bound
  in if i < n
       then pure (Var (bound !! (n - 1 - i)))
       else pure (Var ("#" ++ show i))
quoteFast _ _ (FastFree x) = pure (Var x)
quoteFast avoid bound (FastApp f t) =
  App <$> quoteFast avoid bound f <*> (force t >>= quoteFast avoid bound)
quoteFast avoid bound (FastLam hint f) = do
  t <- freshVal (FastGen (length bound))
  let name  = freshVar hint avoid
      avoid' = Set.insert name avoid
  Lam name <$> (f t >>= quoteFast avoid' (name : bound))

fastNormalForm :: Int -> Expr -> Maybe Expr
fastNormalForm fuel e =
  case runFastM (evalDB [] (toDB [] e) >>= quoteFast (freeVars e) [])
                (FastState fuel 0 IM.empty) of
    Left ()       -> Nothing
    Right (nf, _) -> Just nf

-- ---------------------------------------------------------------------------
-- 归约位置 Redex positions：列出项中所有 β-redex，并可按序号归约
-- All β-redexes with paths, so the user can pick which one to contract.
-- ---------------------------------------------------------------------------
type Path = [Int]

isBetaRedex :: Expr -> Bool
isBetaRedex (App (Lam _ _) _) = True
isBetaRedex _                 = False

isEtaRedex :: Expr -> Bool
isEtaRedex e = case etaRoot e of
  Just _  -> True
  Nothing -> False

isRedex :: Bool -> Expr -> Bool
isRedex eta e = isBetaRedex e || (eta && isEtaRedex e)

-- η 开启时，根位置也要能执行 η 归约
-- With eta on, an eta redex is also contractible at the root.
redexAtRoot :: Bool -> Expr -> Maybe StepOut
redexAtRoot _ (App (Lam x b) a) =
  let r = betaStep x b a in Just (StepOut (redTerm r) r)
redexAtRoot eta e
  | eta = fmap (\r -> StepOut (redTerm r) r) (etaRoot e)
  | otherwise = Nothing

-- 一次遍历同时收集路径、子项和规则；规则用 alphaNeeded 判断，避免为了
-- 显示而真的做一次替换
-- One traversal collects path, subterm and rule. The rule uses alphaNeeded,
-- so no substitution is performed just to display the list.
data Redex = Redex Path Expr String

redexInfos :: Bool -> Expr -> [Redex]
redexInfos eta = go []
  where
    -- 路径按反向累积，只有真的遇到 redex 时才 reverse；正规形里没有 redex，
    -- 因此不会为每个节点分配一条路径
    -- Paths accumulate reversed and are reversed only at a redex, so a normal
    -- form allocates no path per node.
    go rev e = here ++ children
      where
        here = case e of
          App (Lam x b) a ->
            [Redex (reverse rev) e (if alphaNeeded x b a then "β+α" else "β")]
          _ | eta, isEtaRedex e -> [Redex (reverse rev) e "η"]
            | otherwise         -> []
        children = case e of
          App f a -> go (0 : rev) f ++ go (1 : rev) a
          Lam _ b -> go (0 : rev) b
          _       -> []

stepAt :: Bool -> Path -> Expr -> Maybe StepOut
stepAt eta [] e = redexAtRoot eta e
stepAt eta (0:ps) (App f a) =
  (\s -> s { soWhole = App (soWhole s) a }) <$> stepAt eta ps f
stepAt eta (1:ps) (App f a) =
  (\s -> s { soWhole = App f (soWhole s) }) <$> stepAt eta ps a
stepAt eta (0:ps) (Lam x b) =
  (\s -> s { soWhole = Lam x (soWhole s) }) <$> stepAt eta ps b
stepAt _ _ _ = Nothing

stepAtIndex :: Bool -> Int -> Expr -> Maybe StepOut
stepAtIndex eta i e =
  case drop (max 0 (i - 1)) (redexInfos eta e) of
    (Redex p _ _ : _) -> stepAt eta p e
    []    -> Nothing

redexCount :: Bool -> Expr -> Int
redexCount eta = go
  where
    go e = (if isRedex eta e then 1 else 0) +
           case e of
             App f a -> go f + go a
             Lam _ b -> go b
             Var _   -> 0

pathText :: Path -> String
pathText [] = "root"
pathText ps = intercalate "." (map show ps)

-- ---------------------------------------------------------------------------
-- 宏展开（带绑定集与展开燃料）Macro Expansion
-- ---------------------------------------------------------------------------
expandFuel :: Int
expandFuel = 20000

-- 第二个分量表示燃料耗尽；此时结果仍含未展开的宏，调用方必须告警
-- The second component reports exhaustion: the term still holds macros and the
-- caller must warn instead of silently using it.
expand :: Int -> Env -> Set.Set String -> Expr -> (Expr, Bool)
expand fuel _ _ e | fuel <= 0 = (e, True)
expand fuel env bound (Var x)
  | x `Set.member` bound = (Var x, False)
  | Just e <- Map.lookup x env = expand (fuel - 1) env bound e
  | otherwise = (Var x, False)
expand fuel env bound (Lam x body) =
  let (b, hit) = expand fuel env (Set.insert x bound) body
  in (Lam x b, hit)
expand fuel env bound (App f a) =
  let (f', h1) = expand fuel env bound f
      (a', h2) = expand fuel env bound a
  in (App f' a', h1 || h2)

expandChecked :: Env -> Expr -> (Expr, Bool)
expandChecked env e = expand expandFuel env Set.empty e

expandTop :: Env -> Expr -> Expr
expandTop env = fst . expandChecked env

-- ---------------------------------------------------------------------------
-- 语义提示 Semantic Hints：Church 编码 / 组合子
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
    go n (Var x')   | x' == x = Just n
    go n (App (Var f') rest) | f' == f = go (n + 1) rest
    go _ _ = Nothing
isChurchNumeral _ = Nothing

isChurchBoolean :: Expr -> Maybe Bool
isChurchBoolean (Lam t (Lam f (Var t'))) | t == t' && t /= f = Just True
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

-- 提示保留中英两版，供前端在不重放历史的情况下切换语言
-- Hints keep both languages so the client can switch without replaying.
valueHintMsg :: Expr -> Msg
valueHintMsg e = case (isChurchNumeral e, isChurchBoolean e, isChurchPair e) of
  (Just 0, Just False, _) ->
    ("  (邱奇数 0 / Church 布尔值 False)",
     "  (Church numeral 0 / Church boolean False)")
  (Just n, _, _) ->
    ("  (邱奇数 " ++ show n ++ ")", "  (Church numeral " ++ show n ++ ")")
  (_, Just True, _) ->
    ("  (Church 布尔值 True / K 组合子)",
     "  (Church boolean True / K combinator)")
  (_, Just False, _) ->
    ("  (Church 布尔值 False)", "  (Church boolean False)")
  (_, _, Just (a, b)) ->
    let sa = shorten 20 (pretty a); sb = shorten 20 (pretty b)
    in ("  (Church 序对 " ++ sa ++ ", " ++ sb ++ ")",
        "  (Church pair " ++ sa ++ ", " ++ sb ++ ")")
  _ -> case combinatorOf e of
         Just n  -> ("  (" ++ n ++ " 组合子)", "  (" ++ n ++ " combinator)")
         Nothing -> ("", "")

-- ---------------------------------------------------------------------------
-- 美观打印 Pretty Printing
-- ---------------------------------------------------------------------------
pretty :: Expr -> String
pretty e = go 0 e ""
  where
    go :: Int -> Expr -> ShowS
    go _ (Var x)      = showString x
    go p (Lam x body) = showParen (p > 0)
      (showString "λ" . showString x . showString " → " . go 0 body)
    go p (App f a)    = showParen (p > 1)
      (go 1 f . showChar ' ' . go 2 a)

-- 字符串是惰性流：只强制前 n 个字符，截断巨型项时不再先把它整个打印出来
-- Strings are lazy streams: force only the first n characters. Truncating a
-- huge term no longer pretty-prints the whole thing first.
shorten :: Int -> String -> String
shorten n s
  | n <= 0    = ""
  | otherwise = case splitAt n s of
      (pre, []) -> pre
      (pre, _)  -> take (n - 1) pre ++ "…"

-- 惰性判断长度是否超过 n，同样不看完整串
-- Lazy length test: never touch more than n characters.
exceeds :: Int -> String -> Bool
exceeds n s = case splitAt (n + 1) s of
  (_, [])    -> False
  (_, _ : _) -> True

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
deBruijnView e = go [] e ""
  where
    go bound (Var x) = case elemIndex x bound of
      Just i  -> showChar '#' . shows i
      Nothing -> showString x
    go bound (Lam x b) = showString "λ." . go (x : bound) b
    go bound (App f a) =
      showChar '(' . go bound f . showChar ' ' . go bound a . showChar ')'

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
parseExpr = spaces *> (parseLet <++ parseIf <++ parseLam <++ parseApp)

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
  c <- satisfy (\ch -> isAlpha ch || isOperatorChar ch)
  cs <- go
  return (c : cs)
  where
    go = do
      rest <- look
      case rest of
        ('-':'>':_) -> return []
        (ch:_) | isAlpha ch || isDigit ch
               || ch `elem` ("_'" :: String)
               || isOperatorChar ch -> do
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
  binds <- parseBind `sepBy1` (spaces *> char ';' <* spaces)
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
  params <- many1 $ lamIdent <* spaces
  lambdaSep
  spaces
  body <- parseExpr
  return $ foldr Lam body params

parseApp :: ReadP Expr
parseApp = foldl App <$> parseAtom <*> many (spaces *> parseAtom)

parseAtom :: ReadP Expr
parseAtom = notKeyword "in" *> notKeyword "then" *> notKeyword "else"
            *> (parseNum <++ parseVar <++ parseList <++ parseParens)

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

-- 列表字面量 [a, b] 脱糖为 CONS a (CONS b NIL)
-- List literal [a, b] desugars to CONS a (CONS b NIL).
parseList :: ReadP Expr
parseList = between (char '[') (char ']') $ do
  spaces
  es <- parseExpr `sepBy` (spaces *> char ',' <* spaces)
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
  | isLambdaStart && not (hasSeparator s) =
      (pos, ( "Lambda 表达式缺少分隔符（形如 λx. body、λx → body 或 \\x -> body）"
            , "Lambda abstraction is missing '.', '→' or '->', e.g. λx. body" ))
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
    hasSeparator t = '.' `elem` t || '→' `elem` t || "->" `isPrefixOf` dropWhile (/= '-') t

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
             || c `elem` ("λ\\→().=_':" :: String)
             || isOperatorChar c

-- ---------------------------------------------------------------------------
-- 解析赋值 / 命令 Parse Assignment and Commands
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
  | DefineRec String Expr
  | LoadFile FilePath
  | SaveFile FilePath
  | ShowEnv
  | DeleteDef String
  | ResetEnv
  | SetStrategy Strategy
  | SetSteps Int
  | SetEta Bool
  | SetFast Bool
  | Trace Expr
  | Ast Expr
  | DbView Expr
  | TypeOf Expr (Maybe String)
  | TimeOf Int Expr
  | BenchOf Int Expr
  | EqExpr Expr Expr
  | ConvExpr Expr Expr
  | Nf Expr
  | Whnf Expr
  | IntOf Expr
  | ChurchOf Integer
  | Begin Expr
  | StepCmd (Maybe Int)
  | RunCmd
  | EndCmd
  | BackCmd
  | GotoCmd Int
  | ShowDef String
  | SearchEnv String
  | ReloadCmd
  | EditFile (Maybe FilePath)
  | SetLang Lang
  | Help (Maybe String)
  | Quit

knownCommands :: [(String, Msg)]
knownCommands =
  [ (":help", ("显示帮助；:help <命令> 查看单项", "show help; :help <cmd> for one command"))
  , (":load", ("加载定义文件", "load a definitions file"))
  , (":save", ("保存当前定义为 .lam 文件", "save the current definitions to a .lam file"))
  , (":let", ("定义变量；:let rec 支持递归", "define a variable; :let rec allows recursion"))
  , (":env", ("显示当前环境", "show the environment"))
  , (":del", ("删除一个定义", "delete a definition"))
  , (":reset", ("重置为预定义环境", "reset to the prelude"))
  , (":strategy", ("切换求值策略", "switch evaluation strategy"))
  , (":steps", ("设置归约步数上限（快速模式下为 β 燃料）", "set the reduction step limit (β fuel in fast mode)"))
  , (":eta", ("开启/关闭 η 归约", "turn eta reduction on/off"))
  , (":fast", ("开启/关闭共享快速正规化", "turn shared fast normalization on/off"))
  , (":time", ("测量求值耗时：:time [次数] <表达式>", "measure elapsed time: :time [runs] <expr>"))
  , (":bench", ("重复求值并给出平均/中位/标准差", "repeat an evaluation; report mean/median/stddev"))
  , (":trace", ("显示完整归约轨迹", "show the full reduction trace"))
  , (":ast", ("显示语法树", "show the syntax tree"))
  , (":db", ("de Bruijn 索引视图", "de Bruijn index view"))
  , (":type", ("推断简单类型", "infer the simple type"))
  , (":eq", ("判断两个表达式是否 α 等价", "test two expressions for alpha-equivalence"))
  , (":conv", ("判断两个表达式是否 β 等价", "test two expressions for beta-convertibility"))
  , (":nf", ("归约到正规形", "reduce to normal form"))
  , (":whnf", ("归约到弱首正规形", "reduce to weak head normal form"))
  , (":int", ("把邱奇数转成整数", "decode a Church numeral as an integer"))
  , (":church", ("把 0-9999 转成邱奇数", "encode 0-9999 as a Church numeral"))
  , (":begin", ("开始交互式归约", "start interactive reduction"))
  , (":step", ("归约一步；:step <n> 选择第 n 个 redex", "reduce one step; :step <n> picks the nth redex"))
  , (":run", ("归约到底", "reduce to the end"))
  , (":end", ("结束交互式归约", "end interactive reduction"))
  , (":back", ("回退一步手动归约", "step back one manual reduction"))
  , (":goto", ("跳到第 n 步：:goto <n>", "jump to step n: :goto <n>"))
  , (":def", ("显示单个定义：:def <名字>", "show one definition: :def <name>"))
  , (":search", ("在环境中搜索名字：:search <子串>", "search environment names: :search <substring>"))
  , (":reload", ("重新加载上次 :load 的文件", "reload the last :load file"))
  , (":edit", ("用编辑器打开文件：:edit [文件]", "open a file in $EDITOR: :edit [file]"))
  , (":lang", ("切换语言 zh/en/both", "switch language zh/en/both"))
  , (":q", ("退出", "quit"))
  ]

parseCommand :: String -> Either ParseError Command
parseCommand raw
  | null s = Left (ParseError 1 ("空输入", "Empty input"))
  | Just rest <- stripPrefix ":load " s = loadOrSave rest LoadFile
  | Just rest <- stripPrefix ":save " s = loadOrSave rest SaveFile
  | Just rest <- stripPrefix ":let rec " s = uncurry DefineRec <$> parseAssignment rest
  | Just rest <- stripPrefix ":let " s = uncurry Define <$> parseAssignment rest
  | Just rest <- stripPrefix "rec " s, '=' `elem` rest =
      uncurry DefineRec <$> parseAssignment rest
  | s == ":env" = Right ShowEnv
  | s == ":reset" = Right ResetEnv
  | s `elem` [":help", ":h", ":?"] = Right (Help Nothing)
  | Just rest <- stripPrefix ":help " s = Right (Help (Just (trim rest)))
  | Just rest <- stripPrefix ":h " s = Right (Help (Just (trim rest)))
  | s `elem` [":q", ":quit"] = Right Quit
  | s == ":step" = Right (StepCmd Nothing)
  | Just rest <- stripPrefix ":step " s =
      case reads (trim rest) :: [(Int, String)] of
        [(n, "")] | n > 0 -> Right (StepCmd (Just n))
        _ -> Left (ParseError 1
               ("用法：:step <redex 序号>", "Usage: :step <redex index>"))
  | s == ":run" = Right RunCmd
  | s == ":end" = Right EndCmd
  | s `elem` [":back", ":undo"] = Right BackCmd
  | Just rest <- stripPrefix ":goto " s =
      case reads (trim rest) :: [(Int, String)] of
        [(n, "")] | n >= 0 -> Right (GotoCmd n)
        _ -> Left (ParseError 1
               ("用法：:goto <步数>", "Usage: :goto <step>"))
  | Just rest <- stripPrefix ":def " s = showDef rest
  | Just rest <- stripPrefix ":search " s = searchNames rest
  | Just rest <- stripPrefix ":find " s = searchNames rest
  | s == ":reload" = Right ReloadCmd
  | s == ":edit" = Right (EditFile Nothing)
  | Just rest <- stripPrefix ":edit " s =
      if null (trim rest)
        then Left (ParseError 1 ("缺少文件路径", "Missing file path"))
        else Right (EditFile (Just (trim rest)))
  | s == ":eta" = Right (SetEta True)
  | Just rest <- stripPrefix ":eta " s =
      maybe (Left (ParseError 1
              ("用法：:eta on|off", "Usage: :eta on|off")))
            (Right . SetEta) (parseOnOff rest)
  | s == ":fast" = Right (SetFast True)
  | Just rest <- stripPrefix ":fast " s =
      maybe (Left (ParseError 1
              ("用法：:fast on|off", "Usage: :fast on|off")))
            (Right . SetFast) (parseOnOff rest)
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
  | Just rest <- stripPrefix ":type " s = parseTypeQuery rest
  | Just rest <- stripPrefix ":time " s = parseTime rest
  | Just rest <- stripPrefix ":bench " s = parseBench rest
  | Just rest <- stripPrefix ":nf " s = Nf <$> parseExpr' rest
  | Just rest <- stripPrefix ":whnf " s = Whnf <$> parseExpr' rest
  | Just rest <- stripPrefix ":int " s = IntOf <$> parseExpr' rest
  | Just rest <- stripPrefix ":church " s =
      case reads (trim rest) :: [(Integer, String)] of
        [(n, "")] | n >= 0 && n <= 9999 -> Right (ChurchOf n)
        _ -> Left (ParseError 1
               ("用法：:church <0-9999>", "Usage: :church <0-9999>"))
  | Just rest <- stripPrefix ":eq " s = uncurry EqExpr <$> parsePairIn ":eq" rest
  | Just rest <- stripPrefix ":conv " s = uncurry ConvExpr <$> parsePairIn ":conv" rest
  | Just rest <- stripPrefix ":begin " s = Begin <$> parseExpr' rest
  | Just _ <- stripPrefix ":" s = Left (ParseError 1
      ( "未知命令 " ++ takeWhile (not . isSpace) s ++ "，输入 :help 查看全部命令"
      , "Unknown command " ++ takeWhile (not . isSpace) s ++ "; type :help for the full list" ))
  | otherwise =
      -- 先按表达式解析，让含 `=` 的 let / 标注表达式不会被误判为定义
      -- Parse as an expression first, so let / annotated expressions containing
      -- `=` are not mistaken for definitions.
      case runParserFull parseExpr s of
        Right x -> Right (Eval x)
        Left eExpr -> case parseAssignment s of
          Right (name, expr) -> Right (Define name expr)
          Left eAssign
            | '=' `elem` s -> Left eAssign
            | otherwise    -> Left eExpr
  where
    s = trim (stripTrailingComment raw)
    -- :type 可选的类型标注：在括号外用最后一个冒号切分
    -- Optional :type annotation: split at the last top-level colon.
    parseTypeQuery src =
      let txt = trim src
          off = length s - length txt
          (eTxt, ann) = splitTypeAnnotation txt
      in case runParserFull parseExpr (trim eTxt) of
           Left e  -> Left e { pePos = pePos e + off }
           Right x -> Right (TypeOf x ann)
    parseTime src =
      let txt = trim src
          numTxt = takeWhile (not . isSpace) txt
          rest   = dropWhile isSpace txt
      in case reads numTxt :: [(Int, String)] of
           [(n, "")] | n > 0 && n <= 1000, not (null (trim rest)) ->
             case runParserFull parseExpr (trim rest) of
               Left e  -> Left e { pePos = pePos e + (length s - length (trim rest)) }
               Right x -> Right (TimeOf n x)
           _ -> TimeOf 1 <$> parseExpr' src
    parseBench src =
      let txt = trim src
          numTxt = takeWhile (not . isSpace) txt
          rest   = dropWhile (not . isSpace) txt
          usage  = ParseError 1
                     ("用法：:bench <1-1000> <表达式>", "Usage: :bench <1-1000> <expr>")
      in case reads numTxt :: [(Int, String)] of
           [(n, "")] | n > 0 && n <= 1000, not (null (trim rest)) ->
             case runParserFull parseExpr (trim rest) of
               Left e  -> Left e { pePos = pePos e + (length s - length (trim rest)) }
               Right x -> Right (BenchOf n x)
           _ -> Left usage
    deleteDef rest =
      let name = trim rest
      in if null name
           then Left (ParseError 1 ("用法：:del <名字>", "Usage: :del <name>"))
           else Right (DeleteDef name)
    showDef rest =
      let name = trim rest
      in if null name
           then Left (ParseError 1 ("用法：:def <名字>", "Usage: :def <name>"))
           else Right (ShowDef name)
    searchNames rest =
      let needle = trim rest
      in if null needle
           then Left (ParseError 1
                  ("用法：:search <子串>", "Usage: :search <substring>"))
           else Right (SearchEnv needle)
    loadOrSave rest ctor =
      let path = trim rest
      in if null path
           then Left (ParseError 1
                  ("缺少文件路径", "Missing file path"))
           else Right (ctor path)
    parseExpr' src = case runParserFull parseExpr (trim src) of
      Left e  -> Left e { pePos = pePos e + (length s - length (trim src)) }
      Right x -> Right x

-- 在括号外按最后一个冒号切分 `:type expr : T`
-- Split `:type expr : T` at the last colon outside parentheses.
splitTypeAnnotation :: String -> (String, Maybe String)
splitTypeAnnotation txt =
  case [i | (i, c) <- zip [0..] txt, c == ':', depthAt i == 0] of
    []  -> (txt, Nothing)
    xs  -> (take (last xs) txt, Just (trim (drop (last xs + 1) txt)))
  where
    depthAt :: Int -> Int
    depthAt i = foldl' step 0 (take i txt)
    step :: Int -> Char -> Int
    step d '(' = d + 1
    step d ')' = max 0 (d - 1)
    step d _   = d

-- 用逗号分隔两个表达式；逗号不属于表达式语法
-- Two expressions separated by a comma (a comma cannot occur in an expression).
parsePairIn :: String -> String -> Either ParseError (Expr, Expr)
parsePairIn cmdName src =
  case break (== ',') src of
    (l, ',':r)
      | null (trim l) || null (trim r) -> usage
      | otherwise ->
          case (runParserFull parseExpr (trim l), runParserFull parseExpr (trim r)) of
            (Right a, Right b) -> Right (a, b)
            (Left e, Right _)  -> Left e
            (Right _, Left e)  -> Left e
            (Left e1, Left e2) -> Left (ParseError 1
              ( "左侧错误：" ++ fst (peMsg e1) ++ "；右侧错误：" ++ fst (peMsg e2)
              , "left: " ++ snd (peMsg e1) ++ "; right: " ++ snd (peMsg e2) ))
    _ -> usage
  where
    usage = Left (ParseError 1
      ( "用法：" ++ cmdName ++ " <表达式> , <表达式>"
      , "Usage: " ++ cmdName ++ " <expr> , <expr>" ))

parseOnOff :: String -> Maybe Bool
parseOnOff raw = case map lower (trim raw) of
  "on"  -> Just True
  "1"   -> Just True
  "true" -> Just True
  "off" -> Just False
  "0"   -> Just False
  "false" -> Just False
  _     -> Nothing
  where
    lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c

-- ---------------------------------------------------------------------------
-- 简单类型推断 Simple Type Inference (Hindley–Milner)
-- ---------------------------------------------------------------------------
data Ty = TVar String | TArr Ty Ty deriving (Eq)

prettyTy :: Ty -> String
prettyTy t = go 0 t ""
  where
    go :: Int -> Ty -> ShowS
    go _ (TVar v)   = showString v
    go p (TArr a b) = showParen (p > 0)
      (go 1 a . showString " → " . go 0 b)

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

-- 解析用户写的类型标注文本；失败时当作未标注处理
-- Parse a user-written type annotation; an unparseable one is ignored.
parseTyText :: String -> Maybe Ty
parseTyText s =
  case [t | (t, rest) <- readP_to_S (tyP <* spaces) s, null rest] of
    (t:_) -> Just t
    []    -> Nothing
  where
    tyP = do
      a <- atom
      (do spaces
          void (string "->" <|> string "→")
          spaces
          b <- tyP
          return (TArr a b)) <++ return a
    atom =
      (do _ <- char '('
          spaces
          t <- tyP
          spaces
          _ <- char ')'
          return t)
      <++ (TVar <$> munch1 (\c -> isAlpha c || isDigit c || c `elem` ("_'" :: String)))

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
-- `let x = e1 in e2` 脱糖成 (\x.e2) e1；对这个形状做 let 泛化
-- `let x = e1 in e2` desugars to (\x.e2) e1; generalize that shape.
infer env (App (Lam x body) val) = do
  tv  <- infer env val
  sc  <- generalize env tv
  infer (Map.insert x sc env) body
infer env (App f a) = do
  tf <- infer env f
  ta <- infer env a
  tv <- freshTy
  unify tf (TArr ta tv)
  return tv

generalize :: TypeEnv -> Ty -> TI Scheme
generalize env t = do
  t' <- applySub t
  -- 环境中的类型也要应用当前替换，否则与之相连的自由变量会被错误地泛化
  -- Apply the substitution to environment types too, or variables linked to
  -- the environment are wrongly quantified.
  envTypes <- mapM (\(Forall vs ty) -> do
                       ty' <- applySub ty
                       return (vs, ty')) (Map.elems env)
  let envFree = Set.unions
        [ freeTyVars ty `Set.difference` Set.fromList vs
        | (vs, ty) <- envTypes ]
  return (Forall (Set.toList (freeTyVars t' `Set.difference` envFree)) t')

runTI :: TI a -> Int -> Either String a
runTI m seed = case unTI m (TISt seed 0 Map.empty) of
  Left e       -> Left e
  Right (a, _) -> Right a

inferScheme :: TypeEnv -> Expr -> Either String Scheme
inferScheme tenv e = runTI go (Map.size tenv + 1)
  where
    -- 自由变量必须是单态的：同一名字的每次出现共享一个类型变量，
    -- 否则 'x x' 会被错误地类型化
    -- Free variables are monomorphic: every occurrence of a name shares one
    -- type variable, otherwise 'x x' would incorrectly type-check.
    go = do
      seeded <- foldM addFree tenv (Set.toList (freeVars e))
      infer seeded e >>= generalize seeded
    addFree env v
      | Map.member v env = return env
      | otherwise        = do
          tv <- freshTy
          return (Map.insert v (Forall [] tv) env)

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
  , ("XOR",   Lam "b1" $ Lam "b2" $
              apps (Var "IF") [Var "b1", App (Var "NOT") (Var "b2"), Var "b2"])
  , ("NAND",  Lam "b1" $ Lam "b2" $
              App (Var "NOT") (apps (Var "AND") [Var "b1", Var "b2"]))
  , ("IF",    Lam "c" $ Lam "t" $ Lam "f" $ App (App (Var "c") (Var "t")) (Var "f"))
  , ("I",     Lam "x" (Var "x"))
  , ("K",     Lam "x" $ Lam "y" (Var "x"))
  , ("S",     Lam "x" $ Lam "y" $ Lam "z" $
              apps (Var "x") [Var "z", apps (Var "y") [Var "z"]])
  , ("B",     Lam "x" $ Lam "y" $ Lam "z" $
              App (Var "x") (apps (Var "y") [Var "z"]))
  , ("C",     Lam "x" $ Lam "y" $ Lam "z" $
              apps (Var "x") [Var "z", Var "y"])
  , ("W",     Lam "x" $ Lam "y" $ apps (Var "x") [Var "y", Var "y"])
  , ("ZERO",  Lam "f" (Lam "x" (Var "x")))
  , ("ONE",   Lam "f" (Lam "x" (App (Var "f") (Var "x"))))
  , ("TWO",   Lam "f" (Lam "x" (App (Var "f") (App (Var "f") (Var "x")))))
  , ("THREE", Lam "f" (Lam "x" (App (Var "f") (App (Var "f") (App (Var "f") (Var "x"))))))
  , ("SUCC",  Lam "n" $ Lam "f" $ Lam "x" $ App (Var "f") (App (App (Var "n") (Var "f")) (Var "x")))
  , ("PLUS",  Lam "m" $ Lam "n" $ Lam "f" $ Lam "x" $ App (App (Var "m") (Var "f")) (App (App (Var "n") (Var "f")) (Var "x")))
  , ("MULT",  Lam "m" $ Lam "n" $ Lam "f" $ App (Var "m") (App (Var "n") (Var "f")))
  , ("EXP",   Lam "m" $ Lam "n" $ App (Var "n") (Var "m"))
  , ("PRED",  Lam "n" $ Lam "f" $ Lam "x" $
              App (App (App (Var "n")
                    (Lam "g" $ Lam "h" $ App (Var "h") (App (Var "g") (Var "f"))))
                    (Lam "u" (Var "x")))
                  (Lam "u" (Var "u")))
  , ("SUB",   Lam "m" $ Lam "n" $ App (App (Var "n") (Var "PRED")) (Var "m"))
  , ("ISZERO", Lam "n" $ App (App (Var "n") (Lam "x" (Var "FALSE"))) (Var "TRUE"))
  , ("LEQ",   Lam "m" $ Lam "n" $ App (Var "ISZERO") (App (App (Var "SUB") (Var "m")) (Var "n")))
  , ("EQ",    Lam "m" $ Lam "n" $
              App (App (Var "AND") (App (App (Var "LEQ") (Var "m")) (Var "n")))
                            (App (App (Var "LEQ") (Var "n")) (Var "m")))
  , ("MIN",   Lam "m" $ Lam "n" $
              apps (Var "IF") [apps (Var "LEQ") [Var "m", Var "n"], Var "m", Var "n"])
  , ("MAX",   Lam "m" $ Lam "n" $
              apps (Var "IF") [apps (Var "LEQ") [Var "m", Var "n"], Var "n", Var "m"])
  , ("DIV",   recDef "div" $ Lam "m" $ Lam "n" $
              apps (Var "IF")
                [ apps (Var "LEQ") [Var "n", Var "m"]
                , apps (Var "SUCC")
                    [ apps (Var "div") [apps (Var "SUB") [Var "m", Var "n"], Var "n"] ]
                , Var "ZERO" ])
  , ("MOD",   Lam "m" $ Lam "n" $
              apps (Var "SUB")
                [ Var "m"
                , apps (Var "MULT") [Var "n", apps (Var "DIV") [Var "m", Var "n"]] ])
  , ("PAIR",  Lam "a" $ Lam "b" $ Lam "f" $
              App (App (Var "f") (Var "a")) (Var "b"))
  , ("FST",   Lam "p" $ App (Var "p") (Var "TRUE"))
  , ("SND",   Lam "p" $ App (Var "p") (Var "FALSE"))
  , ("NIL",   Lam "n" $ Lam "c" $ Var "n")
  , ("CONS",  Lam "h" $ Lam "t" $ Lam "n" $ Lam "c" $
              App (App (Var "c") (Var "h")) (Var "t"))
  , ("HEAD",  Lam "l" $ App (App (Var "l") (Var "NIL"))
              (Lam "h" $ Lam "t" $ Var "h"))
  , ("TAIL",  Lam "l" $ App (App (Var "l") (Var "NIL"))
              (Lam "h" $ Lam "t" $ Var "t"))
  , ("APPEND", recDef "append" $ Lam "xs" $ Lam "ys" $
              apps (Var "xs")
                [ Var "ys"
                , Lam "h" $ Lam "t" $
                    apps (Var "CONS") [Var "h", apps (Var "append") [Var "t", Var "ys"]] ])
  , ("REV",   recDef "rev" $ Lam "xs" $
              apps (Var "xs")
                [ Var "NIL"
                , Lam "h" $ Lam "t" $
                    apps (Var "APPEND")
                      [ apps (Var "rev") [Var "t"], apps (Var "CONS") [Var "h", Var "NIL"] ] ])
  , ("LENGTH", recDef "len" $ Lam "xs" $
              apps (Var "xs")
                [ Var "ZERO"
                , Lam "h" $ Lam "t" $ apps (Var "SUCC") [apps (Var "len") [Var "t"]] ])
  , ("MAP",   recDef "map" $ Lam "f" $ Lam "xs" $
              apps (Var "xs")
                [ Var "NIL"
                , Lam "h" $ Lam "t" $
                    apps (Var "CONS")
                      [ apps (Var "f") [Var "h"], apps (Var "map") [Var "f", Var "t"] ] ])
  , ("FILTER", recDef "filter" $ Lam "p" $ Lam "xs" $
              apps (Var "xs")
                [ Var "NIL"
                , Lam "h" $ Lam "t" $
                    apps (Var "IF")
                      [ apps (Var "p") [Var "h"]
                      , apps (Var "CONS")
                          [ Var "h", apps (Var "filter") [Var "p", Var "t"] ]
                      , apps (Var "filter") [Var "p", Var "t"] ] ])
  , ("FOLD",  recDef "fold" $ Lam "f" $ Lam "z" $ Lam "xs" $
              apps (Var "xs")
                [ Var "z"
                , Lam "h" $ Lam "t" $
                    apps (Var "f") [Var "h", apps (Var "fold") [Var "f", Var "z", Var "t"]] ])
  , ("RANGE", recDef "range" $ Lam "a" $ Lam "b" $
              apps (Var "IF")
                [ apps (Var "LEQ") [Var "a", Var "b"]
                , apps (Var "CONS")
                    [ Var "a"
                    , apps (Var "range") [apps (Var "SUCC") [Var "a"], Var "b"] ]
                , Var "NIL" ])
  , ("ZIP",   recDef "zip" $ Lam "xs" $ Lam "ys" $
              apps (Var "xs")
                [ Var "NIL"
                , Lam "h" $ Lam "t" $
                    apps (Var "ys")
                      [ Var "NIL"
                      , Lam "h2" $ Lam "t2" $
                          apps (Var "CONS")
                            [ apps (Var "PAIR") [Var "h", Var "h2"]
                            , apps (Var "zip") [Var "t", Var "t2"] ] ] ])
  , ("Y",     yComb)
  ]

-- 多参数应用 / apply an expression to several arguments
apps :: Expr -> [Expr] -> Expr
apps = foldl App

-- 用 Y 组合子书写的递归定义 / a recursive definition written with Y
recDef :: String -> Expr -> Expr
recDef name body = App zComb (Lam name body)

-- 不动点组合子 / fixed-point combinators
-- Y 在正规序下工作；Z 是 call-by-value 版本，默认应用序下也能收敛
-- Y works under normal order; Z is the call-by-value variant used by `rec`,
-- so recursive definitions also converge under the default applicative order.
yComb :: Expr
yComb = Lam "f" $ App (Lam "x" $ App (Var "f") (App (Var "x") (Var "x")))
                     (Lam "x" $ App (Var "f") (App (Var "x") (Var "x")))

zComb :: Expr
zComb = Lam "f" $ App (Lam "x" $ App (Var "f")
                        (Lam "v" $ App (App (Var "x") (Var "x")) (Var "v")))
                     (Lam "x" $ App (Var "f")
                        (Lam "v" $ App (App (Var "x") (Var "x")) (Var "v")))

isFixComb :: Expr -> Bool
isFixComb f = alphaEq f yComb || alphaEq f zComb

initTypeEnv :: TypeEnv
initTypeEnv = buildTypeEnv Map.empty (Map.toList initEnv)

buildTypeEnv :: TypeEnv -> [(String, Expr)] -> TypeEnv
buildTypeEnv = foldl' step
  where
    -- 先展开宏再推断，避免依赖 Map 的遍历顺序
    -- Expand macros before inference so the result does not depend on Map order.
    step tenv (name, expr) = case inferScheme tenv (expandTop initEnv expr) of
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
  , rsTimeout :: Int
  , rsEta     :: Bool
  , rsFast    :: Bool
  , rsJson    :: Bool
  , rsLang    :: Lang
  , rsCurrent :: Maybe Expr
  , rsTrail   :: [Expr]          -- 手动归约历史，最新在前 / newest first
  , rsLastFile :: Maybe FilePath -- 上次 :load 的文件 / last loaded file
  , rsMaxTerm :: Maybe Int       -- 表达式节点上限 / optional AST node cap
  }

-- ---------------------------------------------------------------------------
-- 极简 JSON / a tiny JSON algebra
-- ---------------------------------------------------------------------------
data J = JStr String | JNum Int | JDec Double | JBool Bool | JArr [J] | JObj [(String, J)]

infixr 8 .=
(.=) :: String -> J -> (String, J)
k .= v = (k, v)

encode :: J -> String
encode = \case
  JStr s   -> quote s
  JNum n   -> show n
  JDec d   -> showFFloat (Just 3) d ""
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

-- 输出同时携带两种语言；text 用当前语言，textZh/textEn 供前端本地切换
-- Output carries both languages; text uses the current language and
-- textZh/textEn let the client re-render without replaying commands.
-- 机器可读错误码；调用方可以用同名字段覆盖默认值
-- Machine-readable error codes; callers may override the same field.
errorCode :: String -> String
errorCode "error" = "parse_error"
errorCode "fail"  = "command_failed"
errorCode "warn"  = "warning"
errorCode k       = k

withCode :: String -> [(String, J)] -> [(String, J)]
withCode kind fs
  | kind `elem` ["error", "fail", "warn"]
  , not (any ((== "code") . fst) fs) = ("code" .= JStr (errorCode kind)) : fs
  | otherwise = fs

emitL :: ReplState -> String -> String -> String -> [(String, J)] -> IO ()
emitL st kind zh en fields
  | rsJson st = mask_ . putStrLn . encode $
      JObj (("kind" .= JStr kind)
            : ("text" .= JStr (renderMsg (rsLang st) (zh, en)))
            : ("textZh" .= JStr zh)
            : ("textEn" .= JStr en)
            : withCode kind fields)
  | otherwise = mask_ . putStrLn $
      decorate kind ++ renderMsg (rsLang st) (zh, en)

emit :: ReplState -> String -> String -> [(String, J)] -> IO ()
emit st kind text = emitL st kind text text

-- 轨迹上限：超出后仍保留计数，但只在 JSON 中返回前若干步
-- Trace cap: the count is always exact; JSON carries only the first steps.
traceLimit :: Int
traceLimit = 500

traceClipped :: [TraceStep] -> Bool
traceClipped steps = any longStep steps
  where
    longStep s = exceeds 300 (pretty (tsBefore s)) || exceeds 300 (pretty (tsAfter s))

-- 一次遍历同时生成轨迹 JSON 与截断标记，避免重复 pretty
-- Build the trace JSON and its clipped flag in one pass (pretty is expensive).
traceFields :: Int -> [TraceStep] -> [(String, J)]
traceFields total steps
  | null steps = []
  | otherwise =
      [ "trace"          .= JArr (map fst rendered)
      , "traceShown"     .= JNum (length shown)
      , "traceTruncated" .= JBool (total > length shown || any snd rendered) ]
  where
    shown = take traceLimit steps
    rendered = map one shown
    one s =
      let before = pretty (tsBefore s)
          after  = pretty (tsAfter s)
          long   = exceeds 300 before || exceeds 300 after
      in ( JObj
             [ "n"      .= JNum (tsIndex s)
             , "rule"   .= JStr (tsRule s)
             , "note"   .= JStr (tsNote s)
             , "before" .= JStr (shorten 300 before)
             , "after"  .= JStr (shorten 300 after) ]
         , long )

-- 树形视图的缩进随深度线性增长，大项会变成几十 MB，只在尺寸允许时输出
-- Tree indentation grows with depth, so huge terms would explode; bound it.
astBudget :: Int
astBudget = 400

astFieldSized :: Int -> Expr -> (String, J)
astFieldSized n e
  | n <= astBudget = "ast" .= JArr (map JStr (treeLines e))
  | otherwise      = "astOmitted" .= JBool True

-- 与 astFieldSized 一样限制文本树：缩进随深度增长，大项会撑爆 JSON
-- Bound the text tree like astFieldSized; indentation grows with depth.
treeFieldSized :: Int -> Expr -> (String, J)
treeFieldSized n e
  | n <= astBudget = "tree" .= JArr (map JStr (treeLines e))
  | otherwise      = "astOmitted" .= JBool True

-- 结构化语法树，供 Web 端折叠显示
-- Structured AST for the collapsible web tree.
astJson :: Expr -> J
astJson (Var x) = JObj ["k" .= JStr "var", "label" .= JStr x]
astJson (Lam x b) = JObj
  [ "k" .= JStr "lam", "label" .= JStr x
  , "c" .= JArr [astJson b] ]
astJson (App f a) = JObj
  [ "k" .= JStr "app", "label" .= JStr "App"
  , "c" .= JArr [astJson f, astJson a] ]

astTreeField :: Expr -> (String, J)
astTreeField e = "astTree" .= astJson e

-- 项规模，用于限制结构化 AST 的 JSON 体积
-- Term size, used to cap the structured AST payload.
exprSize :: Expr -> Int
exprSize (Var _)   = 1
exprSize (Lam _ b) = 1 + exprSize b
exprSize (App f a) = 1 + exprSize f + exprSize a

-- 结构化 AST 只对较小的项输出，避免深层 Church 数把 JSON 撑大
-- Emit the structured AST only for small terms; deep Church numerals would bloat JSON.
astTreeFieldsSized :: Int -> Expr -> [(String, J)]
astTreeFieldsSized n e
  | n <= astBudget = [astTreeField e]
  | otherwise      = [ "astTreeOmitted" .= JBool True ]

-- de Bruijn 视图对大项截断，避免单行串无限增长
-- Bound the de Bruijn view for large terms so one line cannot grow unbounded.
dbFieldSized :: Int -> Expr -> (String, J)
dbFieldSized n e
  | n <= astBudget = "db" .= JStr view
  | otherwise      = "db" .= JStr (shorten 1000 view)
  where view = deBruijnView e

-- 归约位置列表 / list of β-redexes (capped so huge terms stay bounded)
redexFields :: Bool -> Expr -> [(String, J)]
redexFields eta e =
  [ "redexes" .= JArr (map one (zip [1..] (take 200 infos)))
  , "redexCount" .= JNum (length infos) ]
  where
    infos = redexInfos eta e
    one (i, Redex p sub rule) = JObj
      [ "i"    .= JNum i
      , "path" .= JStr (pathText p)
      , "term" .= JStr (shorten 200 (pretty sub))
      , "rule" .= JStr rule ]

-- ---------------------------------------------------------------------------
-- 表格打印 Print Table
-- ---------------------------------------------------------------------------
-- 终端显示宽度：CJK 字符占两格 / terminal display width (CJK glyphs use two cells)
displayWidth :: String -> Int
displayWidth = sum . map charWidth
  where
    charWidth c
      | o >= 0x1100 && o <= 0x115F = 2
      | o >= 0x2E80 && o <= 0xA4CF = 2
      | o >= 0xAC00 && o <= 0xD7A3 = 2
      | o >= 0xF900 && o <= 0xFAFF = 2
      | o >= 0xFE30 && o <= 0xFE6F = 2
      | o >= 0xFF00 && o <= 0xFF60 = 2
      | o >= 0xFFE0 && o <= 0xFFE6 = 2
      | o >= 0x1F300 && o <= 0x1FAFF = 2
      | o >= 0x20000 = 2
      | otherwise = 1
      where o = ord c

padRight :: Int -> String -> String
padRight n s = s ++ replicate (max 0 (n - displayWidth s)) ' '

renderTable :: Lang -> [(String, String, String)] -> String
renderTable _ [] = ""
renderTable lang rows = unlines $
  [top, formatRow (head1, head2, head3), mid]
  ++ map formatRow rows ++ [bottom]
  where
    hasTy   = any (not . null . third) rows
    head1   = renderMsg lang ("变量名", "Var Name")
    head2   = renderMsg lang ("值", "Value")
    head3   = renderMsg lang ("类型", "Type")
    col1Len = maximum $ displayWidth head1 : map (displayWidth . first) rows
    col2Len = maximum $ displayWidth head2 : map (displayWidth . second) rows
    col3Len = maximum $ displayWidth head3 : map (displayWidth . third) rows
    first  (a, _, _) = a
    second (_, b, _) = b
    third  (_, _, c) = c
    mkBorder c1 c2 c3 =
      c1 : replicate (col1Len + 2) '─'
         ++ [c2] ++ replicate (col2Len + 2) '─'
         ++ if hasTy then [c2] ++ replicate (col3Len + 2) '─' ++ [c3] else [c3]
    top    = mkBorder '┌' '┬' '┐'
    mid    = mkBorder '├' '┼' '┤'
    bottom = mkBorder '└' '┴' '┘'
    formatRow (a, b, c)
      | hasTy     = "│ " ++ padRight col1Len a ++ " │ " ++ padRight col2Len b
                    ++ " │ " ++ padRight col3Len c ++ " │"
      | otherwise = "│ " ++ padRight col1Len a ++ " │ " ++ padRight col2Len b ++ " │"

-- ---------------------------------------------------------------------------
-- 文件加载 File Loading
-- ---------------------------------------------------------------------------
-- 始终按 UTF-8 读取（与 writeFileUtf8 对应），并强制内容以捕获读取中的解码错误
-- Always read UTF-8 (mirrors writeFileUtf8) and force the content so decode
-- errors during reading are caught instead of escaping the lazy readFile.
readFileSafe :: FilePath -> IO (Either String String)
readFileSafe path = catch go handler
  where
    go = withFile path ReadMode $ \h -> do
      hSetEncoding h utf8
      s <- hGetContents h
      -- 去掉可能存在的 UTF-8 BOM，否则首行定义无法解析
      -- Drop a leading UTF-8 BOM, or the first definition fails to parse.
      let s' = case s of
                 ('\xFEFF':rest) -> rest
                 _               -> s
          n = length s'
      n `seq` return (Right s')
    handler (e :: SomeException) = return $ Left $ show e

data LoadOutcome = LoadOutcome
  { loEnv      :: Env
  , loTypeEnv  :: TypeEnv
  , loOk       :: [(String, Expr)]
  , loFail     :: [(Int, String, Msg, String)]
  , loStrategy :: Maybe Strategy
  , loLimit    :: Maybe Int
  , loLang     :: Maybe Lang
  , loFast     :: Maybe Bool
  , loEta      :: Maybe Bool
  , loEcho     :: [String]
  }

-- 注释行：`--` 或 `#` 开头 / comment lines start with `--` or `#`
isCommentLine :: String -> Bool
isCommentLine line = case trim line of
  ('-':'-':_) -> True
  ('#':_)     -> True
  _           -> False

parenDelta :: String -> Int
parenDelta = foldl' step 0
  where
    step d '(' = d + 1
    step d '[' = d + 1
    step d ')' = d - 1
    step d ']' = d - 1
    step d _   = d

-- 逻辑行：跳过空行/注释，圆括号或方括号未闭合时自动续行
-- Logical lines: skip blanks/comments, join continuation lines while parentheses or brackets stay open.
logicalLines :: String -> [(Int, String)]
logicalLines content = go (zip [1..] (lines content))
  where
    go [] = []
    go ((n, l):rest) =
      let l' = stripTrailingComment l
      in if null (trim l') || isCommentLine l
           then go rest
           else let first = trim l'
                    (parts, rest') = gatherLines [first] ('=' `elem` first)
                                                 (parenDelta l') rest
                in (n, unwords (reverse parts)) : go rest'
    gatherLines parts hasEq depth rest@((_, l):more)
      | isCommentLine l = gatherLines parts hasEq depth more
      | depth > 0 || (startsIndented l && hasEq) =
          let part = trim (stripTrailingComment l)
          in gatherLines (part : parts) (hasEq || '=' `elem` part)
                        (depth + parenDelta part) more
      | otherwise = (parts, rest)
    gatherLines parts _ _ [] = (parts, [])
    startsIndented (c:_) = isSpace c
    startsIndented []    = False

loadDefinitionsFromFile :: Maybe Int -> Env -> TypeEnv -> FilePath
                        -> IO (Either String LoadOutcome)
loadDefinitionsFromFile maxTerm env0 tenv0 path = do
  contentOrErr <- readFileSafe path
  case contentOrErr of
    Left err -> return (Left err)
    Right content -> do
      let start = LoadOutcome env0 tenv0 [] [] Nothing Nothing Nothing Nothing
                                Nothing []
      return (Right (foldl' processLine start (logicalLines content)))
  where
    sizeError e = case maxTerm of
      Just cap | exprSize e > cap ->
        Just ( "表达式过大（节点上限 " ++ show cap ++ "）"
             , "Expression too large (node limit " ++ show cap ++ ")" )
      _ -> Nothing
    processLine acc (n, line) =
      case parseCommand line of
        Left err -> failLine acc n line (peMsg err) "parse_error"
        Right (Define var expr) ->
          case sizeError expr of
            Just msg -> failLine acc n line msg "term_too_large"
            Nothing ->
              let expr' = expandTop (loEnv acc) expr
              in case sizeError expr' of
                   Just msg -> failLine acc n line msg "term_too_large"
                   Nothing ->
                     let env'  = Map.insert var expr' (loEnv acc)
                         tenv' = case inferScheme (loTypeEnv acc) expr of
                           Right sc -> Map.insert var sc (loTypeEnv acc)
                           Left _   -> Map.delete var (loTypeEnv acc)
                     in acc { loEnv = env', loTypeEnv = tenv'
                            , loOk = (var, expr') : loOk acc }
        Right (DefineRec var expr) ->
          case sizeError expr of
            Just msg -> failLine acc n line msg "term_too_large"
            Nothing ->
              let body = expandTop (Map.delete var (loEnv acc)) expr
              in case sizeError body of
                   Just msg -> failLine acc n line msg "term_too_large"
                   Nothing ->
                     let expr' = App zComb (Lam var body)
                         env'  = Map.insert var expr' (loEnv acc)
                         -- 递归定义（不动点编码）在简单类型系统中不可类型化，必须清掉旧方案
                         -- A recursive definition has no simple type, so drop the old scheme.
                         tenv' = Map.delete var (loTypeEnv acc)
                     in acc { loEnv = env', loTypeEnv = tenv'
                            , loOk = (var, expr') : loOk acc }
        Right (DeleteDef name) -> acc
          { loEnv = Map.delete name (loEnv acc)
          , loTypeEnv = Map.delete name (loTypeEnv acc)
          , loOk = filter ((/= name) . fst) (loOk acc) }
        Right ResetEnv -> acc
          { loEnv = initEnv, loTypeEnv = initTypeEnv, loOk = [] }
        Right (SetStrategy s) -> acc { loStrategy = Just s }
        Right (SetSteps k)    -> acc { loLimit = Just k }
        Right (SetLang l)     -> acc { loLang = Just l }
        Right (SetFast b)     -> acc { loFast = Just b }
        Right (SetEta b)      -> acc { loEta = Just b }
        Right c | isQueryCommand c -> acc { loEcho = loEcho acc ++ [line] }
        Right _ -> failLine acc n line
          ("定义文件不支持该命令", "Command not supported in a definition file")
          "unsupported_command"
    failLine acc n line msg code =
      acc { loFail = (n, line, msg, code) : loFail acc }

-- 查询类命令在加载完定义后按原样执行，输出仍走各自的 reporter
-- Query commands are replayed after load so their output uses their reporter.
isQueryCommand :: Command -> Bool
isQueryCommand c = case c of
  Trace _      -> True
  Ast _        -> True
  DbView _     -> True
  TypeOf _ _   -> True
  TimeOf _ _   -> True
  BenchOf _ _  -> True
  EqExpr _ _   -> True
  ConvExpr _ _ -> True
  Nf _         -> True
  Whnf _       -> True
  IntOf _      -> True
  ChurchOf _   -> True
  Help _       -> True
  _            -> False

replayEcho :: ReplState -> [String] -> IO ReplState
replayEcho = foldM step
  where
    step st line = do
      mst <- handleLine st line
      return (fromMaybe st mst)

applyLoadOutcome :: ReplState -> LoadOutcome -> ReplState
applyLoadOutcome st out = st
  { rsEnv      = loEnv out
  , rsTypeEnv  = loTypeEnv out
  , rsStrategy = fromMaybe (rsStrategy st) (loStrategy out)
  , rsLimit    = fromMaybe (rsLimit st) (loLimit out)
  , rsLang     = fromMaybe (rsLang st) (loLang out)
  , rsFast     = fromMaybe (rsFast st) (loFast out)
  , rsEta      = fromMaybe (rsEta st) (loEta out)
  }

-- 可被解析器重新读取的源语法（与 pretty 的 → 不同）
-- Source syntax that the parser can read back (unlike pretty's →).
sourceExpr :: Expr -> String
sourceExpr e = go 0 e ""
  where
    go :: Int -> Expr -> ShowS
    go _ (Var x)      = showString x
    go p (Lam x b)    = showParen (p > 0)
      (showChar '\\' . showString x . showChar '.' . go 0 b)
    go p (App f a)    = showParen (p > 1)
      (go 1 f . showChar ' ' . go 2 a)

-- 保存时把 Y 编码还原为 rec，避免写出一整段不动点组合子
-- Restore a Y-encoded definition to `rec` form when saving.
sourceDef :: String -> Expr -> String
sourceDef name e = case e of
  App f (Lam x b) | x == name && isFixComb f ->
    "rec " ++ name ++ " = " ++ sourceExpr b
  _ -> name ++ " = " ++ sourceExpr e

writeFileUtf8 :: FilePath -> String -> IO (Either String ())
writeFileUtf8 path text =
  catch (withFile path WriteMode $ \h -> do
           hSetEncoding h utf8
           hPutStr h text
           return (Right ()))
        (\(e :: SomeException) -> return (Left (show e)))

-- ---------------------------------------------------------------------------
-- 命令执行 Command Execution
-- ---------------------------------------------------------------------------
-- 定义在消息中的可读形式；递归定义显示为 rec
-- Human-readable definition text; recursive ones are shown as rec.
prettyDef :: String -> Expr -> String
prettyDef name e = case e of
  App f (Lam x b) | x == name && isFixComb f ->
    "rec " ++ name ++ " = " ++ pretty b
  _ -> name ++ " = " ++ pretty e

-- 求值结果统一输出，供 :eval / :nf / :whnf / :run 复用
-- Shared output for evaluation results.
emitEvalResult :: ReplState -> EvalResult -> Maybe Expr -> IO ()
emitEvalResult st res mExpr = do
  let final   = erFinal res
      termTxt = pretty final
      hintMsg = valueHintMsg final
      steps   = erCount res
      stepZh  = if steps > 0 then "  (" ++ show steps ++ " 步)" else ""
      stepEn  = if steps > 0 then "  (" ++ show steps ++ " steps)" else ""
      textZh  = termTxt ++ stepZh ++ fst hintMsg
      textEn  = termTxt ++ stepEn ++ snd hintMsg
      mtyMsg  = case mExpr of
        Just expr -> either (const ("", "")) prettySchemeMsg
                           (inferScheme (rsTypeEnv st) expr)
        Nothing   -> ("", "")
      trail   = erSteps res
      size    = exprSize final
      cycZh   = if erCycle res then "（检测到重复项，疑似发散）" else ""
      cycEn   = if erCycle res
                  then " (a repeated term was detected; likely divergent)" else ""
      fallback = rsFast st && rsEta st
      fbZh    = if fallback then "（η 已开启，快速模式自动回退到逐步引擎）" else ""
      fbEn    = if fallback then " (eta is on; fast mode fell back to the step engine)" else ""
      fields  = [ "steps"    .= JNum steps
                , "term"     .= JStr termTxt
                , "limitHit" .= JBool (erLimitHit res)
                , "cycle"    .= JBool (erCycle res)
                , "fastFallback" .= JBool fallback
                , "hint"     .= JStr (renderMsg (rsLang st) hintMsg)
                , "hintZh"   .= JStr (fst hintMsg)
                , "hintEn"   .= JStr (snd hintMsg)
                , "strategy" .= JStr (strategyId (rsStrategy st))
                , "eta"      .= JBool (rsEta st)
                , astFieldSized size final
                , dbFieldSized size final
                ]
                ++ redexFields (rsEta st) final
                ++ astTreeFieldsSized size final
                ++ (if mtyMsg == ("", "") then []
                      else [ "type"   .= JStr (renderMsg (rsLang st) mtyMsg)
                           , "typeZh" .= JStr (fst mtyMsg)
                           , "typeEn" .= JStr (snd mtyMsg) ])
                ++ traceFields (erCount res) trail
  if erLimitHit res
    then emitL st "warn"
          (textZh ++ cycZh ++ " —— 已达到 " ++ show (rsLimit st) ++ " 步上限，归约未完成")
          (textEn ++ cycEn ++ " -- step limit " ++ show (rsLimit st)
                   ++ " reached, reduction incomplete")
          (fields ++ ["code" .= JStr "step_limit"])
    else emitL st "result" (textZh ++ cycZh ++ fbZh) (textEn ++ cycEn ++ fbEn) fields
  -- 单独的机器可读事件，方便客户端把“疑似发散”和普通步数上限区分开
  -- A separate machine-readable event lets clients tell suspected divergence
  -- apart from an ordinary step-limit hit.
  when (erCycle res) $
    emitL st "warn"
      "检测到重复的整项，归约很可能发散；可提高 :steps 或改用正规序"
      "A whole term repeated during reduction, so it is likely divergent; raise :steps or use normal order"
      [ "code" .= JStr "cycle_detected"
      , "cycle" .= JBool True
      , "steps" .= JNum (erCount res) ]

-- 快速模式：只有正规形，没有轨迹与精确步数
-- Fast mode: normal form only, with neither a trace nor an exact step count.
fastActive :: ReplState -> Bool
fastActive st = rsFast st && not (rsEta st)

emitFastResult :: ReplState -> Expr -> Maybe Expr -> IO ()
emitFastResult st final mExpr = do
  let termTxt = pretty final
      hintMsg = valueHintMsg final
      size    = exprSize final
      mtyMsg  = case mExpr of
        Just expr -> either (const ("", "")) prettySchemeMsg
                           (inferScheme (rsTypeEnv st) expr)
        Nothing   -> ("", "")
      fields  = [ "term"     .= JStr termTxt
                , "fast"     .= JBool True
                , "limitHit" .= JBool False
                , "hint"     .= JStr (renderMsg (rsLang st) hintMsg)
                , "hintZh"   .= JStr (fst hintMsg)
                , "hintEn"   .= JStr (snd hintMsg)
                , "strategy" .= JStr (strategyId (rsStrategy st))
                , "eta"      .= JBool False
                , astFieldSized size final
                , dbFieldSized size final
                , "redexes"     .= JArr []
                , "redexCount"  .= JNum 0
                ]
                ++ astTreeFieldsSized size final
                ++ (if mtyMsg == ("", "") then []
                      else [ "type"   .= JStr (renderMsg (rsLang st) mtyMsg)
                           , "typeZh" .= JStr (fst mtyMsg)
                           , "typeEn" .= JStr (snd mtyMsg) ])
  emitL st "result"
    (termTxt ++ "  （快速模式，未记录步数）" ++ fst hintMsg)
    (termTxt ++ "  (fast mode, steps not recorded)" ++ snd hintMsg)
    fields

emitFastBudget :: ReplState -> IO ()
emitFastBudget st = emitL st "warn"
  ("快速模式燃料用尽（" ++ show (rsLimit st) ++ " 次 β），已中止；可提高 :steps 或关闭 :fast")
  ("Fast-mode fuel exhausted (" ++ show (rsLimit st) ++ " β); raise :steps or turn :fast off")
  [ "fast" .= JBool True, "limitHit" .= JBool True
  , "code" .= JStr "fast_budget" ]

-- 共享正规化 + 统一的结果输出；Nothing 表示燃料用尽
-- Shared normalization with the shared result reporter; Nothing = out of fuel.
runFastEval :: ReplState -> Expr -> Maybe Expr -> IO ()
runFastEval st e' mExpr =
  case fastNormalForm (rsLimit st) e' of
    Nothing -> emitFastBudget st
    Just nf -> emitFastResult st nf mExpr

-- β 等价结果的统一输出，步进与快速模式共用
-- Shared β-convertibility reporter for the step and fast modes.
emitConv :: ReplState -> Bool -> Bool -> String -> String -> IO ()
emitConv st hit ok la lb = do
  let zh = if hit then "无法判定（达到步数上限）：" ++ la ++ "  ,  " ++ lb
           else if ok then "β 等价：" ++ la ++ "  ,  " ++ lb
           else "不 β 等价：" ++ la ++ "  ,  " ++ lb
      en = if hit then "inconclusive (step limit): " ++ la ++ "  ,  " ++ lb
           else if ok then "beta-equivalent: " ++ la ++ "  ,  " ++ lb
           else "not beta-equivalent: " ++ la ++ "  ,  " ++ lb
  emitL st "conv" zh en
    [ "equal"    .= JBool ok
    , "limitHit" .= JBool hit
    , "left"     .= JStr la
    , "right"    .= JStr lb ]

-- 单调时钟：纳秒精度，Windows 上也有可用的分辨率
-- Monotonic clock: nanosecond resolution, including on Windows.
nowMs :: IO Double
nowMs = do
  n <- getMonotonicTimeNSec
  return (fromIntegral n / 1e6)

cpuMs :: IO a -> IO (a, Double)
cpuMs act = do
  t0 <- nowMs
  x  <- act
  t1 <- nowMs
  return (x, t1 - t0)

-- 强制 pretty，确保整项真正被求值后才结束计时
-- Force pretty so the whole term is evaluated before the timer stops.
forceTerm :: ReplState -> Expr -> IO (EvalResult, Int)
forceTerm st e = do
  let res = evalWith (rsEta st) (rsJson st) (rsLimit st) (rsStrategy st)
                     (expandTop (rsEnv st) e)
  n <- evaluate (length (pretty (erFinal res)))
  return (res, n)

fmtMs :: Double -> String
fmtMs d = showFFloat (Just 3) d ""

-- 仅当定义与预定义值相同时才把它当作预定义项 / treat a name as a prelude entry only when its value still matches
isPreludeDef :: String -> Expr -> Bool
isPreludeDef n e = Map.lookup n initEnv == Just e

typeOfExpr :: ReplState -> Expr -> Maybe String -> IO (Maybe ReplState)
typeOfExpr st expr mAnn = do
  case inferScheme (rsTypeEnv st) expr of
    Left err0 -> do
      let err = scrubTyNames err0
      emitL st "fail" ("无法类型化：" ++ err) ("Cannot type: " ++ err)
        [ "code" .= JStr "type_error" ]
      return (Just st)
    Right sc@(Forall _ rawTy) -> do
      let ty = prettySchemeMsg sc
          ann = mAnn >>= parseTyText
          matches = fmap (\t -> normalizeNames t == normalizeNames rawTy) ann
          annText = fmap (prettyTy . normalizeNames) ann
          noteZh = case matches of
            Just True  -> "；标注匹配"
            Just False -> case annText of
              Just a  -> "；标注不匹配（期望 " ++ a ++ "，实际 "
                          ++ prettyTy (normalizeNames rawTy) ++ "）"
              Nothing -> "；标注不匹配"
            Nothing    -> ""
          noteEn = case matches of
            Just True  -> "; annotation matches"
            Just False -> case annText of
              Just a  -> "; annotation does not match (expected " ++ a
                          ++ ", got " ++ prettyTy (normalizeNames rawTy) ++ ")"
              Nothing -> "; annotation does not match"
            Nothing    -> ""
          tyZh = "类型：" ++ fst ty
          tyEn = "Type: " ++ snd ty
          fields = [ "type"   .= JStr (renderMsg (rsLang st) ty)
                   , "typeZh" .= JStr (fst ty)
                   , "typeEn" .= JStr (snd ty)
                   , "freeVars" .= JArr (map JStr (Set.toList (freeVars expr))) ]
                   ++ [ "annotation" .= JStr a | Just a <- [mAnn] ]
                   ++ [ "matches" .= JBool b | Just b <- [matches] ]
                   ++ [ "expected" .= JStr a | Just a <- [annText] ]
                   ++ [ "actual" .= JStr (prettyTy (normalizeNames rawTy))
                      | Just _ <- [ann] ]
      if rsJson st
        then emitL st "type" (fst ty ++ noteZh) (snd ty ++ noteEn) fields
        else putStrLn (renderMsg (rsLang st) (tyZh ++ noteZh, tyEn ++ noteEn))
      return (Just st)

runCommand :: ReplState -> Command -> IO (Maybe ReplState)
runCommand st (TimeOf n expr) = do
  runs <- forM [1 .. n] $ \_ -> do
    ((res, _), ms) <- cpuMs (forceTerm st expr)
    return (res, ms)
  let samples = map snd runs
      res     = fst (head runs)
      avg     = sum samples / fromIntegral (length samples)
      mn      = minimum samples
      mx      = maximum samples
  emitL st "result"
    (if n == 1
       then "求值耗时 " ++ fmtMs avg ++ " ms（" ++ show (erCount res) ++ " 步）"
       else "求值耗时 " ++ show n ++ " 次：平均 " ++ fmtMs avg
            ++ " ms，最短 " ++ fmtMs mn ++ " ms，最长 " ++ fmtMs mx ++ " ms")
    (if n == 1
       then "Evaluation took " ++ fmtMs avg ++ " ms (" ++ show (erCount res) ++ " steps)"
       else "Evaluation over " ++ show n ++ " runs: average " ++ fmtMs avg
            ++ " ms, min " ++ fmtMs mn ++ " ms, max " ++ fmtMs mx ++ " ms")
    [ "term" .= JStr (pretty (erFinal res))
    , "elapsedMs" .= JDec avg
    , "elapsedMinMs" .= JDec mn
    , "elapsedMaxMs" .= JDec mx
    , "runs" .= JNum n
    , "steps" .= JNum (erCount res)
    , "cycle" .= JBool (erCycle res) ]
  return (Just st)
runCommand st (BenchOf n expr) = do
  samples <- forM [1 .. n] $ \_ -> do
    ((_, _), ms) <- cpuMs (forceTerm st expr)
    return ms
  let total = sum samples
      avg   = total / fromIntegral n
      sorted = sort samples
      median = if odd n
                 then sorted !! (n `div` 2)
                 else (sorted !! (n `div` 2 - 1) + sorted !! (n `div` 2)) / 2
      variance = sum [ (x - avg) ^ (2 :: Int) | x <- samples ] / fromIntegral n
      stddev = sqrt variance
  emitL st "result"
    ("基准测试 " ++ show n ++ " 次：平均 " ++ fmtMs avg ++ " ms，中位 "
      ++ fmtMs median ++ " ms，标准差 " ++ fmtMs stddev
      ++ " ms，范围 " ++ fmtMs (minimum samples) ++ "–" ++ fmtMs (maximum samples) ++ " ms")
    ("Benchmark " ++ show n ++ " runs: average " ++ fmtMs avg ++ " ms, median "
      ++ fmtMs median ++ " ms, stddev " ++ fmtMs stddev
      ++ " ms, range " ++ fmtMs (minimum samples) ++ "–" ++ fmtMs (maximum samples) ++ " ms")
    [ "runs" .= JNum n
    , "elapsedMs" .= JDec avg
    , "elapsedTotalMs" .= JDec total
    , "elapsedMedianMs" .= JDec median
    , "elapsedStddevMs" .= JDec stddev
    , "elapsedMinMs" .= JDec (minimum samples)
    , "elapsedMaxMs" .= JDec (maximum samples) ]
  return (Just st)
runCommand st (Eval expr)
  | fastActive st = do
      runFastEval st (expandTop (rsEnv st) expr) (Just expr)
      return (Just st)
  | otherwise = do
      let e'  = expandTop (rsEnv st) expr
          res = evalWith (rsEta st) (rsJson st) (rsLimit st) (rsStrategy st) e'
      emitEvalResult st res (Just expr)
      return (Just st)
runCommand st (Define var expr) = do
  let expr' = expandTop (rsEnv st) expr
      env'  = Map.insert var expr' (rsEnv st)
      (tenv', mtyMsg) = case inferScheme (rsTypeEnv st) expr of
        Right sc -> (Map.insert var sc (rsTypeEnv st), Just (prettySchemeMsg sc))
        Left _   -> (Map.delete var (rsTypeEnv st), Nothing)
      fields = [ "name"  .= JStr var
               , "value" .= JStr (pretty expr') ]
               ++ [ "type" .= JStr (renderMsg (rsLang st) ty) | Just ty <- [mtyMsg] ]
               ++ [ "typeZh" .= JStr (fst ty) | Just ty <- [mtyMsg] ]
               ++ [ "typeEn" .= JStr (snd ty) | Just ty <- [mtyMsg] ]
  emitL st "define"
    ("已定义 " ++ var ++ " = " ++ pretty expr')
    ("defined " ++ var ++ " = " ++ pretty expr') fields
  return (Just st { rsEnv = env', rsTypeEnv = tenv' })
runCommand st (DefineRec var expr) = do
  let body  = expandTop (Map.delete var (rsEnv st)) expr
      expr' = App zComb (Lam var body)
      env'  = Map.insert var expr' (rsEnv st)
      -- 不动点编码无简单类型，清掉可能残留的旧方案
      -- A fixed-point definition has no simple type; drop any stale scheme.
      tenv' = Map.delete var (rsTypeEnv st)
  emitL st "define"
    ("已定义递归 " ++ var ++ " = " ++ pretty body)
    ("defined recursive " ++ var ++ " = " ++ pretty body)
    [ "name"  .= JStr var
    , "value" .= JStr (pretty expr')
    , "rec"   .= JBool True ]
  return (Just st { rsEnv = env', rsTypeEnv = tenv' })
runCommand st (LoadFile path) = do
  res <- loadDefinitionsFromFile (rsMaxTerm st) (rsEnv st) (rsTypeEnv st) path
  case res of
    Left err -> do
      emitL st "fail" ("文件加载错误: " ++ err) ("File load error: " ++ err)
        [ "code" .= JStr "load_error" ]
      return (Just st)
    Right out -> do
      let st' = applyLoadOutcome st out
      forM_ (reverse (loOk out)) $ \(name, ex) ->
        emitL st' "define"
          ("已定义 " ++ prettyDef name ex)
          ("defined " ++ prettyDef name ex)
          [ "name" .= JStr name
          , "value" .= JStr (pretty ex) ]
      forM_ (reverse (loFail out)) $ \(n, line, msg, code) ->
        emitL st' "error"
          ("第 " ++ show n ++ " 行: " ++ shorten 60 line
            ++ " — " ++ fst msg)
          ("Line " ++ show n ++ ": " ++ shorten 60 line
            ++ " -- " ++ snd msg)
          [ "line" .= JNum n, "code" .= JStr code ]
      emitL st' "info"
        ("成功加载 " ++ show (length (loOk out)) ++ " 个定义，失败 " ++ show (length (loFail out)) ++ " 行")
        ("Loaded " ++ show (length (loOk out)) ++ " definitions, " ++ show (length (loFail out)) ++ " lines failed")
        [ "loaded" .= JNum (length (loOk out))
        , "failed" .= JNum (length (loFail out)) ]
      forM_ (loStrategy out) $ \s -> emitL st' "info"
        ("求值策略：" ++ strategyLabel s) ("Strategy: " ++ strategyLabelEn s)
        [ "strategy" .= JStr (strategyId s) ]
      forM_ (loLimit out) $ \n -> emitL st' "info"
        ("归约步数上限：" ++ show n) ("Reduction step limit: " ++ show n)
        [ "limit" .= JNum n ]
      forM_ (loLang out) $ \l -> emitL st' "info"
        "语言已切换。" "Language switched."
        [ "lang" .= JStr (langId l) ]
      forM_ (loFast out) $ \on -> emitL st' "info"
        (if on then "快速模式：开启" else "快速模式：关闭")
        (if on then "Fast mode: on" else "Fast mode: off")
        [ "fast" .= JBool on ]
      forM_ (loEta out) $ \on -> emitL st' "info"
        (if on then "η 归约：开启" else "η 归约：关闭")
        (if on then "Eta reduction: on" else "Eta reduction: off")
        [ "eta" .= JBool on ]
      stAfter <- replayEcho st' (loEcho out)
      return (Just stAfter { rsLastFile = Just path })
runCommand st (SaveFile path) = do
  let defs = [ sourceDef n e
             | (n, e) <- Map.toList (rsEnv st), not (isPreludeDef n e) ]
      body = unlines defs
  res <- writeFileUtf8 path body
  case res of
    Left err -> emitL st "fail"
      ("保存失败: " ++ err) ("Save failed: " ++ err) []
    Right () -> emitL st "info"
      ("已保存 " ++ show (length defs) ++ " 个定义到 " ++ path)
      ("Saved " ++ show (length defs) ++ " definitions to " ++ path)
      [ "file" .= JStr path, "saved" .= JNum (length defs) ]
  return (Just st)
runCommand st ShowEnv = do
  -- 预定义项的推断类型往往很长，环境面板只显示用户定义的类型
  -- Prelude schemes are long; show types for user definitions only.
  let tyOf n e
        | isPreludeDef n e = ("", "")
        | otherwise = maybe ("", "") prettySchemeMsg (Map.lookup n (rsTypeEnv st))
      rows = [(n, pretty e, tyOf n e) | (n, e) <- Map.toList (rsEnv st)]
  if null rows
    then emitL st "info" "当前环境为空。" "The environment is empty." []
    else if rsJson st
      then emit st "env" "" [ "rows" .= JArr
             [ JObj [ "name" .= JStr a, "value" .= JStr b
                    , "type" .= JStr (renderMsg (rsLang st) ty)
                    , "typeZh" .= JStr (fst ty), "typeEn" .= JStr (snd ty) ]
             | (a, b, ty) <- rows ] ]
      else putStr (renderTable (rsLang st) [(a, b, renderMsg (rsLang st) ty) | (a, b, ty) <- rows])
             >> hFlush stdout
  return (Just st)
runCommand st (DeleteDef name)
  | Map.member name (rsEnv st) = do
      emitL st "info" ("已删除 " ++ name) ("Deleted " ++ name) []
      return $ Just st { rsEnv = Map.delete name (rsEnv st)
                       , rsTypeEnv = Map.delete name (rsTypeEnv st) }
  | otherwise = do
      emitL st "fail" ("未找到定义：" ++ name) ("Definition not found: " ++ name) []
      return (Just st)
runCommand st ResetEnv = do
  emitL st "info" "环境已重置为预定义状态。" "Environment reset to the prelude." []
  return $ Just st { rsEnv = initEnv, rsTypeEnv = initTypeEnv
                   , rsCurrent = Nothing, rsTrail = [] }
runCommand st (SetStrategy s) = do
  emitL st "info"
    ("求值策略：" ++ strategyLabel s ++ "（" ++ strategyId s ++ "）")
    ("Strategy: " ++ strategyLabelEn s ++ " (" ++ strategyId s ++ ")")
    [ "strategy" .= JStr (strategyId s) ]
  return $ Just st { rsStrategy = s }
runCommand st (SetSteps n) = do
  emitL st "info" ("归约步数上限：" ++ show n) ("Reduction step limit: " ++ show n)
    [ "limit" .= JNum n ]
  return $ Just st { rsLimit = n }
runCommand st (SetEta on) = do
  emitL st "info"
    ("η 归约：" ++ if on then "开启" else "关闭")
    ("Eta reduction: " ++ if on then "on" else "off")
    [ "eta" .= JBool on ]
  return $ Just st { rsEta = on }
runCommand st (SetFast on) = do
  emitL st "info"
    (if on
       then "快速模式：开启（共享正规化；不记录步数与轨迹，η 开启时自动回退）"
       else "快速模式：关闭（逐步归约）")
    (if on
       then "Fast mode: on (shared normalization; no steps or trace, falls back while eta is on)"
       else "Fast mode: off (step-by-step reduction)")
    [ "fast" .= JBool on ]
  return $ Just st { rsFast = on }
runCommand st (Trace expr) = do
  let e'  = expandTop (rsEnv st) expr
      res = evalTraceWith (rsEta st) (rsLimit st) (rsStrategy st) e'
      trail = erSteps res
      fields = [ "final"    .= JStr (pretty (erFinal res))
               , "steps"    .= JNum (erCount res)
               , "limitHit" .= JBool (erLimitHit res)
               , "eta"      .= JBool (rsEta st)
               , "strategy" .= JStr (strategyId (rsStrategy st)) ]
               ++ traceFields (erCount res) trail
  if rsJson st
    then emit st "trace" "" fields
    else do
      putStrLn $ say st
        ("归约轨迹（" ++ strategyLabel (rsStrategy st) ++ "，共 " ++ show (erCount res) ++ " 步）")
        ("Reduction trace (" ++ strategyLabelEn (rsStrategy st) ++ ", " ++ show (erCount res) ++ " steps)")
      putStrLn $ "  0. " ++ pretty e'
      forM_ trail $ \s -> do
        putStrLn $ "  " ++ show (tsIndex s) ++ ". " ++ tsNote s
        putStrLn $ "       " ++ pretty (tsAfter s)
      when (erCount res > length trail || traceClipped trail) $ putStrLn (say st
        "  ⚠ 轨迹较长，JSON 中只保留前 500 步并截断长项"
        "  ⚠ Long trace: JSON keeps the first 500 steps and clips long terms")
      when (erLimitHit res) $ putStrLn (say st
        "  ⚠ 已达到步数上限，归约未完成"
        "  ⚠ Step limit reached, reduction incomplete")
  return (Just st)
runCommand st (Ast expr) = do
  let e'   = expandTop (rsEnv st) expr
      size = exprSize e'
  if rsJson st
    then emit st "ast" "" (treeFieldSized size e' : astTreeFieldsSized size e')
    else if size <= astBudget
           then putStrLn (unlines (treeLines e'))
           else emitL st "warn"
                  "项过大，已省略语法树（节点上限 400）。"
                  "Term too large; AST omitted (400-node limit)." []
  return (Just st)
runCommand st (DbView expr) = do
  let e'      = expandTop (rsEnv st) expr
      size    = exprSize e'
      dbTxt   = if size <= astBudget then deBruijnView e'
                                     else shorten 1000 (deBruijnView e')
      termTxt = if size <= astBudget then pretty e'
                                     else shorten 4000 (pretty e')
  emit st "db" dbTxt
    ([ astFieldSized size e' ]
     ++ astTreeFieldsSized size e'
     ++ [ "term" .= JStr termTxt ])
  return (Just st)
runCommand st (TypeOf (Var name) _)
  -- 已定义但无法在简单类型系统中类型化的名字（如 Y、rec 定义）不应被当成自由变量
  -- A defined name with no simple type (Y, rec definitions) must not be treated
  -- as a free variable.
  | Map.member name (rsEnv st), Map.notMember name (rsTypeEnv st) = do
      emitL st "fail"
        ("无法类型化：" ++ name ++ " 在简单类型系统中没有类型")
        ("Cannot type: " ++ name ++ " has no simple type")
        [ "code" .= JStr "type_error" ]
      return (Just st)
runCommand st (TypeOf expr mAnn)
  -- 表达式中引用了已定义但没有简单类型的名字时，不能把它们当自由变量推断
  -- A defined name with no simple type must not be inferred as a free variable.
  | not (null untyped) = do
      emitL st "fail"
        ("无法类型化：" ++ intercalate "、" untyped ++ " 在简单类型系统中没有类型")
        ("Cannot type: " ++ intercalate ", " untyped ++ " has/have no simple type")
        [ "code" .= JStr "type_error" ]
      return (Just st)
  | otherwise = typeOfExpr st expr mAnn
  where
    untyped = [ n | n <- Set.toList (freeVars expr)
                  , Map.member n (rsEnv st)
                  , Map.notMember n (rsTypeEnv st) ]

runCommand st (EqExpr a b) = do
  let a' = expandTop (rsEnv st) a
      b' = expandTop (rsEnv st) b
      ok = alphaEq a' b'
      zh = (if ok then "α 等价：" else "不 α 等价：") ++ pretty a' ++ "  ,  " ++ pretty b'
      en = (if ok then "alpha-equivalent: " else "not alpha-equivalent: ")
             ++ pretty a' ++ "  ,  " ++ pretty b'
  emitL st "eq" zh en
    [ "equal" .= JBool ok
    , "left"  .= JStr (pretty a')
    , "right" .= JStr (pretty b') ]
  return (Just st)
runCommand st (ConvExpr a b)
  | fastActive st = do
      let a' = expandTop (rsEnv st) a
          b' = expandTop (rsEnv st) b
      case (fastNormalForm (rsLimit st) a', fastNormalForm (rsLimit st) b') of
        (Just na, Just nb) ->
          emitConv st False (alphaEq na nb) (pretty na) (pretty nb)
        _ -> emitConv st True False (pretty a') (pretty b')
      return (Just st)
  | otherwise = do
      let a' = expandTop (rsEnv st) a
          b' = expandTop (rsEnv st) b
          ra = evalWith (rsEta st) False (rsLimit st) Normal a'
          rb = evalWith (rsEta st) False (rsLimit st) Normal b'
          hit = erLimitHit ra || erLimitHit rb
          ok = not hit && alphaEq (erFinal ra) (erFinal rb)
      emitConv st hit ok (pretty (erFinal ra)) (pretty (erFinal rb))
      return (Just st)
runCommand st (Nf expr)
  | fastActive st = do
      runFastEval st (expandTop (rsEnv st) expr) (Just expr)
      return (Just st)
  | otherwise = do
      let e'  = expandTop (rsEnv st) expr
          res = evalTraceWith (rsEta st) (rsLimit st) Normal e'
      emitEvalResult st res (Just expr)
      return (Just st)
runCommand st (Whnf expr) = do
  let e'  = expandTop (rsEnv st) expr
      res = evalWHNF (rsEta st) (rsLimit st) (rsStrategy st) e'
  emitEvalResult st res (Just expr)
  return (Just st)
runCommand st (IntOf expr)
  | fastActive st = do
      case fastNormalForm (rsLimit st) (expandTop (rsEnv st) expr) of
        Nothing -> emitFastBudget st
        Just final -> case isChurchNumeral final of
          Just n -> emit st "int" (show n)
            [ "value" .= JNum (fromIntegral n)
            , "term"  .= JStr (pretty final)
            , "fast"  .= JBool True ]
          Nothing -> emitL st "fail"
            ("不是邱奇数：" ++ pretty final)
            ("Not a Church numeral: " ++ pretty final) []
      return (Just st)
  | otherwise = do
      let e'  = expandTop (rsEnv st) expr
          res = evalWith (rsEta st) False (rsLimit st) Normal e'
          final = erFinal res
      case isChurchNumeral final of
        Just n | not (erLimitHit res) ->
          emit st "int" (show n)
            [ "value" .= JNum (fromIntegral n)
            , "term"  .= JStr (pretty final) ]
        Just _ -> emitL st "fail"
          "归约达到步数上限，无法确认邱奇数"
          "Step limit reached; cannot confirm a Church numeral" []
        Nothing -> emitL st "fail"
          ("不是邱奇数：" ++ pretty final)
          ("Not a Church numeral: " ++ pretty final) []
      return (Just st)
runCommand st (ChurchOf n) = do
  let e' = churchNumeral n
      ty = either (const ("", "")) prettySchemeMsg (inferScheme (rsTypeEnv st) e')
  emit st "church" (pretty e')
    ([ "value" .= JNum (fromIntegral n)
     , "term"  .= JStr (pretty e') ]
     ++ (if ty == ("", "") then []
           else [ "type"   .= JStr (renderMsg (rsLang st) ty)
                , "typeZh" .= JStr (fst ty)
                , "typeEn" .= JStr (snd ty) ]))
  return (Just st)
runCommand st (Begin expr) = do
  let e' = expandTop (rsEnv st) expr
      n  = redexCount (rsEta st) e'
      fields = [ "steps"    .= JNum 0
               , "term"     .= JStr (pretty e')
               , "strategy" .= JStr (strategyId (rsStrategy st))
               , "eta"      .= JBool (rsEta st) ]
               ++ redexFields (rsEta st) e'
  let hintTxt = say st
        ("（" ++ show n ++ " 个可归约位置；:step 按策略归约，:step <序号> 任选）")
        (" (" ++ show n ++ " redex(es); :step follows the strategy, :step <n> picks one)")
  if rsJson st
    then emit st "term" (pretty e') fields
    else putStrLn (say st
      ("开始手动归约：" ++ pretty e' ++ "\n  用 :step 归约一步，:run 归约到底，:end 结束。")
      ("Manual reduction started: " ++ pretty e' ++ "\n  Use :step to reduce one step, :run to finish, :end to stop.")
      ++ "\n  " ++ hintTxt)
  return $ Just st { rsCurrent = Just e', rsTrail = [e'] }
runCommand st (StepCmd mi) = case rsCurrent st of
  Nothing -> do
    emitL st "fail"
      "当前没有进行中的归约，先用 :begin <表达式> 开始。"
      "No reduction in progress; start one with :begin <expr>." []
    return (Just st)
  Just e ->
    let mstep = case mi of
          Nothing -> stepFor (rsEta st) (rsStrategy st) e
          Just i  -> stepAtIndex (rsEta st) i e
    in case mstep of
      Nothing -> do
        let (zh, en) = case mi of
              Just i  ->
                ( "没有第 " ++ show i ++ " 个 redex（当前 " ++ show (redexCount (rsEta st) e) ++ " 个）。"
                , "No redex #" ++ show i ++ " (there are " ++ show (redexCount (rsEta st) e) ++ ")." )
              Nothing ->
                ( "已是正规形：" ++ pretty e
                , "Already in normal form: " ++ pretty e )
        emitL st (if mi == Nothing then "info" else "fail") zh en []
        return (Just st)
      Just (StepOut whole red) -> do
        let stepNo = maybe "" (\i -> " #" ++ show i) mi
            trail' = whole : rsTrail st
        emit st "step" (pretty whole)
          ([ "rule"     .= JStr (redRule red)
           , "note"     .= JStr (redNote red)
           , "before"   .= JStr (pretty e)
           , "term"     .= JStr (pretty whole)
           , "redex"    .= JStr stepNo
           , "step"     .= JNum (length trail' - 1)
           , "canStepBack" .= JBool True
           , "eta"      .= JBool (rsEta st) ]
           ++ redexFields (rsEta st) whole)
        return $ Just st { rsCurrent = Just whole, rsTrail = trail' }
runCommand st BackCmd = case rsTrail st of
  (_:prev:_) -> do
    let n = length (rsTrail st) - 1
    emit st "step" (pretty prev)
      [ "term" .= JStr (pretty prev)
      , "step" .= JNum (n - 1)
      , "canStepBack" .= JBool (n - 1 > 0)
      , "back" .= JBool True ]
    return $ Just st { rsCurrent = Just prev, rsTrail = prev : drop 2 (rsTrail st) }
  [_] -> do
    emitL st "info" "已经回到起点。" "Already at the start." []
    return (Just st)
  _ -> do
    emitL st "fail"
      "当前没有进行中的归约，先用 :begin <表达式> 开始。"
      "No reduction in progress; start one with :begin <expr>." []
    return (Just st)
runCommand st (GotoCmd n) =
  let trail = rsTrail st
      steps = length trail - 1
      pos = steps - n
  in if null trail
       then do
         emitL st "fail"
           "当前没有进行中的归约，先用 :begin <表达式> 开始。"
           "No reduction in progress; start one with :begin <expr>." []
         return (Just st)
       else if n > steps || pos < 0 || pos >= length trail
         then do
           emitL st "fail"
             ("步数超出范围：当前共 " ++ show steps ++ " 步（0-" ++ show steps ++ "）。")
             ("Step out of range: there are " ++ show steps ++ " step(s) (0-" ++ show steps ++ ").")
             [ "code" .= JStr "step_out_of_range" ]
           return (Just st)
         else do
           let e = trail !! pos
           emit st "step" (pretty e)
             [ "term" .= JStr (pretty e)
             , "step" .= JNum n
             , "canStepBack" .= JBool (n > 0)
             , "goto" .= JBool True ]
           return $ Just st { rsCurrent = Just e, rsTrail = drop pos trail }
runCommand st (ShowDef name) =
  case Map.lookup name (rsEnv st) of
    Nothing -> do
      emitL st "fail" ("未找到定义：" ++ name) ("Definition not found: " ++ name)
        [ "code" .= JStr "unknown_name" ]
      return (Just st)
    Just e -> do
      let ty = if isPreludeDef name e then ("", "")
               else maybe ("", "") prettySchemeMsg (Map.lookup name (rsTypeEnv st))
      emit st "define" (prettyDef name e)
        ([ "name" .= JStr name, "value" .= JStr (pretty e) ]
         ++ (if ty == ("", "") then []
               else [ "type" .= JStr (renderMsg (rsLang st) ty)
                    , "typeZh" .= JStr (fst ty)
                    , "typeEn" .= JStr (snd ty) ]))
      return (Just st)
runCommand st (SearchEnv needle) = do
  let low = map toLower needle
      hits = [ (n, e) | (n, e) <- Map.toList (rsEnv st)
                       , low `isInfixOf` map toLower n ]
  if null hits
    then emitL st "info"
      ("没有匹配 " ++ show needle ++ " 的名字。")
      ("No names match " ++ show needle ++ ".") []
    else if rsJson st
      then emit st "search" "" [ "rows" .= JArr
             [ JObj [ "name" .= JStr n, "value" .= JStr (pretty e) ]
             | (n, e) <- hits ] ]
      else putStr (renderTable (rsLang st)
        [ (n, pretty e, "") | (n, e) <- hits ]) >> hFlush stdout
  return (Just st)
runCommand st ReloadCmd =
  case rsLastFile st of
    Nothing -> do
      emitL st "fail"
        "还没有加载过文件；先用 :load <文件>。"
        "No file has been loaded yet; use :load <file> first." []
      return (Just st)
    Just path -> runCommand st (LoadFile path)
runCommand st (EditFile mpath) =
  case mpath <|> rsLastFile st of
    Nothing -> do
      emitL st "fail" "缺少文件路径。" "Missing file path." []
      return (Just st)
    Just path -> do
      ed <- lookupEnv "EDITOR"
      let editor = fromMaybe (if os == "mingw32" then "notepad" else "vi") ed
      r <- catch (Right <$> callProcess editor [path])
                 (\(e :: SomeException) -> return (Left (show e)))
      case r of
        Left err -> emitL st "fail"
          ("无法启动编辑器 " ++ editor ++ "：" ++ err)
          ("Could not start editor " ++ editor ++ ": " ++ err) []
        Right () -> emitL st "info"
          ("已用 " ++ editor ++ " 打开 " ++ path ++ "；用 :reload 重新加载。")
          ("Opened " ++ path ++ " with " ++ editor ++ "; use :reload to load it again.")
          [ "file" .= JStr path, "editor" .= JStr editor ]
      return (Just st)
runCommand st RunCmd = case rsCurrent st of
  Nothing -> do
    emitL st "fail"
      "当前没有进行中的归约，先用 :begin <表达式> 开始。"
      "No reduction in progress; start one with :begin <expr>." []
    return (Just st)
  Just e -> do
    let res = evalTraceWith (rsEta st) (rsLimit st) (rsStrategy st) e
    emitEvalResult st res Nothing
    return $ Just st { rsCurrent = Nothing, rsTrail = [] }
runCommand st EndCmd = do
  emitL st "info" "已结束手动归约。" "Manual reduction ended." []
  return $ Just st { rsCurrent = Nothing, rsTrail = [] }
runCommand st (SetLang l) = do
  emitL st "info" "语言已切换。" "Language switched."
    [ "lang" .= JStr (langId l) ]
  return $ Just st { rsLang = l }
runCommand st (Help (Just topic)) = do
  let key = case trim topic of
              t | ":" `isPrefixOf` t -> takeWhile (not . isSpace) t
              t -> ":" ++ takeWhile (not . isSpace) t
  case lookup key knownCommands of
    Nothing -> emitL st "fail"
      ("未知命令 " ++ key ++ "，输入 :help 查看全部命令")
      ("Unknown command " ++ key ++ "; type :help for the full list")
      [ "code" .= JStr "unknown_command" ]
    Just (zh, en) -> do
      let usage = fromMaybe ("参见 :help", "see :help") (lookup key commandUsage)
      if rsJson st
        then emitL st "help"
          ("  " ++ key ++ " — " ++ zh ++ "\n  用法：" ++ fst usage)
          ("  " ++ key ++ " -- " ++ en ++ "\n  Usage: " ++ snd usage)
          [ "command" .= JStr key ]
        else putStrLn (renderMsg (rsLang st)
          ("  " ++ key ++ " — " ++ zh ++ "\n  用法：" ++ fst usage
           , "  " ++ key ++ " -- " ++ en ++ "\n  Usage: " ++ snd usage))
  return (Just st)
runCommand st (Help Nothing) = do
  if rsJson st
    then emitL st "help" (helpMessage Zh) (helpMessage En) []
    else putStrLn (helpMessage (rsLang st))
  return (Just st)
runCommand _ Quit = return Nothing

-- :help <命令> 的用法说明 / usage lines for :help <cmd>.
commandUsage :: [(String, Msg)]
commandUsage =
  [ (":help",  (":help 或 :help <命令>", ":help or :help <cmd>"))
  , (":load",  (":load <文件.lam>", ":load <file.lam>"))
  , (":save",  (":save <文件.lam>", ":save <file.lam>"))
  , (":let",   (":let <名字> = <表达式>；:let rec 支持递归",
                ":let <name> = <expr>; :let rec allows recursion"))
  , (":env",   (":env", ":env"))
  , (":del",   (":del <名字>", ":del <name>"))
  , (":reset", (":reset", ":reset"))
  , (":strategy", (":strategy applicative|normal|cbn|cbv",
                   ":strategy applicative|normal|cbn|cbv"))
  , (":steps", (":steps <正整数>", ":steps <positive integer>"))
  , (":eta",   (":eta on|off", ":eta on|off"))
  , (":fast",  (":fast on|off", ":fast on|off"))
  , (":trace", (":trace <表达式>", ":trace <expr>"))
  , (":ast",   (":ast <表达式>", ":ast <expr>"))
  , (":db",    (":db <表达式>", ":db <expr>"))
  , (":type",  (":type <表达式> [: <类型>]", ":type <expr> [: <type>]"))
  , (":time",  (":time [次数] <表达式>", ":time [runs] <expr>"))
  , (":bench", (":bench <1-1000> <表达式>", ":bench <1-1000> <expr>"))
  , (":eq",    (":eq <表达式> , <表达式>", ":eq <expr> , <expr>"))
  , (":conv",  (":conv <表达式> , <表达式>", ":conv <expr> , <expr>"))
  , (":nf",    (":nf <表达式>", ":nf <expr>"))
  , (":whnf",  (":whnf <表达式>", ":whnf <expr>"))
  , (":int",   (":int <表达式>", ":int <expr>"))
  , (":church", (":church <0-9999>", ":church <0-9999>"))
  , (":begin", (":begin <表达式>", ":begin <expr>"))
  , (":step",  (":step 或 :step <序号>", ":step or :step <index>"))
  , (":run",   (":run", ":run"))
  , (":end",   (":end", ":end"))
  , (":back",  (":back", ":back"))
  , (":goto",  (":goto <0-已走步数>", ":goto <0-currentStep>"))
  , (":def",   (":def <名字>", ":def <name>"))
  , (":search", (":search <子串>", ":search <substring>"))
  , (":reload", (":reload", ":reload"))
  , (":edit",  (":edit [文件]", ":edit [file]"))
  , (":lang",  (":lang zh|en|both", ":lang zh|en|both"))
  , (":q",     (":q", ":q"))
  ]

strategyLabelEn :: Strategy -> String
strategyLabelEn Applicative = "applicative order (leftmost-innermost)"
strategyLabelEn Normal      = "normal order (leftmost-outermost)"
strategyLabelEn CallByName  = "call-by-name (weak)"
strategyLabelEn CallByValue = "call-by-value (weak)"

say :: ReplState -> String -> String -> String
say st zh en = renderMsg (rsLang st) (zh, en)

prettySchemeMsg :: Scheme -> Msg
prettySchemeMsg (Forall vars t0) =
  let base = prettyTy (normalizeNames t0)
      poly = if null vars then ("", "") else ("（多态）", " (polymorphic)")
  in (base ++ fst poly, base ++ snd poly)

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
      , ("  ./extension [选项] [文件...]", "  ./extension [options] [file...]")
      , ("", "")
      , ("选项:", "Options:")
      , ("  -h, --help       显示此帮助信息并退出", "  -h, --help       show this help and exit")
      , ("  -v, --version    显示版本号并退出", "  -v, --version    print the version and exit")
      , ("     --batch       批处理模式（从 stdin 逐行读取，供 Web 后端使用）"
        , "     --batch       batch mode (one command per stdin line, used by the web backend)")
      , ("     --json        以 JSON Lines 输出，便于程序消费"
        , "     --json        emit JSON Lines for programmatic use")
      , ("     --lang <值>   输出语言：zh / en / both（默认 both；也接受 --lang=zh）"
        , "     --lang <v>    output language: zh / en / both (default both; --lang=zh also works)")
      , ("     --timeout <秒> 单条命令的墙钟上限，0 表示不限制（默认 0）"
        , "     --timeout <s> wall-clock limit per command; 0 disables it (default 0)")
      , ("  -e, --eval <表达式> 执行一条命令后退出，可重复使用"
        , "  -e, --eval <expr> run one command and exit; may be repeated")
      , ("     --check       只加载并校验 .lam 文件，成功退出码 0，失败 1"
        , "     --check       load and validate .lam files; exit 0 on success, 1 on failure")
      , ("     --strategy <名称> 初始策略：applicative / normal / cbn / cbv"
        , "     --strategy <name> initial strategy: applicative / normal / cbn / cbv")
      , ("     --steps <n>   初始归约步数上限（快速模式下为 β 燃料）"
        , "     --steps <n>   initial step limit (β fuel in fast mode)")
      , ("     --eta[=on|off]  初始 η 归约开关", "     --eta[=on|off]  initial eta reduction switch")
      , ("     --fast[=on|off] 初始快速模式开关", "     --fast[=on|off] initial fast-mode switch")
      , ("     --max-term-size <n> 拒绝超过 n 个节点的输入表达式"
        , "     --max-term-size <n> reject input expressions with more than n nodes")
      , ("", "")
      , ("参数:", "Arguments:")
      , ("  文件              启动时按顺序加载多个文件", "  files             loaded in order at startup")
      , ("                    每行 `name = expr`；支持 -- 注释、圆括号/方括号未闭合时续行"
        , "                    one `name = expr` per line; -- comments; open parentheses/brackets continue the line")
      , ("                    也可包含 :strategy / :steps / :lang / :fast / :eta / :del / :reset 及查询命令"
        , "                    :strategy / :steps / :lang / :fast / :eta / :del / :reset and queries")
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
      , ("  - 定义变量：name = expr；递归定义：rec name = expr 或 :let rec name = expr"
        , "  - definition: name = expr; recursion: rec name = expr or :let rec name = expr")
      , ("  - 抽象: λx.body、λx → body、\\x -> body；多个参数可写为 λx y.body"
        , "  - abstraction: λx.body, λx → body or \\x -> body; multiple params as λx y.body")
      , ("  - let: let x = e1; y = e2 in e3；if c then t else f；列表 [a, b, c]；标注 (e : T)"
        , "  - let: let x = e1; y = e2 in e3; if c then t else f; lists [a, b, c]; annotation (e : T)")
      , ("  - 行尾 -- / # 注释；REPL 中行尾 \\ 或圆括号/方括号未闭合会续行"
        , "  - trailing -- / # comments; a trailing \\ or open parentheses/brackets continue the REPL line")
      , ("  - 应用: f a，左结合", "  - application: f a, left-associative")
      , ("  - 括号: (expr)", "  - grouping: (expr)")
      , ("  - 邱奇数: 直接输入数字 (0-9999) 自动转为 Church 编码"
        , "  - Church numerals: a literal number (0-9999) becomes its Church encoding")
      , ("  - :eq / :conv 用逗号分隔两个表达式，例如 :eq \\a.a , \\b.b"
        , "  - :eq / :conv take two expressions separated by a comma, e.g. :eq \\a.a , \\b.b")
      , ("", "")
      , ("预定义环境:", "Prelude:")
      , ("  TRUE FALSE NOT AND OR XOR NAND IF I K S B C W"
        , "  TRUE FALSE NOT AND OR XOR NAND IF I K S B C W")
      , ("  ZERO ONE TWO THREE SUCC PLUS MULT EXP PRED SUB ISZERO LEQ EQ"
        , "  ZERO ONE TWO THREE SUCC PLUS MULT EXP PRED SUB ISZERO LEQ EQ")
      , ("  MIN MAX DIV MOD PAIR FST SND NIL CONS HEAD TAIL"
        , "  MIN MAX DIV MOD PAIR FST SND NIL CONS HEAD TAIL")
      , ("  APPEND REV LENGTH MAP FILTER FOLD RANGE ZIP Y"
        , "  APPEND REV LENGTH MAP FILTER FOLD RANGE ZIP Y")
      ]

-- ---------------------------------------------------------------------------
-- REPL
-- ---------------------------------------------------------------------------
-- 墙钟超时：0 表示不限制；web 后端另有进程级超时
-- Wall-clock timeout; 0 disables it. The web backend also has a process timeout.
runWithTimeout :: ReplState -> IO (Maybe ReplState) -> IO (Maybe ReplState)
runWithTimeout st act
  | rsTimeout st <= 0 = act
  | otherwise = do
      r <- timeout (rsTimeout st * 1000000) act
      case r of
        Just x  -> return x
        Nothing -> do
          emitL st "warn"
            ("命令超时（超过 " ++ show (rsTimeout st) ++ " 秒），已中止")
            ("Command timed out after " ++ show (rsTimeout st) ++ " s")
            [ "code" .= JStr "timeout" ]
          return (Just st)

-- 收集命令里的表达式，统一在求值前检查宏展开燃料
-- Collect a command's expressions so expansion fuel is checked in one place.
commandExprs :: Command -> [Expr]
commandExprs c = case c of
  Eval e        -> [e]
  Define _ e    -> [e]
  DefineRec _ e -> [e]
  Trace e       -> [e]
  Ast e         -> [e]
  DbView e      -> [e]
  TypeOf e _    -> [e]
  TimeOf _ e    -> [e]
  BenchOf _ e   -> [e]
  EqExpr a b    -> [a, b]
  ConvExpr a b  -> [a, b]
  Nf e          -> [e]
  Whnf e        -> [e]
  IntOf e       -> [e]
  Begin e       -> [e]
  _             -> []

handleLine :: ReplState -> String -> IO (Maybe ReplState)
handleLine st line =
  case parseCommand line of
    Left err -> do
      emitL st "error"
        ( "解析错误: 第 " ++ show (pePos err) ++ " 列 — " ++ fst (peMsg err))
        ( "Parse error at column " ++ show (pePos err) ++ " -- " ++ snd (peMsg err))
        [ "pos" .= JNum (pePos err), "code" .= JStr "parse_error" ]
      return (Just st)
    Right cmd
      | Just cap <- rsMaxTerm st
      , any (\e -> exprSize e > cap) (commandExprs cmd) -> do
          emitL st "fail"
            ("表达式过大（节点上限 " ++ show cap ++ "）")
            ("Expression too large (node limit " ++ show cap ++ ")")
            [ "code" .= JStr "term_too_large", "limit" .= JNum cap ]
          return (Just st)
      | otherwise -> runWithTimeout st $ do
          when (any (snd . expandChecked (rsEnv st)) (commandExprs cmd)) $
            emitL st "warn"
              "宏展开燃料耗尽，结果可能包含未展开的定义（例如自引用定义）"
              "Macro expansion fuel exhausted; the result may contain unexpanded definitions"
              [ "code" .= JStr "macro_fuel" ]
          runCommand st cmd

replSettings :: ReplState -> Maybe FilePath -> Settings IO
replSettings st hist =
  setComplete (completeWordWithPrev Nothing " \t(),.\\λ→" (completeFn st))
              (defaultSettings { historyFile = hist })

completeFn :: ReplState -> String -> String -> IO [Completion]
completeFn st leftRev word
  | any (`isPrefixOf` trim (reverse leftRev)) [":load", ":save", ":edit"] = do
      (_, cs) <- completeFilename (reverse word ++ leftRev, "")
      return cs
  | otherwise = return $ map simpleCompletion
      (filter (word `isPrefixOf`) candidates)
  where
    candidates = Map.keys (rsEnv st) ++ map fst knownCommands

-- 交互式历史文件：~/.lambda_history（失败时静默不保存）
-- Interactive history: ~/.lambda_history (silently disabled on failure).
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
readReplLine = go [] 0 (0 :: Int)
  where
    go acc depth n
      | n >= 20 = return (Just (unwords (reverse acc)))
      | otherwise = do
          m <- getInputLine (if null acc then "λ> " else "  … ")
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
                   then go acc' depth' (n + 1)
                   else return (Just (unwords (reverse acc')))

repl :: ReplState -> InputT IO ()
repl st = do
  minput <- readReplLine
  case minput of
    Nothing    -> return ()
    Just input -> do
      me <- liftIO $ handleLine st input `catch` \(e :: AsyncException) ->
        case e of
          UserInterrupt -> do
            emitL st "warn" "已中断当前计算。" "Interrupted."
              [ "code" .= JStr "interrupted" ]
            return (Just st)
          _ -> throwIO e
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
data Options = Options
  { optBatch    :: Bool
  , optJson     :: Bool
  , optLang     :: Lang
  , optTimeout  :: Int
  , optFiles    :: [FilePath]
  , optHelp     :: Bool
  , optVersion  :: Bool
  , optEval     :: [String]
  , optCheck    :: Bool
  , optStrategy :: Maybe Strategy
  , optSteps    :: Maybe Int
  , optEta      :: Maybe Bool
  , optFast     :: Maybe Bool
  , optMaxTerm  :: Maybe Int
  }

defaultOptions :: Options
defaultOptions = Options False False Both 0 [] False False [] False
                         Nothing Nothing Nothing Nothing Nothing

parseArgs :: [String] -> Either String Options
parseArgs = go defaultOptions
  where
    go o [] = validate o
    go o ("--batch":xs)   = go o { optBatch = True } xs
    go o ("--json":xs)    = go o { optJson = True } xs
    go o ("-j":xs)        = go o { optJson = True } xs
    go o ("--help":xs)    = go o { optHelp = True } xs
    go o ("-h":xs)        = go o { optHelp = True } xs
    go o ("--version":xs) = go o { optVersion = True } xs
    go o ("-v":xs)        = go o { optVersion = True } xs
    go o ("--check":xs)   = go o { optCheck = True } xs
    go o ("--eval":xs) = case xs of
      (v:rest) -> go o { optEval = optEval o ++ [v] } rest
      [] -> Left "缺少 --eval 的值 / missing value for --eval"
    go o ("-e":xs) = case xs of
      (v:rest) -> go o { optEval = optEval o ++ [v] } rest
      [] -> Left "缺少 -e 的值 / missing value for -e"
    go o ("--lang":xs) = case xs of
      (v:rest) -> case parseLang v of
        Just l  -> go o { optLang = l } rest
        Nothing -> Left ("未知语言 / unknown language: " ++ v)
      [] -> Left "缺少 --lang 的值 / missing value for --lang"
    go o ("--timeout":xs) = case xs of
      (v:rest) -> case reads v :: [(Int, String)] of
        [(n, "")] | n >= 0 -> go o { optTimeout = n } rest
        _ -> Left ("无效的 --timeout 秒数 / invalid --timeout: " ++ v)
      [] -> Left "缺少 --timeout 的值 / missing value for --timeout"
    go o ("--max-term-size":xs) = case xs of
      (v:rest) -> case reads v :: [(Int, String)] of
        [(n, "")] | n > 0 -> go o { optMaxTerm = Just n } rest
        _ -> Left ("无效的 --max-term-size / invalid --max-term-size: " ++ v)
      [] -> Left "缺少 --max-term-size 的值 / missing value for --max-term-size"
    go o ("--strategy":xs) = case xs of
      (v:rest) -> case parseStrategy v of
        Just s  -> go o { optStrategy = Just s } rest
        Nothing -> Left ("未知策略 / unknown strategy: " ++ v)
      [] -> Left "缺少 --strategy 的值 / missing value for --strategy"
    go o ("--steps":xs) = case xs of
      (v:rest) -> case reads v :: [(Int, String)] of
        [(n, "")] | n > 0 -> go o { optSteps = Just n } rest
        _ -> Left ("无效的 --steps 值 / invalid --steps: " ++ v)
      [] -> Left "缺少 --steps 的值 / missing value for --steps"
    go o ("--eta":xs) = case xs of
      (v:rest) | Just b <- parseOnOff v -> go o { optEta = Just b } rest
      _ -> go o { optEta = Just True } xs
    go o ("--fast":xs) = case xs of
      (v:rest) | Just b <- parseOnOff v -> go o { optFast = Just b } rest
      _ -> go o { optFast = Just True } xs
    go o (x:xs)
      | Just v <- stripPrefix "--lang=" x =
          case parseLang v of
            Just l  -> go o { optLang = l } xs
            Nothing -> Left ("未知语言 / unknown language: " ++ v)
      | Just v <- stripPrefix "--timeout=" x =
          case reads v :: [(Int, String)] of
            [(n, "")] | n >= 0 -> go o { optTimeout = n } xs
            _ -> Left ("无效的 --timeout 秒数 / invalid --timeout: " ++ v)
      | Just v <- stripPrefix "--eval=" x =
          go o { optEval = optEval o ++ [v] } xs
      | Just v <- stripPrefix "--strategy=" x =
          case parseStrategy v of
            Just s  -> go o { optStrategy = Just s } xs
            Nothing -> Left ("未知策略 / unknown strategy: " ++ v)
      | Just v <- stripPrefix "--max-term-size=" x =
          case reads v :: [(Int, String)] of
            [(n, "")] | n > 0 -> go o { optMaxTerm = Just n } xs
            _ -> Left ("无效的 --max-term-size / invalid --max-term-size: " ++ v)
      | Just v <- stripPrefix "--steps=" x =
          case reads v :: [(Int, String)] of
            [(n, "")] | n > 0 -> go o { optSteps = Just n } xs
            _ -> Left ("无效的 --steps 值 / invalid --steps: " ++ v)
      | Just v <- stripPrefix "--eta=" x =
          case parseOnOff v of
            Just b  -> go o { optEta = Just b } xs
            Nothing -> Left ("无效的 --eta 值 / invalid --eta: " ++ v)
      | Just v <- stripPrefix "--fast=" x =
          case parseOnOff v of
            Just b  -> go o { optFast = Just b } xs
            Nothing -> Left ("无效的 --fast 值 / invalid --fast: " ++ v)
      | "-" `isPrefixOf` x = Left ("未知选项 / unknown option: " ++ x)
      | otherwise          = go o { optFiles = optFiles o ++ [x] } xs
    validate o
      | optCheck o && optBatch o = Left "--check 不能与 --batch 同用 / --check cannot be combined with --batch"
      | optCheck o && not (null (optEval o)) =
          Left "--check 不能与 --eval 同用 / --check cannot be combined with --eval"
      | optCheck o && null (optFiles o) =
          Left "--check 需要一个或多个文件 / --check needs at least one file"
      | not (null (optEval o)) && optBatch o =
          Left "--eval 不能与 --batch 同用 / --eval cannot be combined with --batch"
      | otherwise = Right o

-- 把命令行设置套到初始状态上；文件里的 :strategy 等仍可覆盖
-- Apply CLI settings to the initial state; in-file commands may still override.
applyCliOptions :: Options -> ReplState -> ReplState
applyCliOptions o st = st
  { rsStrategy = fromMaybe (rsStrategy st) (optStrategy o)
  , rsLimit    = fromMaybe (rsLimit st) (optSteps o)
  , rsEta      = fromMaybe (rsEta st) (optEta o)
  , rsFast     = fromMaybe (rsFast st) (optFast o)
  , rsMaxTerm  = optMaxTerm o <|> rsMaxTerm st
  }

-- 启动时加载一个文件；失败只报告，不中断后续文件
-- Load one startup file; failures are reported but do not stop later files.
loadStartupFile :: ReplState -> FilePath -> IO ReplState
loadStartupFile st path = do
  res <- loadDefinitionsFromFile (rsMaxTerm st) (rsEnv st) (rsTypeEnv st) path
  case res of
    Left err -> do
      emitL st "fail" ("文件加载错误: " ++ err) ("File load error: " ++ err)
        [ "code" .= JStr "load_error" ]
      return st { rsLastFile = Just path }
    Right out -> do
      let st' = applyLoadOutcome st out
      unless (null (loOk out)) $
        emitL st' "info"
          ("成功加载 " ++ show (length (loOk out)) ++ " 个定义")
          ("Loaded " ++ show (length (loOk out)) ++ " definitions")
          [ "loaded" .= JNum (length (loOk out)) ]
      forM_ (reverse (loFail out)) $ \(n, line, msg, code) ->
        emitL st' "error"
          ("第 " ++ show n ++ " 行加载失败: " ++ shorten 60 line ++ " — " ++ fst msg)
          ("Line " ++ show n ++ " failed to load: " ++ shorten 60 line
            ++ " -- " ++ snd msg)
          [ "line" .= JNum n, "code" .= JStr code ]
      forM_ (loStrategy out) $ \s -> emitL st' "info"
        ("求值策略：" ++ strategyLabel s) ("Strategy: " ++ strategyLabelEn s)
        [ "strategy" .= JStr (strategyId s) ]
      forM_ (loLimit out) $ \n -> emitL st' "info"
        ("归约步数上限：" ++ show n) ("Reduction step limit: " ++ show n)
        [ "limit" .= JNum n ]
      forM_ (loLang out) $ \l -> emitL st' "info"
        "语言已切换。" "Language switched."
        [ "lang" .= JStr (langId l) ]
      forM_ (loFast out) $ \on -> emitL st' "info"
        (if on then "快速模式：开启" else "快速模式：关闭")
        (if on then "Fast mode: on" else "Fast mode: off")
        [ "fast" .= JBool on ]
      forM_ (loEta out) $ \on -> emitL st' "info"
        (if on then "η 归约：开启" else "η 归约：关闭")
        (if on then "Eta reduction: on" else "Eta reduction: off")
        [ "eta" .= JBool on ]
      stAfter <- replayEcho st' (loEcho out)
      return stAfter { rsLastFile = Just path }

main :: IO ()
main = do
  args <- getArgs
  case parseArgs args of
    Left err -> do
      hPutStrLn stderr err
      exitFailure
    Right opts -> do
      term <- hIsTerminalDevice stdout
      when (not term) $ do
        hSetEncoding stdout utf8
        hSetEncoding stderr utf8
      if optHelp opts
        then putStrLn (helpMessage (optLang opts))
        else if optVersion opts
          then putStrLn versionString
          else do
            let json  = optJson opts
                batch = optBatch opts
                lang  = optLang opts
            when (batch || not term || not (null (optEval opts)) || optCheck opts) $ do
              hSetEncoding stdin utf8
              hSetEncoding stdout utf8
              hSetEncoding stderr utf8
            when batch $ hSetBuffering stdout LineBuffering
            let st0 = applyCliOptions opts $
                        ReplState initEnv initTypeEnv Applicative defaultLimit
                          (optTimeout opts) False False json lang Nothing [] Nothing Nothing
            if optCheck opts
              then do
                ok <- runCheck st0 (optFiles opts)
                if ok then exitSuccess else exitFailure
              else do
                st1 <- foldM loadStartupFile st0 (optFiles opts)
                if not (null (optEval opts))
                  then do
                    ok <- runEvalCommands st1 (optEval opts)
                    hFlush stdout
                    if ok then exitSuccess else exitFailure
                  else if batch
                    then batchLoop st1
                    else do
                      hist <- historyPath
                      runInputT (replSettings st1 hist) (repl st1)

-- --check：加载并校验 .lam，失败时返回 False
-- --check: load and validate .lam files; False when anything fails.
runCheck :: ReplState -> [FilePath] -> IO Bool
runCheck st0 files = go st0 True files
  where
    go _ ok [] = return ok
    go st ok (path:rest) = do
      res <- loadDefinitionsFromFile (rsMaxTerm st) (rsEnv st) (rsTypeEnv st) path
      case res of
        Left err -> do
          emitL st "fail"
            ("检查失败 " ++ path ++ "：" ++ err)
            ("Check failed for " ++ path ++ ": " ++ err)
            [ "file" .= JStr path, "ok" .= JBool False
            , "code" .= JStr "load_error" ]
          go st False rest
        Right out -> do
          let st' = applyLoadOutcome st out
              okHere = null (loFail out)
          emitL st' (if okHere then "info" else "fail")
            ((if okHere then "检查通过 " else "检查有错误 ") ++ path
              ++ "：成功 " ++ show (length (loOk out))
              ++ " 个定义，失败 " ++ show (length (loFail out)) ++ " 行")
            ((if okHere then "Checked " else "Check found errors in ") ++ path
              ++ ": " ++ show (length (loOk out)) ++ " definitions, "
              ++ show (length (loFail out)) ++ " failed line(s)")
            [ "file" .= JStr path, "ok" .= JBool okHere
            , "loaded" .= JNum (length (loOk out))
            , "failed" .= JNum (length (loFail out)) ]
          forM_ (reverse (loFail out)) $ \(n, line, msg, code) ->
            emitL st' "error"
              ("第 " ++ show n ++ " 行: " ++ shorten 60 line ++ " — " ++ fst msg)
              ("Line " ++ show n ++ ": " ++ shorten 60 line ++ " -- " ++ snd msg)
              [ "file" .= JStr path, "line" .= JNum n
              , "code" .= JStr code ]
          go st' (ok && okHere) rest

-- --eval：依次执行命令行给出的命令；解析失败时返回 False
-- --eval: run the given commands in order; False when a command fails to parse.
runEvalCommands :: ReplState -> [String] -> IO Bool
runEvalCommands st0 cmds = go st0 True cmds
  where
    go _ ok [] = return ok
    go st ok (src:rest) =
      case parseCommand src of
        Left err -> do
          emitL st "error"
            ("解析错误: 第 " ++ show (pePos err) ++ " 列 — " ++ fst (peMsg err))
            ("Parse error at column " ++ show (pePos err) ++ " -- " ++ snd (peMsg err))
            [ "pos" .= JNum (pePos err), "code" .= JStr "parse_error" ]
          return False
        Right _ -> do
          mst <- handleLine st src
          case mst of
            Nothing  -> return ok
            Just st' -> go st' ok rest

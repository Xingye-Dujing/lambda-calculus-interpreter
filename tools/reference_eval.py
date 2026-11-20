#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 lambda 演算参考实现，作为测试预言机 / Pure lambda-calculus test oracle

本文件是项目 Haskell 解释器行为的小型、无依赖参照实现，供测试比对使用。
它解析 pretty 语法的一个实用子集，按正常序（最左最外）做完全 beta 归约，
并提供 α 等价判断、单步归约与 de Bruijn 诊断输出。

A small, dependency-free reference for the project's Haskell interpreter, used
as a test oracle. It parses a practical subset of the pretty syntax, performs
normal-order (leftmost-outermost) full beta reduction, and exposes alpha
equivalence, single-step reduction and de Bruijn diagnostics.
"""

from __future__ import annotations

import sys

# 深 Church 数会产生嵌套很深的应用项，提高递归上限以容纳诊断与打印
# Deep Church numerals build deeply nested applications; raise the recursion
# limit so diagnostics and pretty printing can still walk them.
sys.setrecursionlimit(100000)

# 运算符字符与解释器保持一致 / Operator chars kept in sync with the interpreter
_OPERATORS = frozenset("+*-/%^?!<>|&~#$")

# 项表示 Term representation
class Term:
    """所有项的基类 / Base class of all terms"""
    __slots__ = ()

class Var(Term):
    """变量，自由变量或绑定变量 / A variable, free or bound"""
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

class Lam(Term):
    """抽象 λx. body / Abstraction λx. body"""
    __slots__ = ("var", "body")

    def __init__(self, var: str, body: Term):
        self.var = var
        self.body = body

class App(Term):
    """应用 f a / Application f a"""
    __slots__ = ("func", "arg")

    def __init__(self, func: Term, arg: Term):
        self.func = func
        self.arg = arg

# 词法与语法分析 Lexing and parsing
def _strip_comment(s: str) -> str:
    """去掉行尾 `--` / `#` 注释，仅当注释符在行首或空白之后才算

    Drop trailing `--` / `#` comments; a marker counts only at line start or
    after whitespace, so operator names containing those chars survive.
    """
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '-' and i + 1 < n and s[i + 1] == '-' and (not out or out[-1].isspace()):
            break
        if c == '#' and (not out or out[-1].isspace()):
            break
        out.append(c)
        i += 1
    return ''.join(out)

def _ident_start(c: str) -> bool:
    """标识符首字符可为字母或运算符 / An ident may start with a letter or operator"""
    return c.isalpha() or c in _OPERATORS

def _ident_rest(c: str) -> bool:
    """后续字符还可含数字、_ 与 ' / More chars may include digits, _ and '"""
    return c.isalpha() or c.isdigit() or c in "_'" or c in _OPERATORS

def _tokenize(s: str) -> list:
    """把源码切成 token / Turn source text into tokens"""
    tokens = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
        elif c == 'λ' or c == '\\':
            tokens.append(('LAM',)); i += 1
        elif c == '→':
            tokens.append(('ARROW',)); i += 1
        elif c == '-' and i + 1 < n and s[i + 1] == '>':
            tokens.append(('ARROW',)); i += 2
        elif c == '.':
            tokens.append(('DOT',)); i += 1
        elif c == '(':
            tokens.append(('LP',)); i += 1
        elif c == ')':
            tokens.append(('RP',)); i += 1
        elif c.isdigit():
            j = i + 1
            while j < n and s[j].isdigit():
                j += 1
            tokens.append(('NUM', int(s[i:j]))); i = j
        elif _ident_start(c):
            j = i + 1
            while j < n and _ident_rest(s[j]):
                j += 1
            tokens.append(('IDENT', s[i:j])); i = j
        else:
            raise SyntaxError("非法字符 / illegal character: " + repr(c))
    return tokens

def _church(n: int) -> Term:
    """把 0..9999 的整数构造成邱奇数 / Build a Church numeral for 0..9999"""
    if not 0 <= n <= 9999:
        raise ValueError("邱奇数超出范围 / Church numeral out of range: " + str(n))
    body = Var('x')
    for _ in range(n):
        body = App(Var('f'), body)
    return Lam('f', Lam('x', body))

class _Parser:
    """递归下降解析器 / Recursive-descent parser"""
    def __init__(self, tokens: list):
        self.toks = tokens
        self.pos = 0

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def take(self):
        tok = self.peek()
        if tok is None:
            raise SyntaxError("表达式意外结束 / unexpected end of term")
        self.pos += 1
        return tok

    def parse(self) -> Term:
        term = self.parse_expr()
        if self.peek() is not None:
            raise SyntaxError("多余记号 / unexpected token: " + repr(self.peek()))
        return term

    def parse_expr(self) -> Term:
        if self.peek() is not None and self.peek()[0] == 'LAM':
            return self.parse_lam()
        return self.parse_app()

    def parse_lam(self) -> Term:
        self.take()  # LAM
        names = []
        while self.peek() is not None and self.peek()[0] == 'IDENT':
            names.append(self.take()[1])
        if not names:
            raise SyntaxError("λ 缺少参数 / lambda missing a parameter")
        sep = self.peek()
        if sep is None or sep[0] not in ('DOT', 'ARROW'):
            raise SyntaxError("λ 缺少分隔符 / lambda missing a separator")
        self.take()
        body = self.parse_expr()
        for name in reversed(names):
            body = Lam(name, body)
        return body

    def parse_app(self) -> Term:
        term = self.parse_atom()
        while self.peek() is not None and self.peek()[0] in ('NUM', 'IDENT', 'LP'):
            term = App(term, self.parse_atom())
        return term

    def parse_atom(self) -> Term:
        tok = self.take()
        if tok[0] == 'NUM':
            return _church(tok[1])
        if tok[0] == 'IDENT':
            return Var(tok[1])
        if tok[0] == 'LP':
            term = self.parse_expr()
            if self.peek() is None or self.peek()[0] != 'RP':
                raise SyntaxError("缺少右括号 / missing closing parenthesis")
            self.take()
            return term
        raise SyntaxError("非法原子 / unexpected atom: " + repr(tok))

def parse(term: str) -> Term:
    """把 pretty 语法字符串解析成项 / Parse a pretty-syntax string into a term"""
    tokens = _tokenize(_strip_comment(term))
    if not tokens:
        raise SyntaxError("空表达式 / empty term")
    return _Parser(tokens).parse()

# 替换与归约 Substitution and reduction
def _free_vars(t: Term) -> set:
    """计算自由变量集合 / Compute the set of free variables"""
    if isinstance(t, Var):
        return {t.name}
    if isinstance(t, App):
        return _free_vars(t.func) | _free_vars(t.arg)
    return _free_vars(t.body) - {t.var}

def _fresh(name: str, avoid: set) -> str:
    """生成避开给定集合的新名字 / Generate a name avoiding a given set"""
    if name not in avoid:
        return name
    i = 1
    while name + str(i) in avoid:
        i += 1
    return name + str(i)

def _rename(t: Term, old: str, new: str) -> Term:
    """把自由出现的 old 改名为 new / Rename free occurrences of old to new"""
    if isinstance(t, Var):
        return Var(new) if t.name == old else t
    if isinstance(t, App):
        return App(_rename(t.func, old, new), _rename(t.arg, old, new))
    if t.var == old:
        return t
    return Lam(t.var, _rename(t.body, old, new))

def _subst(t: Term, name: str, value: Term, fv_value: set) -> Term:
    """捕获避免替换 [name := value] / Capture-avoiding substitution"""
    if isinstance(t, Var):
        return value if t.name == name else t
    if isinstance(t, App):
        return App(_subst(t.func, name, value, fv_value),
                   _subst(t.arg, name, value, fv_value))
    if t.var == name:
        return t
    if t.var in fv_value:
        fresh = _fresh(t.var, fv_value | _free_vars(t.body) | {name})
        body = _rename(t.body, t.var, fresh)
        return Lam(fresh, _subst(body, name, value, fv_value))
    return Lam(t.var, _subst(t.body, name, value, fv_value))

def _step(t: Term):
    """正常序单步归约，返回新项或 None / One normal-order step, or None"""
    if isinstance(t, App):
        if isinstance(t.func, Lam):
            return _subst(t.func.body, t.func.var, t.arg, _free_vars(t.arg))
        new_func = _step(t.func)
        if new_func is not None:
            return App(new_func, t.arg)
        new_arg = _step(t.arg)
        if new_arg is not None:
            return App(t.func, new_arg)
        return None
    if isinstance(t, Lam):
        new_body = _step(t.body)
        if new_body is not None:
            return Lam(t.var, new_body)
    return None

# 打印与诊断 Pretty printing and diagnostics
def _pretty(t: Term, prec: int = 0) -> str:
    """按解释器风格打印项 / Print a term in the interpreter's style"""
    if isinstance(t, Var):
        return t.name
    if isinstance(t, Lam):
        s = 'λ' + t.var + ' → ' + _pretty(t.body, 0)
        return '(' + s + ')' if prec > 0 else s
    s = _pretty(t.func, 1) + ' ' + _pretty(t.arg, 2)
    return '(' + s + ')' if prec > 1 else s

def normalize(term: str, limit: int = 20000) -> str:
    """正常序完全 beta 归约到范式，受步数上限约束

    Normalize to normal form with a step budget, raising RuntimeError on
    exhaustion so a divergent term can never loop forever.
    """
    t = parse(term)
    steps = 0
    while True:
        nxt = _step(t)
        if nxt is None:
            return _pretty(t)
        steps += 1
        if steps > limit:
            raise RuntimeError(
                "归约步数超过上限 / reduction step limit %d exceeded" % limit)
        t = nxt

def step(term: str) -> tuple[str, bool]:
    """走一步正常序归约，返回 (项, 是否发生归约)

    Take one normal-order beta step; return (term, whether a step happened).
    """
    t = parse(term)
    nxt = _step(t)
    if nxt is None:
        return _pretty(t), False
    return _pretty(nxt), True

def _db(t: Term, env: list):
    """构造 de Bruijn 结构，绑定变量用下标、自由变量用名字

    Build a de Bruijn structure: bound variables are indices, free ones names.
    """
    if isinstance(t, Var):
        if t.name in env:
            return ('B', env.index(t.name))
        return ('F', t.name)
    if isinstance(t, App):
        return ('A', _db(t.func, env), _db(t.arg, env))
    return ('L', _db(t.body, [t.var] + env))

def alpha_eq(a: str, b: str) -> bool:
    """判断两个项字符串是否 α 等价 / Check whether two strings are alpha-equivalent"""
    return _db(parse(a), []) == _db(parse(b), [])

def _db_str(node, prec: int = 0) -> str:
    """打印 de Bruijn 结构 / Pretty-print a de Bruijn structure"""
    kind = node[0]
    if kind == 'B':
        return str(node[1])
    if kind == 'F':
        return node[1]
    if kind == 'L':
        s = 'λ.' + _db_str(node[1], 0)
        return '(' + s + ')' if prec > 0 else s
    s = _db_str(node[1], 1) + ' ' + _db_str(node[2], 2)
    return '(' + s + ')' if prec > 1 else s

def to_debruijn(term: str) -> str:
    """输出项的 de Bruijn 诊断形式 / Emit a de Bruijn diagnostic form"""
    return _db_str(_db(parse(term), []))

if __name__ == "__main__":
    parsed = parse(r"(\f.λx.f (f x))")
    assert alpha_eq(_pretty(parsed), "λa → λb → a (a b)")
    assert normalize("(λx.x) 3") == "λf → λx → f (f (f x))"
    assert alpha_eq("λx.x", "λy.y")
    assert not alpha_eq("λx.λy.x", "λx.λy.y")
    assert to_debruijn("λx.λy.x y") == "λ.λ.1 0"
    got, did = step("(λx.x) z")
    assert did and got == "z"
    print(_pretty(parsed))
    print(normalize("(λx.x) 3"))
    print(alpha_eq("λx.x", "λy.y"), alpha_eq("λx.x", "λx.y"))

# 支持邱奇数编码的 Lambda 演算解释器

基于 Haskell 实现的纯 lambda 演算解释器，支持邱奇数、邱奇布尔值以及宏定义环境。提供两个版本：

- `main`: 最小核心解释器，仅支持 lambda 演算与正规序归约。
- `extension`: 增强版，支持变量定义、文件加载、环境查看、扩展变量名语法（允许特定运算符）、自动数字转换等。

## 功能特点

1. 纯 lambda 演算，支持 alpha 等价与无捕获替换。
2. 正规序（应用序）归约至 beta-正规形。
3. 自动识别邱奇数与邱奇布尔值，结果后附数字/布尔提示。
4. 增强版独有：

- 定义变量 (`name = expression`) 并复用。
- 从文件加载定义 (`:load file`).
- 查看当前环境 (`:env`).
- 变量名可包含运算符 (`+`, `-`, `*`, `/`, `%`, `^`, `?`, `!`, `<`, `>`, `|`, `&`, `~`, `#`, `$`) 、下划线、数字、单引号，但不能以数字开头。
- 直接输入十进制数字自动转换为邱奇数。
- 预定义环境：`TRUE`, `FALSE`, `NOT`, `AND`, `OR`, `IF`, `ZERO`, `ONE`, `TWO`, `THREE`, `SUCC`, `PLUS`, `MULT`.

## Building

使用提供的 `build.sh` 脚本：

```bash
chmod +x build.sh
./build.sh
```

脚本会以优化选项 (`-O2`, `-split-sections`, `-optlc-O3`, `-threaded`, etc.) 编译两个解释器，生成可执行文件`main` and `extension`。

## 使用方法

### 最小解释器 (`main`)

```bash
./main
```

启动 REPL，直接输入 lambda 表达式：

```
λ> \x. x
⇒ λx → x
λ> (\x. x) y
⇒ y
λ> \f x. f (f x)
⇒ λf → λx → f (f x)
λ> (\a.\b.a ((\n.\a.\b.a (n a b)) b)) (\f.\x.f (f x)) (\f.\x.f (f (f x)))
⇒ λx → λb' → x (x (x (x (x (x (x (x (x (x (x (x (x (x (x (x b')))))))))))))))
```

输入 `:q` 退出。

### 增强解释器 (`extension`)

```bash
./extension [-h,--help] [file]
```

如果提供了文件名，启动 REPL 前会先加载文件中的定义。

1. REPL 内建命令：

- `:load <file>`: 加载定义文件 (每行格式：`name = expr`)
- `:let name = expr`: 在当前环境中定义变量
- `:env`: 显示当前所有定义
- `:q`: 退出解释器

2. 表达式语法：

- 变量名：以字母或特定运算符开头 (`+ - * / % ^ ? ! < > | & ~ # $`)，后续可包含字母、数字、下划线、单引号或运算符。
- Lambda 抽象：`λx.body` or 多个参数：`λx y.body`.
- 应用：`f a` (左结合)，括号可用于分组。
- 数字：直接输入`0`, `1`, `2`, ..., `9` 自动转换为邱奇数。
- 定义：`name = expression` (也可直接在 REPL 中输入)。

3. 示例:

```
λ> TRUE
⇒ λt → λf → t  (Church boolean True)
λ> TRUE 2 3
⇒ λf → λx → f (f x)  (Church numeral 2)
λ> PLUS 2 3
⇒ λf → λx → f (f (f (f (f x))))  (Church numeral 5)
λ> 3 2
⇒ λx → λx' → x (x (x (x (x (x (x (x x')))))))  (Church numeral 8)
λ> 2 3
⇒ λx → λx' → x (x (x (x (x (x (x (x (x x'))))))))  (Church numeral 9)
λ> + = PLUS
defined + = λm → λn → λf → λx → m f (n f x)
λ> + 4 3
⇒ λf → λx → f (f (f (f (f (f (f x))))))  (Church numeral 7)
λ> :env
┌──────────┬─────────────────────────────────┐
│ Var Name │ Value                           │
├──────────┼─────────────────────────────────┤
│ +        │ λm → λn → λf → λx → m f (n f x) │
│ AND      │ λb1 → λb2 → b1 b2 FALSE         │
│ FALSE    │ λt → λf → f                     │
│ IF       │ λc → λt → λf → c t f            │
│ MULT     │ λm → λn → λf → m (n f)          │
│ NOT      │ λb → b FALSE TRUE               │
│ ONE      │ λf → λx → f x                   │
│ OR       │ λb1 → λb2 → b1 TRUE b2          │
│ PLUS     │ λm → λn → λf → λx → m f (n f x) │
│ SUCC     │ λn → λf → λx → f (n f x)        │
│ THREE    │ λf → λx → f (f (f x))           │
│ TRUE     │ λt → λf → t                     │
│ TWO      │ λf → λx → f (f x)               │
│ ZERO     │ λf → λx → x                     │
└──────────┴─────────────────────────────────┘
λ> :load test.lam

成功加载 7 个定义：
┌─────────────────┬─────────────────────────────────────────────────────────────────┐
│ Var Name        │ Value                                                           │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ id              │ λ? → ?                                                          │
│ *               │ λm → λn → λf → m (n f)                                          │
│ +               │ λm → λn → λf → λx → m f (n f x)                                 │
│ aPOWbPOWc       │ λa → λb → λc → c b a                                            │
│ tow_pow_eight   │ (λf → λx → f (f (f x))) (λf → λx → f (f x)) (λf → λx → f (f x)) │
│ POW             │ λa → λb → b a                                                   │
│ b_ADD_ONE_POW_a │ λa → λb → b ((λn → λf → λx → f (n f x)) a)                      │
└─────────────────┴─────────────────────────────────────────────────────────────────┘

！！！以下 2 行解析失败（已忽略）：
  第 4 行: ERROR = \a.a b c)
  第 2 行: ERR  = \a.

λ> :env
┌─────────────────┬─────────────────────────────────────────────────────────────────┐
│ Var Name        │ Value                                                           │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ *               │ λm → λn → λf → m (n f)                                          │
│ +               │ λm → λn → λf → λx → m f (n f x)                                 │
│ AND             │ λb1 → λb2 → b1 b2 FALSE                                         │
│ FALSE           │ λt → λf → f                                                     │
│ IF              │ λc → λt → λf → c t f                                            │
│ MULT            │ λm → λn → λf → m (n f)                                          │
│ NOT             │ λb → b FALSE TRUE                                               │
│ ONE             │ λf → λx → f x                                                   │
│ OR              │ λb1 → λb2 → b1 TRUE b2                                          │
│ PLUS            │ λm → λn → λf → λx → m f (n f x)                                 │
│ POW             │ λa → λb → b a                                                   │
│ SUCC            │ λn → λf → λx → f (n f x)                                        │
│ THREE           │ λf → λx → f (f (f x))                                           │
│ TRUE            │ λt → λf → t                                                     │
│ TWO             │ λf → λx → f (f x)                                               │
│ ZERO            │ λf → λx → x                                                     │
│ aPOWbPOWc       │ λa → λb → λc → c b a                                            │
│ b_ADD_ONE_POW_a │ λa → λb → b ((λn → λf → λx → f (n f x)) a)                      │
│ id              │ λ? → ?                                                          │
│ tow_pow_eight   │ (λf → λx → f (f (f x))) (λf → λx → f (f x)) (λf → λx → f (f x)) │
└─────────────────┴─────────────────────────────────────────────────────────────────┘
λ> aPOWbPOWc 1 2 2
⇒ λx' → λx → x' x  (Church numeral 1)
λ> aPOWbPOWc 2 2 2
⇒ λx' → λx → x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' x)))))))))))))))  (Church numeral 16)
λ> id 3
⇒ λf → λx → f (f (f x))  (Church numeral 3)
λ> :let FOUR = \f x.f (f (f (f x)))
defined FOUR = λf → λx → f (f (f (f x)))
λ> FOUR
⇒ λf → λx → f (f (f (f x)))  (Church numeral 4)
λ> :q
```

## 技术简述

1. 两个解释器均实现：

- 无捕获替换：通过 freshVar 重命名绑定变量，避免捕获自由变量。
- 正规序归约（nf）：反复归约直至得到 beta-正规形。
- 自由变量计算：用于替换时判断是否需要重命名。

2. 增强版额外实现：

- 宏展开（`expand`）：将定义变量替换为其体，同时维护绑定变量集合避免捕获。
- 解析器：支持自定义变量名规则和自动数字转邱奇数。
- 文件加载：按行解析，统计成功/失败，输出友好表格。
- 动态表格打印：自动调整列宽，适应最长的变量名和表达式字符串。

## 许可证

本项目开源，欢迎用于学习或实验。

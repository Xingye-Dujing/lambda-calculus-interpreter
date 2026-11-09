# 贡献指南 / Contributing

欢迎贡献。本项目提供两个独立的单文件 Haskell 解释器，文档与面向用户的文本都是中英双语；
提交改动前请阅读下列约定，并让中英两版逐节对应。
Thanks for contributing. This project ships two standalone single-file Haskell
interpreters; documentation and user-facing text are bilingual, so please read
the conventions below and keep the Chinese and English versions in step.

## 1. 构建与测试 / 1. Build and test

Windows 用 `.\build.bat`，Linux / macOS 用 `./build.sh`，两者都直接调用 `ghc`；
`cabal build all` 会构建同样的两个可执行文件。共享核心在 `main.hs` 与
`extension.hs` 中各有一份，核心或归约逻辑的修复要同时改两处，并用
`python tools/check_core_sync.py` 校验一致。改动后运行端到端测试
`python tests/run_tests.py [--bin ./extension]`，或 `./test.sh` / `test.bat`。
On Windows use `.\build.bat`; on Linux/macOS use `./build.sh`. Both call `ghc`
directly, and `cabal build all` builds the same two executables. The core is
duplicated across `main.hs` and `extension.hs`: apply core/reduction fixes to
both and verify with `python tools/check_core_sync.py`. `--fix` copies the shared
core from `extension.hs` into `main.hs`. After any change, run
the end-to-end suite `python tests/run_tests.py [--bin ./extension]`, or
`./test.sh` / `test.bat`.

## 2. 双语字符串规范 / 2. Bilingual string rules

所有注释、帮助文本、错误与界面文案都经 `tr` / `renderMsg` 辅助函数与 `Msg` 类型，
中文与英文成对出现；不要只加中文或只加英文的字符串。默认输出语言是 `both`，
`--lang` / `:lang` 可切换到 `zh` 或 `en`，Web 端另有自己的 `I18N` 词典。
Every comment, help text, error and UI string goes through the `tr` /
`renderMsg` helpers and the `Msg` type, always with a Chinese form and an
English form together; never add a Chinese-only or English-only string. The
default output language is `both`; `--lang` / `:lang` switch to `zh` or `en`,
and the web UI has its own `I18N` dictionary.

## 3. 引号 / 3. Quotation marks

中文文本用全角引号 “ ”，英文文本用 ASCII 引号 `"` 与 `'`。任何位置都不要使用
U+300C 与 U+300D 这两个角括号：源码、注释、Markdown 与界面文案都不例外。
Chinese text uses the full-width quotes “ ”; English text uses ASCII `"` and `'`.
Never use the corner brackets U+300C and U+300D anywhere: code, comments,
Markdown, or UI strings.

## 4. 注释 / 4. Comments

注释行同样中英双语；注释行不得以中文句号 `。` 结尾，可以不带标点，或改用英文句号。
请保留 λ、→、⇒ 与终端风格排版。
Comment lines are bilingual too, and must not end with a Chinese full stop `。`:
end with nothing or an English period instead. Keep the λ/→/⇒ symbols and the
terminal-style formatting.

## 5. 新增命令与 Web UI / 5. New commands and the Web UI

新增 REPL 命令时，必须同时在 Web UI 加入口（工具标签页、按钮或命令面板），
补上 `:help <cmd>` 分项帮助与测试，并同步 README.md、README-CN.md 与 CHANGELOG.md。
仅限本地终端的命令（如 `:edit`）可以只在终端提供，但网页端应给出明确提示。
When adding a REPL command, also add a Web UI entry (Tools tab, a button, or the
command palette), cover it with tests and `:help <cmd>` help, and update
README.md, README-CN.md and CHANGELOG.md. Local-only commands such as `:edit`
may stay CLI-only, but the web terminal should explain why they are unavailable.

## 6. 本地运行 CI / 6. Running CI locally

CI 在 Ubuntu、macOS、Windows 三个平台运行。本地可按相同顺序复现：构建、Cabal 构建、
核心一致性校验、Python 字节码编译、安装依赖、端到端测试。
CI runs on Ubuntu, macOS and Windows. Reproduce it locally in the same order:
build, Cabal build, core-sync check, Python byte-compile, install dependencies,
end-to-end tests.

```bash
./build.sh                                  # Windows 用 build.bat / Windows: build.bat
cabal build all
python tools/check_core_sync.py
python -m compileall -q web tests tools
python -m pip install -r web/requirements.txt
python tests/run_tests.py
```

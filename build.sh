#!/usr/bin/env bash
# 构建两个独立单文件解释器 / Build the two standalone single-file interpreters
# 用法：./build.sh（设置 LAMBDA_NATIVE=1 开启本机优化）/ Usage: ./build.sh (set LAMBDA_NATIVE=1 for native tuning)
set -eu

# 跨平台基础参数 / Portable base flags
FLAGS="-O2 -Wall -threaded -rtsopts -package containers -package haskeline -package directory -package process"

# ghc 必须存在 / ghc must be present
if ! command -v ghc >/dev/null 2>&1; then
    echo "错误：未找到 ghc，请先安装 GHC 9.6 / Error: ghc not found; install GHC 9.6 first" >&2
    exit 1
fi

# 本机优化默认关闭，保证产物可移植 / Native tuning is opt-in for portable binaries
NATIVE=""
if [ "${LAMBDA_NATIVE:-0}" = "1" ]; then
    NATIVE="-optlc-O3 -optlc-march=native"
fi

# GNU ld 专属链接参数仅用于 Linux / GNU ld-specific link flags on Linux only
LINK=""
case "$(uname -s)" in
    Linux)
        LINK="-split-sections -optl-Wl,--gc-sections -optl-s"
        ;;
    *)
        # macOS 与其它平台保持可移植参数 / macOS and others keep portable flags
        ;;
esac

build_one() {
    out="$1"
    src="$2"
    if ghc $FLAGS $NATIVE $LINK -o "$out" "$src"; then
        echo "构建成功 / build succeeded: $out"
    else
        echo "构建失败 / build failed: $out" >&2
        exit 1
    fi
}

build_one main main.hs
build_one extension extension.hs

echo "全部构建完成 / all builds finished"

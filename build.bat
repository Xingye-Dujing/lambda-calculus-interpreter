@echo off
setlocal
chcp 65001 >nul 2>nul
rem Build the two standalone single-file interpreters / 构建两个独立单文件解释器
rem Portable flags: no -march=native and no GNU ld-specific link flags
rem 可移植参数：不使用 -march=native，也不使用 GNU ld 专属链接参数

rem Check that ghc is available / 检查 ghc 是否可用
where ghc >nul 2>nul
if errorlevel 1 (
    echo Error: ghc not found; install GHC 9.6 first
    echo 错误：未找到 ghc，请先安装 GHC 9.6
    exit /b 1
)

set "FLAGS=-O2 -Wall -threaded -rtsopts -package containers -package haskeline -package directory -package process"

ghc %FLAGS% -o main.exe main.hs
if errorlevel 1 (
    echo Build failed: main.exe
    echo 构建失败：main.exe
    exit /b 1
)
echo Build succeeded: main.exe
echo 构建成功：main.exe

ghc %FLAGS% -o extension.exe extension.hs
if errorlevel 1 (
    echo Build failed: extension.exe
    echo 构建失败：extension.exe
    exit /b 1
)
echo Build succeeded: extension.exe
echo 构建成功：extension.exe

echo All builds finished
echo 全部构建完成

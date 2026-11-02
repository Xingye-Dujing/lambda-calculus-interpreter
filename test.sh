#!/bin/sh
# 编译并运行端到端测试 / build and run the end-to-end tests
set -e
./build.sh
exec python3 tests/run_tests.py "$@"

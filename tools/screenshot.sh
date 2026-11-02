#!/bin/sh
# 为 README 生成浅色截图 / capture light-mode README screenshots
exec python3 "$(dirname "$0")/screenshot.py" "$@"

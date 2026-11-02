@echo off
REM 编译并运行端到端测试 / build and run the end-to-end tests
setlocal
call build.bat || exit /b 1
python tests\run_tests.py %*
exit /b %ERRORLEVEL%

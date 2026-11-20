# 多阶段构建：先在 GHC 镜像里编译 extension，再交给精简的 Python 运行镜像
# Multi-stage build: compile extension in the GHC image, then ship it on slim Python
FROM ghc:9.6 AS builder
WORKDIR /src
COPY extension.hs ./
RUN ghc -O2 -Wall -threaded -rtsopts \
        -package containers -package haskeline -package directory -package process \
        -o extension extension.hs

# 运行阶段：只保留 extension 与 web/，不携带编译工具链
# Runtime stage: keep only the binary and web/, without the compiler toolchain
FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /src/extension /app/extension
COPY web/ /app/web/
COPY lib/ /app/lib/
COPY VERSION /app/VERSION
RUN pip install --no-cache-dir -r web/requirements.txt
ENV LAMBDA_INTERP_DIR=/app \
    HOST=0.0.0.0 \
    PORT=8081 \
    LAMBDA_SHARE_DB=/app/web/shares.json \
    LAMBDA_SNAPSHOT_DB=/app/web/sessions.json \
    LAMBDA_PAGE_DB=/app/web/sharepages.json \
    LAMBDA_TOKEN_DB=/app/web/tokens.json
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8081')+'/api/health', timeout=2)"
# 单进程多线程：会话与解释器子进程都在本进程内
# Single process, multiple threads: sessions and child interpreters live here.
# Shell form so ${PORT} expands at runtime; web/app.py and waitress both honor it.
CMD waitress-serve --listen=0.0.0.0:${PORT} --threads=16 web.app:app

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DIMLAB_DB=/data/cases.db

WORKDIR /app

# 系统依赖（uvicorn[standard] 无需额外编译依赖，保持镜像精简）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 持久化数据目录（SQLite）
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/units > /dev/null || exit 1

# 固定端口 8000，容器内外一致
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

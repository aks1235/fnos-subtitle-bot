# 字幕搜索下载 Bot Dockerfile
# 多阶段构建：uv sync 装依赖 → 复制代码 → 运行

FROM python:3.13-slim AS builder
WORKDIR /app

# 安装 uv
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

# ---- 运行阶段 ----
FROM python:3.13-slim
WORKDIR /app

# 复制虚拟环境和代码
COPY --from=builder /app/.venv /app/.venv
COPY . /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# 媒体挂载点与日志挂载点
VOLUME ["/media/cloud", "/logs"]

CMD ["python", "subtitle_bot.py"]

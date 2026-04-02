FROM python:3.11-slim
WORKDIR /app

# ── 系统工具 + 字体 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 基础工具
    git curl wget jq zip unzip tar tree file htop ripgrep \
    openssh-client rsync \
    # 编译工具链
    build-essential \
    # 媒体
    ffmpeg imagemagick graphviz \
    # 文档
    pandoc \
    # 字体
    fonts-noto-cjk fonts-noto-color-emoji fontconfig \
    # sqlite CLI
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js LTS ──
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Python 包管理 ──
RUN pip install uv --no-cache-dir

# ── 项目依赖 ──
COPY pyproject.toml ./
COPY src/ src/
RUN uv pip install --system .

# ── Playwright + Chromium（含系统依赖） ──
RUN pip install playwright && playwright install --with-deps chromium

# ── Bot 常用 Python 库 ──
RUN uv pip install --system \
    httpx beautifulsoup4 lxml \
    Pillow markdown-it-py Jinja2 \
    pandas openpyxl matplotlib seaborn \
    weasyprint yt-dlp \
    numpy scipy

# ── 扩展 ──
COPY extensions/ extensions/

EXPOSE 8080 8765
ENV PYTHONPATH=/app/src:/app/extensions
CMD ["python", "-m", "acabot.main"]

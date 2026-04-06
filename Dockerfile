# syntax=docker/dockerfile:1.7
FROM python:3.11-slim
ARG TARGETARCH
WORKDIR /app

ARG UV_DEFAULT_INDEX=https://mirrors.cloud.tencent.com/pypi/simple
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG NODE_VERSION=24.14.1
ARG NODE_DIST_MIRROR=https://mirrors.cloud.tencent.com/nodejs-release
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_DEFAULT_TIMEOUT=120

# ── 系统工具 + 字体 ──
RUN sed -i "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g; s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g; s|http://security.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" /etc/apt/sources.list.d/debian.sources
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get -o Acquire::Retries=10 update && apt-get -o Acquire::Retries=10 install -y --no-install-recommends \
    git curl wget jq zip unzip tar tree file htop ripgrep \
    openssh-client rsync \
    build-essential \
    ffmpeg imagemagick graphviz \
    pandoc \
    fonts-noto-cjk fonts-noto-color-emoji fontconfig \
    sqlite3 xz-utils

# ── Node.js LTS（直接下载官方二进制，绕开 NodeSource apt 仓库） ──
RUN --mount=type=cache,target=/var/cache/node-dist,sharing=locked \
    set -eux; \
    case "${TARGETARCH}" in \
        amd64) node_arch='x64' ;; \
        arm64) node_arch='arm64' ;; \
        *) echo "不支持的 Node 架构: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    node_dir="v${NODE_VERSION}"; \
    node_file="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"; \
    node_url="${NODE_DIST_MIRROR}/${node_dir}/${node_file}"; \
    shasums_url="${NODE_DIST_MIRROR}/${node_dir}/SHASUMS256.txt"; \
    curl -fsSL --retry 10 --retry-all-errors --connect-timeout 20 "${node_url}" -o "/var/cache/node-dist/${node_file}"; \
    curl -fsSL --retry 10 --retry-all-errors --connect-timeout 20 "${shasums_url}" -o /tmp/SHASUMS256.txt; \
    (cd /var/cache/node-dist && grep "  ${node_file}$" /tmp/SHASUMS256.txt | sha256sum -c -); \
    tar -xJf "/var/cache/node-dist/${node_file}" -C /usr/local --strip-components=1 --no-same-owner; \
    rm -f /tmp/SHASUMS256.txt; \
    node --version; \
    npm --version

# ── Python 包管理 ──
RUN pip install uv --no-cache-dir --retries 10

# ── 前端依赖与构建 ──
COPY webui/package.json webui/package-lock.json ./webui/
RUN --mount=type=cache,target=/root/.npm \
    npm --prefix webui ci

# ── 项目依赖 ──
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-editable --no-emit-project > /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --requirements /tmp/requirements.txt

COPY src/ src/
COPY webui/ ./webui/
RUN --mount=type=cache,target=/root/.npm \
    npm --prefix webui run build
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-deps .

# ── Playwright browser 安装（依赖已由项目安装） ──
RUN python -m playwright install --with-deps chromium

# ── Bot 常用 Python 库 ──
RUN uv pip install --system \
    httpx beautifulsoup4 lxml \
    Pillow Jinja2 \
    pandas openpyxl matplotlib seaborn \
    weasyprint yt-dlp \
    numpy scipy

# ── 扩展 ──
COPY extensions/ extensions/

EXPOSE 8080 8765
ENV PYTHONPATH=/app/src:/app/extensions
CMD ["python", "-m", "acabot.main"]

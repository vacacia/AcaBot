"""验证 WebUI 源码、构建链路和仓库约束保持一致。"""

from pathlib import Path


def test_webui_build_is_driven_by_source_and_docker() -> None:
    """前端源码应由 Docker 构建到运行时静态目录，而不是手工维护产物。"""

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    vite_config = Path("webui/vite.config.ts").read_text(encoding="utf-8")
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8")

    assert 'outDir: resolve(__dirname, "../src/acabot/webui")' in vite_config
    assert "COPY webui/package.json webui/package-lock.json ./webui/" in dockerfile
    assert "RUN npm --prefix webui ci" in dockerfile
    assert "COPY webui/ ./webui/" in dockerfile
    assert "RUN npm --prefix webui run build" in dockerfile

    assert "src/acabot/webui/index.html" in gitignore
    assert "src/acabot/webui/assets/" in gitignore

    assert "webui/node_modules/" in dockerignore
    assert "src/acabot/webui/assets/" in dockerignore
    assert "src/acabot/webui/index.html" in dockerignore

## Worktree Test Environment

如果新 worktree 里出现下面两种现象:
- `uv run pytest` 大量报 `ModuleNotFoundError: acabot`
- `uv run which pytest` 指向 `/usr/bin/pytest`

优先怀疑是 worktree 的 `.venv` 没装好, 不要先怀疑代码本身.

这次的根因是两层:
1. 没装 `dev` extra, 导致 `.venv` 里没有 pytest
2. `pyproject.toml` 缺少最小 packaging 配置, `uv sync` 后不能稳定把 `src/acabot` 装进环境

下次新 worktree 先做这几步:
```bash
uv sync --extra dev
uv run which pytest
uv run pytest --collect-only -q
```

预期:
- `pytest` 应该指向 `<worktree>/.venv/bin/pytest`
- `collect-only` 能正常收集测试
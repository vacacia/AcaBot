"""runtime.control.prompt_loader 提供 prompt-only 加载接口.

这一层只解决一件事:

- 按 `prompt_ref` 取到 system prompt 文本
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PromptLoader(ABC):
    """system prompt 加载接口."""

    def __call__(self, prompt_ref: str) -> str:
        """允许把 loader 当作普通 callable 使用."""

        return self.load(prompt_ref)

    @abstractmethod
    def load(self, prompt_ref: str) -> str:
        """按 prompt_ref 加载 system prompt 文本."""

        ...


class StaticPromptLoader(PromptLoader):
    """基于内存映射的 prompt loader."""

    def __init__(self, prompts: dict[str, str]) -> None:
        self.prompts = dict(prompts)

    def load(self, prompt_ref: str) -> str:
        return self.prompts[prompt_ref]

    def replace_prompts(self, prompts: dict[str, str]) -> None:
        self.prompts = dict(prompts)


class ChainedPromptLoader(PromptLoader):
    """按顺序回退的 prompt loader."""

    def __init__(self, loaders: list[PromptLoader]) -> None:
        self.loaders = list(loaders)

    def load(self, prompt_ref: str) -> str:
        for loader in self.loaders:
            try:
                return loader.load(prompt_ref)
            except KeyError:
                continue
        raise KeyError(f"Unknown prompt_ref: {prompt_ref}")


class ReloadablePromptLoader(PromptLoader):
    """可在运行时替换底层 loader 的 prompt loader 代理."""

    def __init__(self, loader: PromptLoader) -> None:
        self._loader = loader

    def replace_loader(self, loader: PromptLoader) -> None:
        self._loader = loader

    def load(self, prompt_ref: str) -> str:
        return self._loader.load(prompt_ref)


class FileSystemPromptLoader(PromptLoader):
    """从 `prompts/` 目录加载 prompt 的 loader."""

    def __init__(
        self,
        root: str | Path,
        *,
        extensions: tuple[str, ...] = (".md", ".txt", ".prompt"),
    ) -> None:
        self.root = Path(root)
        self.extensions = tuple(extensions)

    def load(self, prompt_ref: str) -> str:
        path = self._resolve_prompt_path(prompt_ref)
        if path is None:
            raise KeyError(f"Unknown prompt_ref: {prompt_ref}")
        return path.read_text(encoding="utf-8")

    def _resolve_prompt_path(self, prompt_ref: str) -> Path | None:
        # `subagent/*` 已经收口为 SUBAGENT.md 真源, 不再允许被 prompts/ 命名空间覆盖.
        if str(prompt_ref or "").strip().startswith("subagent/"):
            return None
        relative = prompt_ref.removeprefix("prompt/")
        candidate = self.root / relative
        candidates: list[Path] = []
        if candidate.suffix:
            candidates.append(candidate)
        else:
            candidates.extend(candidate.with_suffix(ext) for ext in self.extensions)
            candidates.extend((candidate / f"index{ext}") for ext in self.extensions)
        for path in candidates:
            if path.exists() and path.is_file():
                return path
        return None


__all__ = [
    "ChainedPromptLoader",
    "FileSystemPromptLoader",
    "PromptLoader",
    "ReloadablePromptLoader",
    "StaticPromptLoader",
]

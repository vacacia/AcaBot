"""runtime.render.artifacts 管理 internal render artifacts 路径."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RenderArtifacts:
    """一次 render 任务对应的内部产物路径."""

    root_dir: Path
    artifact_dir: Path
    image_path: Path
    html_path: Path


def render_artifacts(
    *,
    runtime_root: Path | str,
    conversation_id: str,
    run_id: str,
    filename_stem: str = "rendered",
) -> RenderArtifacts:
    """分配 render artifacts 的 internal runtime 路径.

    这里故意固定到 `runtime_data/render_artifacts/...`,
    不复用 `/workspace/attachments` 或 Work World.
    """

    root_dir = Path(runtime_root).expanduser()
    safe_conversation_id = _safe_path_segment(conversation_id, field_name="conversation_id")
    safe_run_id = _safe_path_segment(run_id, field_name="run_id")
    safe_stem = _safe_path_segment(filename_stem, field_name="filename_stem")
    artifact_dir = root_dir / "render_artifacts" / safe_conversation_id / safe_run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return RenderArtifacts(
        root_dir=root_dir,
        artifact_dir=artifact_dir,
        image_path=artifact_dir / f"{safe_stem}.png",
        html_path=artifact_dir / f"{safe_stem}.html",
    )


def _safe_path_segment(value: str, *, field_name: str) -> str:
    """校验单个路径段, 阻止路径穿越."""

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if normalized in {".", ".."}:
        raise ValueError(f"{field_name} cannot be '.' or '..'")
    if "/" in normalized or "\\" in normalized:
        raise ValueError(f"{field_name} cannot contain path separators")
    return normalized

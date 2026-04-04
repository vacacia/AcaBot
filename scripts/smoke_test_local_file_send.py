from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from acabot.config import Config
from acabot.runtime.bootstrap.config import resolve_runtime_path
from acabot.runtime.notification_send_context import workspace_dir_for_conversation

DEFAULT_WEBUI = "http://127.0.0.1:8765"
NAPCAT_CONTAINER = "acabot-napcat"
ACABOT_CONTAINER = "acabot"
LOCAL_FILE_ERROR_MARKERS = (
    "ENOENT",
    "no such file",
    "copyfile",
    "local file unreadable",
    "unreadable",
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def _check_container_running(name: str) -> bool:
    result = _run(["docker", "inspect", "-f", "{{.State.Running}}", name])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _fetch_status(base_url: str) -> tuple[int, dict[str, object]]:
    request = Request(base_url.rstrip("/") + "/api/status", method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return int(exc.code), json.loads(body)
        except json.JSONDecodeError:
            return int(exc.code), {"ok": False, "error": body}
    except URLError as exc:
        return 0, {"ok": False, "error": str(exc)}


def _fetch_json(base_url: str, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    request = Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return int(exc.code), json.loads(body)
        except json.JSONDecodeError:
            return int(exc.code), {"ok": False, "error": body}
    except URLError as exc:
        return 0, {"ok": False, "error": str(exc)}


def _container_runtime_path_for_host(config: Config, path: Path) -> str:
    runtime_root = resolve_runtime_path(config, "")
    relative = path.resolve().relative_to(runtime_root.resolve())
    return str(Path("/app/runtime_data") / relative)


def _generate_png_fixture() -> bytes:
    import struct
    import zlib

    width = 64
    height = 64
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            r = (x * 4) % 256
            g = (y * 4) % 256
            b = 180
            a = 255
            row.extend((r, g, b, a))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(raw, level=9))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def _write_fixture(destination: Path, source_file: Path | None, *, config: Config) -> Path:
    content = source_file.read_bytes() if source_file is not None else _generate_png_fixture()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination
    except PermissionError:
        container_path = _container_runtime_path_for_host(config, destination)
        mkdir_result = _run(["docker", "exec", ACABOT_CONTAINER, "sh", "-lc", f"mkdir -p {Path(container_path).parent}"])
        if mkdir_result.returncode != 0:
            raise RuntimeError(mkdir_result.stderr or mkdir_result.stdout or "docker exec mkdir failed")
        if source_file is not None:
            copy_result = _run(["docker", "cp", str(source_file), f"{ACABOT_CONTAINER}:{container_path}"])
            if copy_result.returncode != 0:
                raise RuntimeError(copy_result.stderr or copy_result.stdout or "docker cp failed")
            return destination
        encoded = base64.b64encode(content).decode("ascii")
        script = (
            "import base64, pathlib; "
            f"p=pathlib.Path({container_path!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_bytes(base64.b64decode({encoded!r}))"
        )
        result = _run(["docker", "exec", ACABOT_CONTAINER, "python", "-c", script])
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "docker exec write failed")
        return destination


def _tail_logs(name: str, since: str) -> str:
    result = _run(["docker", "logs", "--since", since, name])
    combined = (result.stdout or "") + (result.stderr or "")
    return combined.strip()


def _looks_like_local_file_failure(log_text: str) -> bool:
    lowered = log_text.lower()
    return any(marker.lower() in lowered for marker in LOCAL_FILE_ERROR_MARKERS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test local file sending through live acabot + napcat")
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--image", required=True, help="workspace-relative image path")
    parser.add_argument("--source-file", help="optional local source file to copy into workspace")
    parser.add_argument("--text", default="")
    parser.add_argument("--base-url", default=DEFAULT_WEBUI)
    args = parser.parse_args()

    if not _check_container_running(ACABOT_CONTAINER) or not _check_container_running(NAPCAT_CONTAINER):
        print("SKIP/ENV-FAIL: acabot or acabot-napcat container is not running")
        return 2

    status_code, status_body = _fetch_status(args.base_url)
    if status_code != 200 or not status_body.get("ok"):
        print("SKIP/ENV-FAIL: WebUI API is not reachable")
        return 2

    config = Config.from_file()
    workspace_root = workspace_dir_for_conversation(config, args.conversation_id)
    relative_path = Path(args.image)
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        print("FAIL: --image must be a safe workspace-relative path")
        return 1

    source_file = Path(args.source_file).expanduser().resolve() if args.source_file else None
    prepared_file = _write_fixture(workspace_root / relative_path, source_file, config=config)
    since = datetime.now(timezone.utc).isoformat()

    status, body = _fetch_json(
        args.base_url,
        "/api/notifications",
        {
            "conversation_id": args.conversation_id,
            "text": args.text or None,
            "images": [relative_path.as_posix()],
        },
    )
    napcat_logs = _tail_logs(NAPCAT_CONTAINER, since)

    print(json.dumps({
        "prepared_file": str(prepared_file),
        "http_status": status,
        "response": body,
        "napcat_logs": napcat_logs,
    }, ensure_ascii=False, indent=2))

    if status == 0:
        print("SKIP/ENV-FAIL: notification API is unreachable")
        return 2
    if status != 200 or not body.get("ok"):
        error_text = str(body.get("error", "") or "")
        lowered = error_text.lower()
        if any(token in lowered for token in ("no ws connection", "no_ack", "timeout")):
            print("SKIP/ENV-FAIL: acabot is not ready to deliver to NapCat")
            return 2
        print("FAIL: notification API call failed")
        return 1

    ack = dict((body.get("data") or {}).get("ack") or {})
    ack_status = str(ack.get("status", "") or "").lower()
    ack_retcode = ack.get("retcode")
    try:
        ack_ok = ack_status == "ok" and int(ack_retcode) == 0
    except (TypeError, ValueError):
        ack_ok = False

    if not ack_ok:
        print("FAIL: ack did not indicate success")
        return 1
    if _looks_like_local_file_failure(napcat_logs):
        print("FAIL: napcat logs show local file read failure")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

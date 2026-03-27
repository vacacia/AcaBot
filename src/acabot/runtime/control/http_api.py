"""runtime.http_api 提供本地 WebUI / control plane 的 HTTP 入口."""

from __future__ import annotations

import asyncio
from dataclasses import fields, is_dataclass
import json
import mimetypes
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from acabot.config import Config

from .control_plane import RuntimeControlPlane
from ..references import ReferenceDocumentInput


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        data: dict[str, Any] = {}
        for field in fields(value):
            if field.name == "lock":
                continue
            data[field.name] = _to_jsonable(getattr(value, field.name))
        return data
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_to_jsonable(item) for item in sorted(value)]
    if isinstance(value, Path):
        return str(value)
    return value


def _query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    if not values:
        return default
    return str(values[-1] or default)


def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
    raw = _query_value(query, key, "")
    if not raw:
        return default
    return int(raw)


def _query_float(query: dict[str, list[str]], key: str, default: float) -> float:
    raw = _query_value(query, key, "")
    if not raw:
        return default
    return float(raw)


def _query_bool(query: dict[str, list[str]], key: str, default: bool = False) -> bool:
    raw = _query_value(query, key, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class RuntimeHttpApiServer:
    """本地单机 HTTP server, 暴露 control plane API 并可选托管静态 WebUI."""

    def __init__(
        self,
        *,
        config: Config,
        control_plane: RuntimeControlPlane,
    ) -> None:
        runtime_conf = config.get("runtime", {})
        webui_conf = dict(runtime_conf.get("webui", {}) or {})
        self.enabled = bool(webui_conf.get("enabled", False))
        self.host = str(webui_conf.get("host", "127.0.0.1") or "127.0.0.1")
        self.port = int(webui_conf.get("port", 8765))
        self.request_timeout_sec = float(webui_conf.get("request_timeout_sec", 30.0))
        self.cors_origins = [
            str(item)
            for item in list(
                webui_conf.get(
                    "cors_origins",
                    [
                        "http://127.0.0.1:5173",
                        "http://localhost:5173",
                    ],
                )
                or []
            )
        ]
        # 踩坑记录：`http_api.py` 位于 `src/acabot/runtime/control/`，这里如果只写
        # `parent.parent / "webui"` 会错误指向 `src/acabot/runtime/webui`，导致 WebUI
        # 明明存在却被判成 `static files unavailable`。真正的默认静态目录是
        # `src/acabot/webui`。
        static_default = Path(__file__).resolve().parent.parent.parent / "webui"
        static_dir = Path(str(webui_conf.get("static_dir", static_default) or static_default))
        self.static_dir = static_dir if static_dir.exists() else None
        self.config = config
        self.control_plane = control_plane
        self._loop: asyncio.AbstractEventLoop | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    async def start(self) -> None:
        if not self.enabled or self._httpd is not None:
            return
        self._loop = asyncio.get_running_loop()
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AcaBotWebUI/0.1"

            def do_OPTIONS(self) -> None:
                self._write_empty(204)

            def do_GET(self) -> None:
                self._dispatch("GET")

            def do_POST(self) -> None:
                self._dispatch("POST")

            def do_PUT(self) -> None:
                self._dispatch("PUT")

            def do_DELETE(self) -> None:
                self._dispatch("DELETE")

            def log_message(self, fmt: str, *args: object) -> None:
                return None

            def _dispatch(self, method: str) -> None:
                split = urlsplit(self.path)
                if split.path.startswith("/api/"):
                    self._dispatch_api(method, split)
                    return
                self._dispatch_static(split.path)

            def _dispatch_api(self, method: str, split) -> None:
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                    payload: dict[str, Any] = {}
                    if length > 0:
                        raw = self.rfile.read(length)
                        if raw:
                            payload = json.loads(raw.decode("utf-8"))
                    query = parse_qs(split.query, keep_blank_values=True)
                    status, result = server.handle_api_request(
                        method=method,
                        path=split.path,
                        query=query,
                        payload=payload,
                    )
                except KeyError as exc:
                    status, result = 404, {"ok": False, "error": f"not found: {exc}"}
                except ValueError as exc:
                    status, result = 400, {"ok": False, "error": str(exc)}
                except Exception as exc:  # pragma: no cover - 兜底保护
                    status, result = 500, {"ok": False, "error": str(exc)}
                self._write_json(status, result)

            def _dispatch_static(self, raw_path: str) -> None:
                if server.static_dir is None:
                    self._write_json(404, {"ok": False, "error": "webui static files unavailable"})
                    return
                relative = raw_path.lstrip("/") or "index.html"
                safe_path = (server.static_dir / relative).resolve()
                try:
                    safe_path.relative_to(server.static_dir.resolve())
                except ValueError:
                    self._write_json(403, {"ok": False, "error": "forbidden"})
                    return
                if not safe_path.exists() or safe_path.is_dir():
                    safe_path = server.static_dir / "index.html"
                if not safe_path.exists():
                    self._write_json(404, {"ok": False, "error": "index.html not found"})
                    return
                content_type, _ = mimetypes.guess_type(str(safe_path))
                body = safe_path.read_bytes()
                self.send_response(200)
                self._write_cors_headers()
                self.send_header("Content-Type", content_type or "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _write_empty(self, status: int) -> None:
                self.send_response(status)
                self._write_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _write_json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._write_cors_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _write_cors_headers(self) -> None:
                origin = str(self.headers.get("Origin", "") or "")
                if origin and origin in server.cors_origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
                elif server.cors_origins:
                    self.send_header("Access-Control-Allow-Origin", server.cors_origins[0])
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = Thread(target=self._httpd.serve_forever, name="acabot-webui", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._httpd = None

    def handle_api_request(
        self,
        *,
        method: str,
        path: str,
        query: dict[str, list[str]],
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        segments = [unquote(part) for part in path.split("/") if part][1:]

        if segments == ["meta"] and method == "GET":
            return 200, {
                "ok": True,
                "data": {
                    "storage_mode": getattr(self.control_plane.config_control_plane, "storage_mode", lambda: "none")(),
                    "config_path": self.config.path or "config.yaml",
                    "webui_enabled": self.enabled,
                    "static_dir": str(self.static_dir) if self.static_dir is not None else "",
                },
            }
        if segments == ["ui", "catalog"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_ui_catalog()))
        if segments == ["status"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_status()))
        if segments == ["backend", "status"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_backend_status()))
        if segments == ["backend", "session-binding"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_backend_session_binding()))
        if segments == ["backend", "session-path"] and method == "GET":
            return self._ok({"path": self._await(self.control_plane.get_backend_session_path())})
        if segments == ["gateway", "config"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_gateway_config()))
        if segments == ["gateway", "status"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_gateway_status()))
        if segments == ["gateway", "config"] and method == "PUT":
            return self._ok(self._await(self.control_plane.upsert_gateway_config(payload)))
        if segments == ["approvals"] and method == "GET":
            status = self._await(self.control_plane.get_status())
            return self._ok(status.pending_approvals)
        if segments == ["approvals", "approve"] and method == "POST":
            result = self._await(
                self.control_plane.approve_pending_approval(
                    run_id=str(payload.get("run_id", "") or ""),
                    metadata=dict(payload.get("metadata", {}) or {}),
                )
            )
            return self._ok(result)
        if segments == ["approvals", "reject"] and method == "POST":
            result = self._await(
                self.control_plane.reject_pending_approval(
                    run_id=str(payload.get("run_id", "") or ""),
                    reason=str(payload.get("reason", "approval rejected") or "approval rejected"),
                    metadata=dict(payload.get("metadata", {}) or {}),
                )
            )
            return self._ok(result)
        if segments == ["plugins"] and method == "GET":
            status = self._await(self.control_plane.get_status())
            return self._ok({"loaded_plugins": status.loaded_plugins})
        if segments == ["plugins", "reload"] and method == "POST":
            return self._ok(
                self._await(
                    self.control_plane.reload_plugins(
                        [str(item) for item in list(payload.get("plugin_names", []) or [])]
                    )
                )
            )
        if segments == ["system", "logs"] and method == "GET":
            return self._ok(
                self._await(
                    self.control_plane.list_recent_logs(
                        after_seq=_query_int(query, "after_seq", 0),
                        level=_query_value(query, "level", ""),
                        keyword=_query_value(query, "keyword", ""),
                        limit=_query_int(query, "limit", 500),
                    )
                )
            )
        if segments == ["system", "plugins", "config"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_plugin_configs()))
        if segments == ["system", "plugins", "config"] and method == "PUT":
            return self._ok(
                self._await(
                    self.control_plane.replace_plugin_configs(
                        [dict(item) for item in list(payload.get("items", []) or [])]
                    )
                )
            )
        if segments == ["soul", "files"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_soul_files()))
        if segments == ["soul", "file"] and method == "GET":
            name = _query_value(query, "name", "") or _query_value(query, "path", "")
            return self._ok(self._await(self.control_plane.get_soul_file(name=name)))
        if segments == ["soul", "file"] and method == "PUT":
            return self._ok(
                self._await(
                    self.control_plane.put_soul_file(
                        name=str(payload.get("name", "") or payload.get("path", "") or ""),
                        content=str(payload.get("content", "") or ""),
                    )
                )
            )
        if segments == ["soul", "files"] and method == "POST":
            return self._ok(
                self._await(
                    self.control_plane.post_soul_file(
                        name=str(payload.get("name", "") or payload.get("path", "") or ""),
                        content=str(payload.get("content", "") or ""),
                    )
                )
            )
        if segments == ["self", "files"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_self_files()))
        if segments == ["self", "file"] and method == "GET":
            name = _query_value(query, "name", "") or _query_value(query, "path", "")
            return self._ok(self._await(self.control_plane.get_self_file(name=name)))
        if segments == ["self", "file"] and method == "PUT":
            return self._ok(
                self._await(
                    self.control_plane.put_self_file(
                        name=str(payload.get("name", "") or payload.get("path", "") or ""),
                        content=str(payload.get("content", "") or ""),
                    )
                )
            )
        if segments == ["self", "files"] and method == "POST":
            return self._ok(
                self._await(
                    self.control_plane.post_self_file(
                        name=str(payload.get("name", "") or payload.get("path", "") or ""),
                        content=str(payload.get("content", "") or ""),
                    )
                )
            )
        if segments == ["memory", "sticky-notes"] and method == "GET":
            return self._ok(
                self._await(
                    self.control_plane.list_sticky_notes(
                        entity_kind=_query_value(query, "entity_kind", ""),
                    )
                )
            )
        if segments == ["memory", "sticky-notes", "item"] and method == "GET":
            result = self._await(
                self.control_plane.get_sticky_note_record(
                    entity_ref=_query_value(query, "entity_ref", ""),
                )
            )
            if result is None:
                return 404, {"ok": False, "error": "sticky note not found"}
            return self._ok(result)
        if segments == ["memory", "sticky-notes", "item"] and method == "PUT":
            return self._ok(
                self._await(
                    self.control_plane.save_sticky_note_record(
                        entity_ref=str(payload.get("entity_ref", "") or ""),
                        readonly=str(payload.get("readonly", "") or ""),
                        editable=str(payload.get("editable", "") or ""),
                    )
                )
            )
        if segments == ["memory", "sticky-notes", "item"] and method == "POST":
            return self._ok(
                self._await(
                    self.control_plane.create_sticky_note(
                        entity_ref=str(payload.get("entity_ref", "") or ""),
                    )
                )
            )
        if segments == ["memory", "sticky-notes", "item"] and method == "DELETE":
            deleted = self._await(
                self.control_plane.delete_sticky_note(
                    entity_ref=_query_value(query, "entity_ref", ""),
                )
            )
            if not deleted:
                return 404, {"ok": False, "error": "sticky note not found"}
            return self._ok({"deleted": True})
        if segments == ["sessions"] and method == "GET":
            return 501, {"ok": False, "error": "session shell redesign pending"}
        if len(segments) == 2 and segments[0] == "sessions" and method == "GET":
            return 501, {"ok": False, "error": "session shell redesign pending"}
        if len(segments) == 2 and segments[0] == "sessions" and method == "PUT":
            return 501, {"ok": False, "error": "session shell redesign pending"}
        if segments == ["skills"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_skills()))
        if len(segments) == 3 and segments[0] == "agents" and segments[2] == "skills" and method == "GET":
            return self._ok(self._await(self.control_plane.list_agent_skills(segments[1])))
        if segments == ["subagents", "executors"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_subagent_executors()))

        if segments == ["bot"] and method == "GET":
            return 501, {"ok": False, "error": "bot shell redesign pending"}
        if segments == ["bot"] and method == "PUT":
            return 501, {"ok": False, "error": "bot shell redesign pending"}
        if segments == ["admins"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_admins()))
        if segments == ["admins"] and method == "PUT":
            return self._ok(self._await(self.control_plane.put_admins(payload=payload)))

        if segments == ["profiles"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_profiles()))
        if len(segments) == 2 and segments[0] == "profiles":
            agent_id = segments[1]
            if method == "GET":
                result = self._await(self.control_plane.get_profile(agent_id))
                if result is None:
                    return 404, {"ok": False, "error": "profile not found"}
                return self._ok(result)
            if method == "PUT":
                return self._ok(self._await(self.control_plane.upsert_profile({**payload, "agent_id": agent_id})))
            if method == "DELETE":
                deleted = self._await(self.control_plane.delete_profile(agent_id))
                if not deleted:
                    return 404, {"ok": False, "error": "profile not found"}
                return self._ok({"deleted": True})

        if segments == ["prompts"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_prompts()))
        if segments == ["prompt"]:
            prompt_ref = _query_value(query, "prompt_ref", "")
            if method == "GET":
                result = self._await(self.control_plane.get_prompt(prompt_ref))
                if result is None:
                    return 404, {"ok": False, "error": "prompt not found"}
                return self._ok(result)
            if method == "PUT":
                return self._ok(
                    self._await(
                        self.control_plane.upsert_prompt(
                            prompt_ref=prompt_ref,
                            content=str(payload.get("content", "") or ""),
                        )
                    )
                )
            if method == "DELETE":
                deleted = self._await(self.control_plane.delete_prompt(prompt_ref))
                if not deleted:
                    return 404, {"ok": False, "error": "prompt not found"}
                return self._ok({"deleted": True})

        if segments == ["runtime", "reload-config"] and method == "POST":
            return self._ok(self._await(self.control_plane.reload_runtime_configuration()))
        if segments == ["runtime", "threads"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_threads(limit=_query_int(query, "limit", 100))))
        if len(segments) >= 3 and segments[0] == "runtime" and segments[1] == "threads":
            thread_id = segments[2]
            if len(segments) == 3 and method == "GET":
                result = self._await(self.control_plane.get_thread(thread_id))
                if result is None:
                    return 404, {"ok": False, "error": "thread not found"}
                return self._ok(result)
            if len(segments) == 4 and segments[3] == "steps" and method == "GET":
                return self._ok(
                    self._await(
                        self.control_plane.list_workspace_activity(
                            thread_id=thread_id,
                            limit=_query_int(query, "limit", 100),
                            step_types=query.get("step_type"),
                        )
                    )
                )
            if len(segments) == 4 and segments[3] == "events" and method == "GET":
                return self._ok(
                    self._await(
                        self.control_plane.list_thread_events(
                            thread_id=thread_id,
                            limit=_query_int(query, "limit", 100),
                            since=int(_query_value(query, "since", "0") or 0) or None,
                            event_types=query.get("event_type"),
                        )
                    )
                )
            if len(segments) == 4 and segments[3] == "messages" and method == "GET":
                return self._ok(
                    self._await(
                        self.control_plane.list_thread_messages(
                            thread_id=thread_id,
                            limit=_query_int(query, "limit", 100),
                            since=int(_query_value(query, "since", "0") or 0) or None,
                        )
                    )
                )

        if segments == ["runtime", "runs"] and method == "GET":
            statuses = [item for item in query.get("status", []) if item]
            thread_id = _query_value(query, "thread_id", "") or None
            return self._ok(
                self._await(
                    self.control_plane.list_runs(
                        limit=_query_int(query, "limit", 100),
                        statuses=statuses,
                        thread_id=thread_id,
                    )
                )
            )
        if len(segments) >= 3 and segments[0] == "runtime" and segments[1] == "runs":
            run_id = segments[2]
            if len(segments) == 3 and method == "GET":
                result = self._await(self.control_plane.get_run(run_id))
                if result is None:
                    return 404, {"ok": False, "error": "run not found"}
                return self._ok(result)
            if len(segments) == 4 and segments[3] == "steps" and method == "GET":
                return self._ok(
                    self._await(
                        self.control_plane.list_run_steps(
                            run_id=run_id,
                            limit=_query_int(query, "limit", 100),
                            step_types=query.get("step_type"),
                        )
                    )
                )

        if len(segments) >= 2 and segments[0] == "models":
            return self._handle_models(method=method, segments=segments[1:], query=query, payload=payload)

        if segments == ["workspaces"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_workspaces()))
        if len(segments) >= 2 and segments[0] == "workspaces":
            return self._handle_workspaces(method=method, segments=segments[1:], query=query, payload=payload)

        if len(segments) >= 2 and segments[0] == "references":
            return self._handle_references(method=method, segments=segments[1:], query=query, payload=payload)

        return 404, {"ok": False, "error": f"unknown endpoint: {path}"}

    def _handle_models(
        self,
        *,
        method: str,
        segments: list[str],
        query: dict[str, list[str]],
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        if segments == ["status"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_model_registry_status()))
        if segments == ["reload"] and method == "POST":
            return self._ok(self._await(self.control_plane.reload_models()))
        if segments == ["targets"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_model_targets()))
        if len(segments) == 2 and segments[0] == "targets" and method == "GET":
            result = self._await(self.control_plane.get_model_target(segments[1]))
            if result is None:
                return 404, {"ok": False, "error": "target not found"}
            return self._ok(result)
        if len(segments) == 3 and segments[0] == "targets" and segments[2] == "effective" and method == "GET":
            return self._ok(self._await(self.control_plane.preview_effective_target_model(segments[1])))
        if segments == ["providers"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_model_providers()))
        if len(segments) == 2 and segments[0] == "providers":
            provider_id = segments[1]
            if method == "GET":
                result = self._await(self.control_plane.get_model_provider(provider_id))
                if result is None:
                    return 404, {"ok": False, "error": "provider not found"}
                return self._ok(result)
            if method == "PUT":
                model = payload
                model["provider_id"] = provider_id
                existing = self._await(self.control_plane.get_model_provider(provider_id))
                return self._ok(
                    self._await(
                        self.control_plane.upsert_model_provider(
                            _model_provider_from_payload(model, existing=existing)
                        )
                    )
                )
            if method == "DELETE":
                return self._ok(
                    self._await(
                        self.control_plane.delete_model_provider(
                            provider_id,
                            force=_query_bool(query, "force", False),
                        )
                    )
                )
        if len(segments) == 3 and segments[0] == "providers" and segments[2] == "impact" and method == "GET":
            return self._ok(self._await(self.control_plane.get_model_provider_impact(segments[1])))

        if segments == ["presets"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_model_presets()))
        if len(segments) == 2 and segments[0] == "presets":
            preset_id = segments[1]
            if method == "GET":
                result = self._await(self.control_plane.get_model_preset(preset_id))
                if result is None:
                    return 404, {"ok": False, "error": "preset not found"}
                return self._ok(result)
            if method == "PUT":
                model = dict(payload)
                model["preset_id"] = preset_id
                return self._ok(self._await(self.control_plane.upsert_model_preset(_model_preset_from_payload(model))))
            if method == "DELETE":
                return self._ok(
                    self._await(
                        self.control_plane.delete_model_preset(
                            preset_id,
                            force=_query_bool(query, "force", False),
                        )
                    )
                )
        if len(segments) == 3 and segments[0] == "presets" and segments[2] == "impact" and method == "GET":
            return self._ok(self._await(self.control_plane.get_model_preset_impact(segments[1])))
        if len(segments) == 3 and segments[0] == "presets" and segments[2] == "health-check" and method == "POST":
            return self._ok(self._await(self.control_plane.health_check_model_preset(segments[1])))

        if segments == ["bindings"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_model_bindings()))
        if len(segments) == 2 and segments[0] == "bindings":
            binding_id = segments[1]
            if method == "GET":
                result = self._await(self.control_plane.get_model_binding(binding_id))
                if result is None:
                    return 404, {"ok": False, "error": "binding not found"}
                return self._ok(result)
            if method == "PUT":
                model = dict(payload)
                model["binding_id"] = binding_id
                return self._ok(self._await(self.control_plane.upsert_model_binding(_model_binding_from_payload(model))))
            if method == "DELETE":
                return self._ok(self._await(self.control_plane.delete_model_binding(binding_id)))
        if len(segments) == 3 and segments[0] == "bindings" and segments[2] == "impact" and method == "GET":
            return self._ok(self._await(self.control_plane.get_model_binding_impact(segments[1])))

        return 404, {"ok": False, "error": "unknown model endpoint"}

    def _handle_workspaces(
        self,
        *,
        method: str,
        segments: list[str],
        query: dict[str, list[str]],
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        thread_id = segments[0]
        if len(segments) == 2 and segments[1] == "attachments" and method == "GET":
            return self._ok(self._await(self.control_plane.list_workspace_attachments(thread_id=thread_id)))
        if len(segments) == 2 and segments[1] == "sessions" and method == "GET":
            return self._ok(self._await(self.control_plane.list_workspace_sessions(thread_id=thread_id)))
        if len(segments) == 2 and segments[1] == "sandbox" and method == "GET":
            return self._ok(self._await(self.control_plane.get_sandbox_status(thread_id=thread_id)))
        if len(segments) == 2 and segments[1] == "prune" and method == "POST":
            return self._ok(
                self._await(
                    self.control_plane.prune_workspace(
                        thread_id=thread_id,
                        force=bool(payload.get("force", False)),
                    )
                )
            )
        if len(segments) == 2 and segments[1] == "stop-sandbox" and method == "POST":
            return self._ok(
                self._await(
                    self.control_plane.stop_workspace_sandbox(
                        thread_id=thread_id,
                        force=bool(payload.get("force", False)),
                    )
                )
            )
        return 404, {"ok": False, "error": "unknown workspace endpoint"}

    def _handle_references(
        self,
        *,
        method: str,
        segments: list[str],
        query: dict[str, list[str]],
        payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        if segments == ["spaces"] and method == "GET":
            tenant_id = _query_value(query, "tenant_id", "") or None
            mode = _query_value(query, "mode", "") or None
            return self._ok(
                self._await(
                    self.control_plane.list_reference_spaces(
                        tenant_id=tenant_id,
                        mode=mode or None,
                    )
                )
            )
        if segments == ["search"] and method == "GET":
            return self._ok(
                self._await(
                    self.control_plane.search_reference(
                        query=_query_value(query, "query", ""),
                        tenant_id=_query_value(query, "tenant_id", ""),
                        space_id=_query_value(query, "space_id", "") or None,
                        mode=_query_value(query, "mode", "") or None,
                        limit=_query_int(query, "limit", 10),
                        body=_query_value(query, "body", "none") or "none",
                        min_score=_query_float(query, "min_score", 0.0),
                    )
                )
            )
        if segments == ["document"] and method == "GET":
            result = self._await(
                self.control_plane.get_reference_document(
                    ref_id=_query_value(query, "ref_id", ""),
                    tenant_id=_query_value(query, "tenant_id", ""),
                    body=_query_value(query, "body", "full") or "full",
                )
            )
            if result is None:
                return 404, {"ok": False, "error": "reference document not found"}
            return self._ok(result)
        if segments == ["documents"] and method == "POST":
            documents = [
                ReferenceDocumentInput(
                    title=str(item.get("title", "") or ""),
                    body=str(item.get("body", "") or ""),
                    source_uri=str(item.get("source_uri", "") or ""),
                    tags=[str(tag) for tag in list(item.get("tags", []) or [])],
                    metadata=dict(item.get("metadata", {}) or {}),
                )
                for item in list(payload.get("documents", []) or [])
            ]
            return self._ok(
                self._await(
                    self.control_plane.add_reference_documents(
                        tenant_id=str(payload.get("tenant_id", "") or ""),
                        space_id=str(payload.get("space_id", "") or ""),
                        mode=str(payload.get("mode", "readonly_reference") or "readonly_reference"),
                        documents=documents,
                    )
                )
            )
        return 404, {"ok": False, "error": "unknown reference endpoint"}

    def _ok(self, data: Any) -> tuple[int, dict[str, Any]]:
        return 200, {"ok": True, "data": _to_jsonable(data)}

    def _await(self, awaitable):
        if self._loop is None:
            raise RuntimeError("http api server is not started")
        future = asyncio.run_coroutine_threadsafe(awaitable, self._loop)
        return future.result(timeout=self.request_timeout_sec)


def _model_provider_from_payload(
    payload: dict[str, Any],
    *,
    existing=None,
):
    from ..model.model_registry import (
        AnthropicProviderConfig,
        GoogleGeminiProviderConfig,
        ModelProvider,
        OpenAICompatibleProviderConfig,
        _normalize_provider_auth_fields,
    )

    existing_config = {}
    if existing is not None:
        existing_config = dict(existing.to_dict())
    normalized = {
        **dict(existing_config.get("config", {}) or {}),
        **{
            key: value
            for key, value in dict(existing_config).items()
            if key not in {"provider_id", "kind"}
        },
        **dict(payload.get("config", {}) or {}),
        **dict(payload),
    }
    kind = str(normalized.get("kind", "") or "")
    provider_id = str(normalized.get("provider_id", "") or "")
    api_key_env, api_key = _normalize_provider_auth_fields(
        api_key_env=str(normalized.get("api_key_env", "") or ""),
        api_key=str(normalized.get("api_key", "") or ""),
    )
    if kind == "openai_compatible":
        config = OpenAICompatibleProviderConfig(
            base_url=str(normalized.get("base_url", "") or ""),
            api_key_env=api_key_env,
            api_key=api_key,
            default_headers=dict(normalized.get("default_headers", {}) or {}),
            default_query=dict(normalized.get("default_query", {}) or {}),
            default_body=dict(normalized.get("default_body", {}) or {}),
        )
    elif kind == "anthropic":
        config = AnthropicProviderConfig(
            api_key_env=api_key_env,
            api_key=api_key,
            base_url=str(normalized.get("base_url", "") or ""),
            anthropic_version=str(normalized.get("anthropic_version", "") or ""),
            default_headers=dict(normalized.get("default_headers", {}) or {}),
            default_query=dict(normalized.get("default_query", {}) or {}),
            default_body=dict(normalized.get("default_body", {}) or {}),
        )
    elif kind == "google_gemini":
        config = GoogleGeminiProviderConfig(
            api_key_env=api_key_env,
            api_key=api_key,
            base_url=str(normalized.get("base_url", "") or ""),
            api_version=str(normalized.get("api_version", "") or ""),
            project_id=str(normalized.get("project_id", "") or ""),
            location=str(normalized.get("location", "") or ""),
            use_vertex_ai=bool(normalized.get("use_vertex_ai", False)),
            default_headers=dict(normalized.get("default_headers", {}) or {}),
            default_query=dict(normalized.get("default_query", {}) or {}),
            default_body=dict(normalized.get("default_body", {}) or {}),
        )
    else:
        raise ValueError(f"unsupported provider kind: {kind}")
    return ModelProvider(
        provider_id=provider_id,
        kind=kind,
        config=config,
        name=str(normalized.get("name", "") or provider_id),
    )


def _model_preset_from_payload(payload: dict[str, Any]):
    from ..model.model_registry import ModelPreset

    capabilities = payload.get("capabilities")
    if capabilities is None:
        capabilities = [
            capability
            for capability, enabled in (
                ("tool_calling", payload.get("supports_tools", True)),
                ("image_input", payload.get("supports_vision", False)),
            )
            if enabled
        ]
    return ModelPreset(
        preset_id=str(payload.get("preset_id", "") or ""),
        provider_id=str(payload.get("provider_id", "") or ""),
        model=str(payload.get("model", "") or ""),
        task_kind=str(payload.get("task_kind", payload.get("capability", "")) or ""),
        context_window=int(payload.get("context_window", 0) or 0),
        capabilities=[str(item) for item in list(capabilities or [])],
        max_output_tokens=(
            int(payload["max_output_tokens"])
            if payload.get("max_output_tokens") not in (None, "")
            else None
        ),
        model_params=dict(payload.get("model_params", {}) or {}),
    )


def _model_binding_from_payload(payload: dict[str, Any]):
    from ..model.model_registry import ModelBinding

    timeout_sec = payload.get("timeout_sec")
    return ModelBinding(
        binding_id=str(payload.get("binding_id", "") or ""),
        target_id=str(payload.get("target_id", "") or ""),
        preset_ids=[str(item) for item in list(payload.get("preset_ids", []) or [])],
        timeout_sec=float(timeout_sec) if timeout_sec not in (None, "") else None,
    )

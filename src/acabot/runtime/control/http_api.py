"""runtime.http_api 提供本地 WebUI / control plane 的 HTTP 入口."""

from __future__ import annotations

import asyncio
from dataclasses import fields, is_dataclass
import json
import logging
import mimetypes
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from acabot.config import Config

from .control_plane import RuntimeControlPlane
from ..scheduler.service import ScheduledTaskConflictError, ScheduledTaskUnavailableError

logger = logging.getLogger("acabot.runtime.http_api")


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


def _entry_to_dict(entry: Any) -> dict[str, Any]:
    """把 MemoryEntry 序列化成 JSON 安全的字典."""
    return {
        "entry_id": entry.entry_id,
        "conversation_id": entry.conversation_id,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "topic": entry.topic,
        "lossless_restatement": entry.lossless_restatement,
        "keywords": entry.keywords,
        "persons": entry.persons,
        "entities": entry.entities,
        "location": entry.location,
        "time_point": entry.time_point,
        "time_interval_start": entry.time_interval_start,
        "time_interval_end": entry.time_interval_end,
        "extractor_version": entry.extractor_version,
        "provenance": {"fact_ids": entry.provenance.fact_ids},
    }


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
        self.allow_synthetic_events = bool(webui_conf.get("allow_synthetic_events", False))
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
            protocol_version = "HTTP/1.1"  # 启用持久连接，避免每次请求都重新建立 TCP 连接

            def address_string(self) -> str:
                return str(self.client_address[0])

            def do_OPTIONS(self) -> None:
                self._write_empty(204)

            def do_HEAD(self) -> None:
                self._dispatch("HEAD")

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
                route_method = "GET" if method == "HEAD" else method
                if split.path.startswith("/api/"):
                    self._dispatch_api(route_method, split)
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
                        remote_addr=str(self.client_address[0] or ""),
                    )
                except KeyError as exc:
                    status, result = 404, {"ok": False, "error": f"not found: {exc}"}
                except FileNotFoundError as exc:
                    status, result = 404, {"ok": False, "error": str(exc)}
                except ScheduledTaskConflictError as exc:
                    status, result = 409, {"ok": False, "error": str(exc)}
                except ScheduledTaskUnavailableError as exc:
                    status, result = 503, {"ok": False, "error": str(exc)}
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
                if self.command != "HEAD":
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
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _write_cors_headers(self) -> None:
                origin = str(self.headers.get("Origin", "") or "")
                if origin and origin in server.cors_origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
                elif server.cors_origins:
                    self.send_header("Access-Control-Allow-Origin", server.cors_origins[0])
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
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
        remote_addr: str = "",
    ) -> tuple[int, dict[str, Any]]:
        segments = [unquote(part) for part in path.split("/") if part][1:]

        if segments == ["meta"] and method == "GET":
            return 200, {
                "ok": True,
                "data": {
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
        if segments == ["render", "config"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_render_config()))
        if segments == ["render", "config"] and method == "PUT":
            return self._ok(self._await(self.control_plane.upsert_render_config(payload)))
        if segments == ["filesystem", "config"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_filesystem_scan_config()))
        if segments == ["filesystem", "config"] and method == "PUT":
            return self._ok(self._await(self.control_plane.upsert_filesystem_scan_config(payload)))
        if segments == ["system", "configuration"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_system_configuration_view()))
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
        if segments == ["system", "plugins"] and method == "GET":
            return self._ok({"plugins": self.control_plane.list_plugins()})
        if len(segments) == 3 and segments[0] == "system" and segments[1] == "plugins" and method == "GET":
            plugin_id = segments[2]
            result = self.control_plane.get_plugin(plugin_id)
            if result is None:
                return 404, {"ok": False, "error": f"plugin not found: {plugin_id}"}
            return self._ok(result)
        if len(segments) == 4 and segments[:2] == ["system", "plugins"] and segments[3] == "spec" and method == "PUT":
            plugin_id = segments[2]
            return self._ok(self._await(
                self.control_plane.update_plugin_spec(
                    plugin_id,
                    enabled=bool(payload.get("enabled", False)),
                    config=dict(payload.get("config", {}) or {}),
                )
            ))
        if len(segments) == 4 and segments[:2] == ["system", "plugins"] and segments[3] == "spec" and method == "DELETE":
            plugin_id = segments[2]
            return self._ok(self._await(self.control_plane.delete_plugin_spec(plugin_id)))
        if segments == ["system", "plugins", "reconcile"] and method == "POST":
            return self._ok({"plugins": self._await(self.control_plane.reconcile_all_plugins())})
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
        if segments == ["memory", "long-term", "config"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_long_term_memory_config()))
        if segments == ["memory", "long-term", "config"] and method == "PUT":
            return self._ok(self._await(self.control_plane.upsert_long_term_memory_config(payload)))
        if segments == ["memory", "long-term", "stats"] and method == "GET":
            store = self._get_ltm_store()
            if store is None:
                return 404, {"ok": False, "error": "LTM not configured"}
            return self._ok(store.get_stats())
        if segments == ["memory", "long-term", "entries"] and method == "GET":
            store = self._get_ltm_store()
            if store is None:
                return 404, {"ok": False, "error": "LTM not configured"}
            offset = int(_query_value(query, "offset", "0"))
            limit = min(int(_query_value(query, "limit", "50")), 200)
            date_start = _query_value(query, "date_start", "")
            date_end = _query_value(query, "date_end", "")
            entries, total = store.list_entries(
                offset=offset,
                limit=limit,
                conversation_id=_query_value(query, "conversation_id"),
                keyword=_query_value(query, "keyword"),
                person=_query_value(query, "person"),
                entity=_query_value(query, "entity"),
                date_start=date_start,
                date_end=date_end,
            )
            return self._ok({
                "entries": [_entry_to_dict(e) for e in entries],
                "total": total,
                "offset": offset,
                "limit": limit,
            })
        if segments == ["memory", "long-term", "entries"] and method == "DELETE":
            store = self._get_ltm_store()
            if store is None:
                return 404, {"ok": False, "error": "LTM not configured"}
            conversation_id = _query_value(query, "conversation_id", "")
            if not conversation_id:
                return 400, {"ok": False, "error": "conversation_id query param required"}
            deleted = store.delete_entries_by_conversation(conversation_id)
            return self._ok({"deleted_count": deleted, "conversation_id": conversation_id})
        if len(segments) == 4 and segments[:3] == ["memory", "long-term", "entries"]:
            entry_id = segments[3]
            store = self._get_ltm_store()
            if store is None:
                return 404, {"ok": False, "error": "LTM not configured"}
            if method == "GET":
                entry = store.get_entry(entry_id)
                if entry is None:
                    return 404, {"ok": False, "error": "entry not found"}
                return self._ok(_entry_to_dict(entry))
            if method == "PUT":
                entry = store.get_entry(entry_id)
                if entry is None:
                    return 404, {"ok": False, "error": "entry not found"}
                kwargs: dict[str, Any] = {}
                if "topic" in payload:
                    kwargs["topic"] = str(payload["topic"] or "")
                if "lossless_restatement" in payload:
                    kwargs["lossless_restatement"] = str(payload["lossless_restatement"] or "")
                if "keywords" in payload:
                    kwargs["keywords"] = [str(k) for k in (payload["keywords"] or [])]
                if "persons" in payload:
                    kwargs["persons"] = [str(p) for p in (payload["persons"] or [])]
                if "entities" in payload:
                    kwargs["entities"] = [str(e) for e in (payload["entities"] or [])]
                if "location" in payload:
                    kwargs["location"] = payload["location"]
                updated = store.update_entry(entry_id, **kwargs)
                if updated is None:
                    return 404, {"ok": False, "error": "entry not found"}
                return self._ok(_entry_to_dict(updated))
            if method == "DELETE":
                deleted = store.delete_entry(entry_id)
                return self._ok({"deleted": deleted})
        if segments == ["memory", "long-term", "search-test"] and method == "POST":
            store = self._get_ltm_store()
            if store is None:
                return 404, {"ok": False, "error": "LTM not configured"}
            query_text = str(payload.get("query_text", "") or "")
            conversation_id = str(payload.get("conversation_id", "") or "")
            if not query_text:
                return 400, {"ok": False, "error": "query_text is required"}
            if not conversation_id:
                return 400, {"ok": False, "error": "conversation_id is required"}
            results: list[dict[str, Any]] = []
            # keyword search
            kw_hits = store.keyword_search(query_text, conversation_id=conversation_id, limit=10)
            seen_ids: set[str] = set()
            for entry in kw_hits:
                if entry.entry_id not in seen_ids:
                    seen_ids.add(entry.entry_id)
                    results.append({**_entry_to_dict(entry), "hit_source": "keyword"})
            # structured search by person/entity extracted from query
            struct_hits = store.structured_search(
                conversation_id=conversation_id,
                persons=[],
                entities=[],
                location=None,
                time_range=None,
                limit=10,
            )
            for entry in struct_hits:
                if entry.entry_id not in seen_ids:
                    seen_ids.add(entry.entry_id)
                    results.append({**_entry_to_dict(entry), "hit_source": "structured"})
            return self._ok({"query_text": query_text, "conversation_id": conversation_id, "results": results[:20]})
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
        if segments == ["schedules", "conversation-wakeup"] and method == "GET":
            enabled_query = _query_value(query, "enabled", "").strip().lower()
            enabled: bool | None
            if enabled_query == "":
                enabled = None
            elif enabled_query == "true":
                enabled = True
            elif enabled_query == "false":
                enabled = False
            else:
                raise ValueError("enabled must be true or false")
            return self._ok(
                self._await(
                    self.control_plane.list_conversation_wakeup_schedules(
                        conversation_id=_query_value(query, "conversation_id", ""),
                        enabled=enabled,
                        limit=_query_int(query, "limit", 200),
                    )
                )
            )
        if segments == ["schedules", "conversation-wakeup"] and method == "POST":
            created = self._await(self.control_plane.create_conversation_wakeup_schedule(payload))
            return 201, {"ok": True, "data": _to_jsonable(created)}
        if len(segments) == 4 and segments[:2] == ["schedules", "conversation-wakeup"] and segments[3] in {"enable", "disable"}:
            task_id = segments[2]
            if method != "POST":
                raise KeyError("unsupported method")
            if segments[3] == "enable":
                return self._ok(self._await(self.control_plane.enable_conversation_wakeup_schedule(task_id)))
            return self._ok(self._await(self.control_plane.disable_conversation_wakeup_schedule(task_id)))
        if len(segments) == 3 and segments[:2] == ["schedules", "conversation-wakeup"] and method == "DELETE":
            task_id = segments[2]
            return self._ok(self._await(self.control_plane.delete_conversation_wakeup_schedule(task_id)))
        if segments == ["sessions"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_sessions()))
        if segments == ["sessions"] and method == "POST":
            created = self._await(self.control_plane.create_session(payload))
            return 201, {"ok": True, "data": _to_jsonable(created)}
        if len(segments) == 2 and segments[0] == "sessions":
            session_id = segments[1]
            if method == "GET":
                result = self._await(self.control_plane.get_session(session_id))
                if result is None:
                    return 404, {"ok": False, "error": "session not found"}
                return self._ok(result)
            if method == "PUT":
                return self._ok(self._await(self.control_plane.update_session(session_id, payload)))
        if len(segments) == 3 and segments[0] == "sessions" and segments[2] == "agent":
            session_id = segments[1]
            if method == "GET":
                result = self._await(self.control_plane.get_session_agent(session_id))
                if result is None:
                    return 404, {"ok": False, "error": "session not found"}
                return self._ok(result)
            if method == "PUT":
                return self._ok(self._await(self.control_plane.update_session_agent(session_id, payload)))
        if segments == ["skills"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_skills()))
        if len(segments) == 3 and segments[0] == "agents" and segments[2] == "skills" and method == "GET":
            return self._ok(self._await(self.control_plane.list_agent_skills(segments[1])))
        if segments == ["subagents"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_subagents()))
        if segments == ["subagents", "executors"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_subagents()))

        if segments == ["bot"] and method == "GET":
            return 501, {"ok": False, "error": "bot shell redesign pending"}
        if segments == ["bot"] and method == "PUT":
            return 501, {"ok": False, "error": "bot shell redesign pending"}
        if segments == ["admins"] and method == "GET":
            return self._ok(self._await(self.control_plane.get_admins()))
        if segments == ["admins"] and method == "PUT":
            return self._ok(self._await(self.control_plane.put_admins(payload=payload)))
        if segments == ["notifications"] and method == "POST":
            result = self._await(self.control_plane.post_notification(payload=payload))
            if not bool(result.get("delivered", True)):
                return 500, {"ok": False, "error": result.get("error", "notification delivery failed"), "data": result}
            return self._ok(result)

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
        if segments == ["runtime", "events"] and method == "POST":
            if not self.allow_synthetic_events:
                return 403, {"ok": False, "error": "synthetic events are disabled"}
            if remote_addr not in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}:
                return 403, {"ok": False, "error": "synthetic events require loopback access"}
            return self._ok(self._await(self.control_plane.inject_synthetic_event(payload=payload)))
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
                            latest=_query_value(query, "latest", "").lower() in {"1", "true", "yes", "on"},
                        )
                    )
                )

        if len(segments) >= 2 and segments[0] == "models":
            return self._handle_models(method=method, segments=segments[1:], query=query, payload=payload)

        if segments == ["workspaces"] and method == "GET":
            return self._ok(self._await(self.control_plane.list_workspaces()))
        if len(segments) >= 2 and segments[0] == "workspaces":
            return self._handle_workspaces(method=method, segments=segments[1:], query=query, payload=payload)

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

        if segments == ["litellm-info"] and method == "GET":
            return self._ok(_get_litellm_model_info(
                model=_query_value(query, "model", ""),
            ))
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

    def _ok(self, data: Any) -> tuple[int, dict[str, Any]]:
        import time
        start = time.perf_counter()
        jsonable = _to_jsonable(data)
        duration = time.perf_counter() - start
        if duration > 0.1:
            logger.info("JSON serialization took %.3fs", duration)
        return 200, {"ok": True, "data": jsonable}

    def _get_ltm_store(self):
        """获取 LTM 存储实例, 如果未配置则返回 None."""
        return getattr(self.control_plane, "ltm_store", None)

    def _await(self, awaitable):
        import time
        if self._loop is None:
            raise RuntimeError("http api server is not started")
        
        start = time.perf_counter()
        future = asyncio.run_coroutine_threadsafe(awaitable, self._loop)
        result = future.result(timeout=self.request_timeout_sec)
        duration = time.perf_counter() - start
        
        if duration > 0.1:
            logger.info("Async task execution took %.3fs", duration)
            
        return result


def _get_litellm_model_info(model: str) -> dict[str, Any]:
    """查询 litellm 注册表获取模型能力和支持的参数."""

    import litellm

    result: dict[str, Any] = {"model": model}
    if not model:
        result["model_info"] = None
        result["supported_params"] = []
        result["param_hints"] = {}
        return result

    raw: dict[str, Any] | None = None

    # 模型能力信息
    try:
        raw = litellm.get_model_info(model)
        result["model_info"] = {
            "max_input_tokens": raw.get("max_input_tokens"),
            "max_output_tokens": raw.get("max_output_tokens"),
            "supports_vision": bool(raw.get("supports_vision")),
            "supports_function_calling": bool(raw.get("supports_function_calling")),
            "supports_reasoning": bool(raw.get("supports_reasoning")),
            "supports_audio_input": bool(raw.get("supports_audio_input")),
            "supports_audio_output": bool(raw.get("supports_audio_output")),
            "supports_web_search": bool(raw.get("supports_web_search")),
            "supports_prompt_caching": bool(raw.get("supports_prompt_caching")),
            "supports_response_schema": bool(raw.get("supports_response_schema")),
        }
    except Exception:
        result["model_info"] = None

    # 支持的参数列表
    supported_params: list[str] = []
    try:
        params = litellm.get_supported_openai_params(model=model)
        supported_params = sorted(params) if params else []
    except Exception:
        pass
    result["supported_params"] = supported_params

    # 为前端生成每个参数的 UI hint（控件类型、范围、选项等）
    result["param_hints"] = _build_param_hints(supported_params, raw)

    return result


def _build_param_hints(
    supported_params: list[str],
    model_info: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """根据模型支持的参数列表和能力信息，生成前端渲染所需的控件元数据.

    前端不再维护写死的参数定义 — 所有控件类型、范围、选项全由后端决定。
    """

    hints: dict[str, dict[str, Any]] = {}
    param_set = set(supported_params)

    if "temperature" in param_set:
        hints["temperature"] = {
            "type": "slider", "label": "Temperature",
            "hint": "越高越随机", "min": 0, "max": 2, "step": 0.05,
        }

    if "top_p" in param_set:
        hints["top_p"] = {
            "type": "slider", "label": "Top P",
            "hint": "核采样", "min": 0, "max": 1, "step": 0.05,
        }

    if "max_tokens" in param_set or "max_completion_tokens" in param_set:
        # 用实际支持的参数名作为 hint key
        actual_key = "max_completion_tokens" if "max_completion_tokens" in param_set and "max_tokens" not in param_set else "max_tokens"
        max_out = (model_info or {}).get("max_output_tokens")
        h: dict[str, Any] = {
            "type": "number", "label": "Max Tokens",
            "hint": "最大输出 token 数", "min": 1,
        }
        if max_out:
            h["max"] = max_out
            h["hint"] = f"最大输出 token 数 (上限 {max_out})"
        hints[actual_key] = h

    # litellm 的 supported_params 是 provider 级别的，不区分具体模型。
    # 需要结合 model_info 来过滤掉模型实际不支持的参数。
    supports_reasoning = bool((model_info or {}).get("supports_reasoning"))

    if "reasoning_effort" in param_set and supports_reasoning:
        max_input = (model_info or {}).get("max_input_tokens") or 0
        # 大上下文推理模型 (如 gpt-5.4 1M+) 通常支持 max 档
        if max_input >= 500_000:
            options = ["low", "medium", "high", "max"]
        else:
            options = ["low", "medium", "high"]
        hints["reasoning_effort"] = {
            "type": "select", "label": "思考强度",
            "hint": "控制推理深度", "options": options,
        }

    if "thinking" in param_set and supports_reasoning:
        hints["thinking"] = {
            "type": "checkbox", "label": "深度思考",
            "hint": "启用 extended thinking",
        }

    if "frequency_penalty" in param_set:
        hints["frequency_penalty"] = {
            "type": "slider", "label": "Frequency Penalty",
            "hint": "重复惩罚", "min": -2, "max": 2, "step": 0.05,
        }

    if "presence_penalty" in param_set:
        hints["presence_penalty"] = {
            "type": "slider", "label": "Presence Penalty",
            "hint": "新话题鼓励", "min": -2, "max": 2, "step": 0.05,
        }

    if "seed" in param_set:
        hints["seed"] = {
            "type": "number", "label": "Seed",
            "hint": "固定随机种子",
        }

    if "stop" in param_set:
        hints["stop"] = {
            "type": "text", "label": "Stop Sequences",
            "hint": "逗号分隔",
        }

    return hints


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
        PROVIDER_KIND_REGISTRY,
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
    meta = PROVIDER_KIND_REGISTRY.get(kind)
    if meta is None:
        raise ValueError(f"unsupported provider kind: {kind}")
    api_key_env, api_key = _normalize_provider_auth_fields(
        api_key_env=str(normalized.get("api_key_env", "") or ""),
        api_key=str(normalized.get("api_key", "") or ""),
    )
    default_headers = dict(normalized.get("default_headers", {}) or {})
    default_query = dict(normalized.get("default_query", {}) or {})
    default_body = dict(normalized.get("default_body", {}) or {})
    if meta.config_class == "anthropic":
        config = AnthropicProviderConfig(
            api_key_env=api_key_env,
            api_key=api_key,
            base_url=str(normalized.get("base_url", "") or ""),
            anthropic_version=str(normalized.get("anthropic_version", "") or ""),
            default_headers=default_headers,
            default_query=default_query,
            default_body=default_body,
        )
    elif meta.config_class == "google_gemini":
        config = GoogleGeminiProviderConfig(
            api_key_env=api_key_env,
            api_key=api_key,
            base_url=str(normalized.get("base_url", "") or ""),
            api_version=str(normalized.get("api_version", "") or ""),
            project_id=str(normalized.get("project_id", "") or ""),
            location=str(normalized.get("location", "") or ""),
            use_vertex_ai=bool(normalized.get("use_vertex_ai", False)),
            default_headers=default_headers,
            default_query=default_query,
            default_body=default_body,
        )
    else:
        config = OpenAICompatibleProviderConfig(
            base_url=str(normalized.get("base_url", "") or ""),
            api_key_env=api_key_env,
            api_key=api_key,
            default_headers=default_headers,
            default_query=default_query,
            default_body=default_body,
        )
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

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import core


STATIC_ROOT = core.APP_ROOT / "static"
SESSION_TOKEN = secrets.token_urlsafe(24)
MAX_BODY = 1_000_000
SCHEDULER = core.Scheduler()


class HubHandler(BaseHTTPRequestHandler):
    server_version = "YanFlow/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[yanflow] {self.address_string()} {format % args}")

    def json_response(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def error_response(self, message: str, status: int = 400) -> None:
        self.json_response({"ok": False, "error": core.redact(message)}, status)

    def preview_response(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; img-src 'self' data: https:; "
            "style-src 'unsafe-inline'; font-src data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def read_payload(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0 or size > MAX_BODY:
            raise core.HubError("请求内容大小不合法")
        try:
            value = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise core.HubError("请求不是有效 JSON") from exc
        if not isinstance(value, dict):
            raise core.HubError("请求 JSON 必须是对象")
        return value

    def valid_session(self) -> bool:
        cookies = {}
        for item in (self.headers.get("Cookie") or "").split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1)
                cookies[key] = value
        token = self.headers.get("X-Yanflow-Token") or cookies.get("yanflow_session")
        return bool(token and secrets.compare_digest(token, SESSION_TOKEN))

    def valid_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed = urllib.parse.urlparse(origin)
        except ValueError:
            return False
        return parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == self.server.server_port

    def require_write_access(self) -> bool:
        if not self.valid_session() or not self.valid_origin():
            self.error_response("本地会话校验失败", HTTPStatus.FORBIDDEN)
            return False
        return True

    def serve_file(
        self,
        path: Path,
        *,
        cache: bool = False,
        isolated_preview: bool = False,
    ) -> None:
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = resolved.read_bytes()
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type = f"{content_type}; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if isolated_preview:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; img-src 'self' data: https:; "
                "style-src 'unsafe-inline'; font-src data:; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            )
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/api/health":
            self.json_response({"ok": True, "service": "yanflow", "time": core.now_iso()})
            return
        if path == "/api/status":
            include_accounts = query.get("accounts", ["0"])[0] == "1"
            self.json_response(core.connector_status(include_accounts=include_accounts))
            return
        if path == "/api/settings":
            self.json_response({"ok": True, "settings": core.default_settings()})
            return
        if path == "/api/jobs":
            self.json_response({"ok": True, "jobs": core.list_jobs()})
            return
        match = re.fullmatch(r"/api/jobs/(\d{8}-\d{6}-[0-9a-f]{8})", path)
        if match:
            try:
                self.json_response({"ok": True, "job": core.public_job(core.load_job(match.group(1)))})
            except core.HubError as exc:
                self.error_response(str(exc), HTTPStatus.NOT_FOUND)
            return
        preview_match = re.fullmatch(
            r"/api/jobs/(\d{8}-\d{6}-[0-9a-f]{8})/preview", path
        )
        if preview_match:
            try:
                job = core.load_job(preview_match.group(1))
                preview = Path(str((job.get("content") or {}).get("preview_path") or ""))
                job_root = core.safe_job_dir(preview_match.group(1)).resolve()
                allowed = (
                    preview.resolve().is_relative_to(core.TREND_RUNS_ROOT.resolve())
                    or preview.resolve().is_relative_to(job_root)
                )
                if not allowed:
                    raise core.HubError("预览路径不在允许目录")
                self.preview_response(core.render_article_preview(job))
            except (core.HubError, OSError) as exc:
                self.error_response(str(exc), HTTPStatus.NOT_FOUND)
            return
        asset_match = re.fullmatch(
            r"/api/jobs/(\d{8}-\d{6}-[0-9a-f]{8})/assets/([0-9]{2}\.(?:png|jpe?g|webp))",
            path,
            flags=re.I,
        )
        if asset_match:
            try:
                job_dir = core.safe_job_dir(asset_match.group(1))
                candidate = (job_dir / "assets" / asset_match.group(2)).resolve()
                if not candidate.is_relative_to((job_dir / "assets").resolve()):
                    raise core.HubError("素材路径无效")
                self.serve_file(candidate, cache=True)
            except (core.HubError, OSError) as exc:
                self.error_response(str(exc), HTTPStatus.NOT_FOUND)
            return
        if path == "/":
            body = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
            body = body.replace("__YANFLOW_SESSION_TOKEN__", SESSION_TOKEN)
            data = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header(
                "Set-Cookie",
                f"yanflow_session={SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Strict",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                "script-src 'self'; connect-src 'self'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'",
            )
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", relative):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.serve_file(STATIC_ROOT / relative, cache=False)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def start_background(
        self,
        identifier: str,
        label: str,
        target: Callable[[], Any],
    ) -> None:
        def runner() -> None:
            try:
                target()
            except Exception as exc:
                try:
                    job = core.load_job(identifier)
                    if job.get("status") not in {"failed", "blocked"}:
                        core.update_job(
                            identifier,
                            status="failed",
                            message=core.redact(str(exc)),
                            event={"stage": "system", "label": f"{label}停止"},
                        )
                except Exception:
                    pass

        threading.Thread(target=runner, daemon=True).start()

    def do_POST(self) -> None:
        if not self.require_write_access():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self.read_payload()
            if path == "/api/jobs":
                job = core.create_job(payload)
                self.json_response({"ok": True, "job": job}, HTTPStatus.CREATED)
                return
            if path == "/api/settings":
                self.json_response({"ok": True, "settings": core.save_settings(payload)})
                return

            settings_match = re.fullmatch(
                r"/api/jobs/(\d{8}-\d{6}-[0-9a-f]{8})/publish-settings",
                path,
            )
            if settings_match:
                job = core.update_publish_settings(settings_match.group(1), payload)
                self.json_response({"ok": True, "job": job})
                return

            action_match = re.fullmatch(
                r"/api/jobs/(\d{8}-\d{6}-[0-9a-f]{8})/(run|research|images)",
                path,
            )
            if action_match:
                identifier, action = action_match.groups()
                core.load_job(identifier)
                if action == "run":
                    use_latest = bool(payload.get("use_latest", False))
                    self.start_background(
                        identifier,
                        "安全自动流程",
                        lambda: core.run_safe_pipeline(identifier, use_latest=use_latest),
                    )
                elif action == "research":
                    use_latest = bool(payload.get("use_latest", False))
                    self.start_background(
                        identifier,
                        "选题与内容",
                        lambda: core.run_research(identifier, use_latest=use_latest),
                    )
                else:
                    self.start_background(
                        identifier,
                        "图片生成",
                        lambda: core.run_images(identifier),
                    )
                self.json_response({"ok": True, "job_id": identifier, "accepted": action}, 202)
                return

            dry_match = re.fullmatch(
                r"/api/jobs/(\d{8}-\d{6}-[0-9a-f]{8})/publish/dry-run",
                path,
            )
            if dry_match:
                identifier = dry_match.group(1)
                core.load_job(identifier)
                self.start_background(
                    identifier,
                    "发布预检",
                    lambda: core.run_publish(identifier, live=False),
                )
                self.json_response({"ok": True, "job_id": identifier, "accepted": "dry-run"}, 202)
                return

            live_match = re.fullmatch(
                r"/api/jobs/(\d{8}-\d{6}-[0-9a-f]{8})/publish/live",
                path,
            )
            if live_match:
                identifier = live_match.group(1)
                confirmation = str(payload.get("confirmation") or "")
                if confirmation.strip() != "确认正式发布":
                    raise core.HubError("正式发布需要输入：确认正式发布")
                job = core.load_job(identifier)
                if str((job.get("publish") or {}).get("status") or "") != "dry_run_passed":
                    raise core.HubError("正式发布前必须先通过完整 dry-run")
                self.start_background(
                    identifier,
                    "正式发布",
                    lambda: core.run_publish(
                        identifier,
                        live=True,
                        confirmation=confirmation,
                    ),
                )
                self.json_response({"ok": True, "job_id": identifier, "accepted": "live"}, 202)
                return
            self.error_response("接口不存在", HTTPStatus.NOT_FOUND)
        except core.HubError as exc:
            self.error_response(str(exc), HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.error_response(core.redact(str(exc)), HTTPStatus.INTERNAL_SERVER_ERROR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YanFlow 内容自动化中枢")
    parser.add_argument("--port", type=int, default=8786)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    core.ensure_runtime()
    core.reconcile_stale_image_jobs()
    core.seed_demo_from_latest()
    SCHEDULER.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), HubHandler)
    print(f"YanFlow 已启动：http://127.0.0.1:{args.port}")
    print("仅监听本机；正式发布必须先通过 dry-run 并输入确认短语。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        SCHEDULER.stop()
        server.server_close()


if __name__ == "__main__":
    main()

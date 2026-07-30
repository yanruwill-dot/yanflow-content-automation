from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import subprocess
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
REMOTE_APP_ORIGIN = "https://yanruwill-dot.github.io"
REMOTE_APP_URL = f"{REMOTE_APP_ORIGIN}/yanflow-content-automation/"


class HubHandler(BaseHTTPRequestHandler):
    server_version = "YanFlow/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[yanflow] {self.address_string()} {format % args}")

    def request_origin(self) -> str:
        return self.headers.get("Origin") or ""

    def origin_allowed(self, origin: str) -> bool:
        if origin == REMOTE_APP_ORIGIN:
            return True
        try:
            parsed = urllib.parse.urlparse(origin)
        except ValueError:
            return False
        return (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.port == self.server.server_port
        )

    def add_cors_headers(self) -> None:
        origin = self.request_origin()
        if origin and self.origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def json_response(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.add_cors_headers()
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
        self.add_cors_headers()
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
        return self.origin_allowed(origin)

    def require_api_access(self) -> bool:
        if not self.valid_session() or not self.valid_origin():
            self.error_response("本地会话校验失败", HTTPStatus.FORBIDDEN)
            return False
        return True

    def do_OPTIONS(self) -> None:
        origin = self.request_origin()
        if not origin or not self.origin_allowed(origin):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.add_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Yanflow-Token",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

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
        self.add_cors_headers()
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
        if path == "/connect":
            return_url = query.get("return", [""])[0]
            if return_url != REMOTE_APP_URL:
                self.error_response("只允许连接官方 YanFlow GitHub 页面", HTTPStatus.BAD_REQUEST)
                return
            fragment = urllib.parse.urlencode(
                {
                    "yanflow_token": SESSION_TOKEN,
                    "yanflow_bridge": f"http://127.0.0.1:{self.server.server_port}",
                }
            )
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"{REMOTE_APP_URL}#{fragment}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            return
        if path.startswith("/api/") and not self.require_api_access():
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
                    publish_status = str((job.get("publish") or {}).get("status") or "")
                    if (
                        job.get("status") not in {"failed", "blocked"}
                        and publish_status not in core.SUBMITTED_STATES
                    ):
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
        if not self.require_api_access():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self.read_payload()
            if path == "/api/accounts/login":
                platform = str(payload.get("platform") or "")
                if platform not in {"小红书", "微信公众号"}:
                    raise core.HubError("账号平台无效")
                app_path = Path("/Applications/蚁小二4.0.app")
                if not app_path.exists():
                    raise core.HubError("本机没有安装蚁小二4.0")
                result = subprocess.run(
                    ["open", "-a", "蚁小二4.0"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode != 0:
                    raise core.HubError(result.stderr or "蚁小二4.0启动失败")
                self.json_response(
                    {
                        "ok": True,
                        "action": "opened_yixiaoer",
                        "platform": platform,
                        "checkpoint": (
                            f"请在蚁小二4.0里添加或重新登录{platform}账号；"
                            "扫码、验证码或实名确认完成后，回到本页刷新账号。"
                        ),
                    }
                )
                return
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
                job = core.load_job(identifier)
                if str((job.get("publish") or {}).get("status") or "") in core.SUBMITTED_STATES:
                    raise core.HubError(
                        "该任务已经提交或成功；请新建任务后再运行预检，避免破坏历史记录或重复发布"
                    )
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

from __future__ import annotations

import json
import http.client
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import core
import server


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.originals = {
            "RUNTIME_ROOT": core.RUNTIME_ROOT,
            "JOBS_ROOT": core.JOBS_ROOT,
            "SETTINGS_FILE": core.SETTINGS_FILE,
            "TREND_RUNS_ROOT": core.TREND_RUNS_ROOT,
        }
        root = Path(self.temp.name)
        core.RUNTIME_ROOT = root / "runtime"
        core.JOBS_ROOT = core.RUNTIME_ROOT / "jobs"
        core.SETTINGS_FILE = core.RUNTIME_ROOT / "settings.json"
        core.TREND_RUNS_ROOT = root / "trend-runs"
        core.ensure_runtime()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.HubHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        for name, value in self.originals.items():
            setattr(core, name, value)
        self.temp.cleanup()

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict | None = None,
        token: bool = False,
        origin: str = "",
    ) -> tuple[int, dict | str, dict]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-Yanflow-Token"] = server.SESSION_TOKEN
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        payload = json.loads(raw) if "application/json" in content_type else raw.decode("utf-8")
        return response.status, payload, dict(response.headers)

    def test_health_and_home_security_headers(self) -> None:
        status, payload, _ = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        status, html, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("焰流", html)
        self.assertNotIn("__YANFLOW_SESSION_TOKEN__", html)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("HttpOnly", headers["Set-Cookie"])

    def test_post_requires_local_session_token(self) -> None:
        status, payload, _ = self.request(
            "/api/jobs",
            method="POST",
            body={"brief": "测试", "targets": ["小红书"]},
        )
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])

    def test_remote_bridge_pairing_and_private_network_cors(self) -> None:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.httpd.server_port,
            timeout=5,
        )
        return_url = urllib.parse.quote(server.REMOTE_APP_URL, safe="")
        connection.request("GET", f"/connect?return={return_url}")
        response = connection.getresponse()
        self.assertEqual(response.status, 302)
        location = response.getheader("Location") or ""
        self.assertTrue(location.startswith(server.REMOTE_APP_URL + "#"))
        self.assertIn("yanflow_token=", location)
        connection.close()

        status, payload, headers = self.request(
            "/api/status?accounts=1",
            token=True,
            origin=server.REMOTE_APP_ORIGIN,
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            headers["Access-Control-Allow-Origin"],
            server.REMOTE_APP_ORIGIN,
        )
        self.assertEqual(headers["Access-Control-Allow-Private-Network"], "true")

    def test_remote_origin_still_requires_pairing_token(self) -> None:
        status, payload, _ = self.request(
            "/api/status?accounts=1",
            origin=server.REMOTE_APP_ORIGIN,
        )
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])

    @mock.patch("server.subprocess.run")
    @mock.patch("server.Path.exists", return_value=True)
    def test_account_login_opens_official_yixiaoer_checkpoint(
        self,
        _exists: mock.Mock,
        run: mock.Mock,
    ) -> None:
        run.return_value = mock.Mock(returncode=0, stderr="")
        status, payload, _ = self.request(
            "/api/accounts/login",
            method="POST",
            body={"platform": "小红书"},
            token=True,
            origin=server.REMOTE_APP_ORIGIN,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "opened_yixiaoer")
        self.assertIn("扫码", payload["checkpoint"])
        run.assert_called_once()

    def test_create_and_read_job(self) -> None:
        status, payload, _ = self.request(
            "/api/jobs",
            method="POST",
            body={"brief": "测试自动选题系统", "targets": ["小红书"]},
            token=True,
        )
        self.assertEqual(status, 201)
        identifier = payload["job"]["id"]
        status, payload, _ = self.request(f"/api/jobs/{identifier}", token=True)
        self.assertEqual(status, 200)
        self.assertEqual(payload["job"]["brief"], "测试自动选题系统")

    def test_publish_settings_endpoint_updates_account_and_layout(self) -> None:
        _, created, _ = self.request(
            "/api/jobs",
            method="POST",
            body={"brief": "测试任务设置", "targets": ["小红书"], "layout": "editorial"},
            token=True,
        )
        identifier = created["job"]["id"]
        status, payload, _ = self.request(
            f"/api/jobs/{identifier}/publish-settings",
            method="POST",
            body={"account_ids": {"小红书": "xhs-account-02"}, "layout": "clean"},
            token=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["job"]["layout"], "clean")
        self.assertEqual(payload["job"]["account_ids"]["小红书"], "xhs-account-02")

    def test_static_text_assets_declare_utf8(self) -> None:
        status, _, headers = self.request("/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("charset=utf-8", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_styles_do_not_force_desktop_width_on_mobile(self) -> None:
        css = (server.STATIC_ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("min-width: 1120px", css)
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn("overflow-x: hidden", css)

    def test_preview_is_utf8_and_blocks_scripts_and_forms(self) -> None:
        run = core.TREND_RUNS_ROOT / "preview-fixture"
        run.mkdir(parents=True)
        preview = run / "article.html"
        preview.write_text("<h1>中文预览</h1><script>alert(1)</script>", encoding="utf-8")
        created = core.create_job({"brief": "预览安全测试", "targets": ["微信公众号"]})
        raw = core.load_job(created["id"])
        raw["content"] = {"preview_path": str(preview)}
        core.save_job(raw)
        status, html, headers = self.request(
            f"/api/jobs/{created['id']}/preview",
            token=True,
        )
        self.assertEqual(status, 200)
        self.assertIn("中文预览", html)
        self.assertIn('data-layout="editorial"', html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("charset=utf-8", headers["Content-Type"])
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("form-action 'none'", headers["Content-Security-Policy"])

    def test_live_endpoint_refuses_without_dry_run(self) -> None:
        _, created, _ = self.request(
            "/api/jobs",
            method="POST",
            body={"brief": "测试正式发布闸门", "targets": ["小红书"]},
            token=True,
        )
        identifier = created["job"]["id"]
        status, payload, _ = self.request(
            f"/api/jobs/{identifier}/publish/live",
            method="POST",
            body={"confirmation": "确认正式发布"},
            token=True,
        )
        self.assertEqual(status, 400)
        self.assertIn("dry-run", payload["error"].lower())


if __name__ == "__main__":
    unittest.main()

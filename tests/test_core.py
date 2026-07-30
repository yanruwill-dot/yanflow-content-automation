from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

import core


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.originals = {
            "RUNTIME_ROOT": core.RUNTIME_ROOT,
            "JOBS_ROOT": core.JOBS_ROOT,
            "SETTINGS_FILE": core.SETTINGS_FILE,
            "TREND_RUNS_ROOT": core.TREND_RUNS_ROOT,
            "PUBLISHED_REFERENCES": core.PUBLISHED_REFERENCES,
        }
        core.RUNTIME_ROOT = self.root / "runtime"
        core.JOBS_ROOT = core.RUNTIME_ROOT / "jobs"
        core.SETTINGS_FILE = core.RUNTIME_ROOT / "settings.json"
        core.TREND_RUNS_ROOT = self.root / "trend-runs"
        core.PUBLISHED_REFERENCES = self.root / "published-references"
        core.ensure_runtime()

    def tearDown(self) -> None:
        for name, value in self.originals.items():
            setattr(core, name, value)
        self.temp.cleanup()

    def create_job(self) -> dict:
        return core.create_job(
            {
                "brief": "企业为什么买了很多 AI 工具，效率还是没有提升",
                "audience": "企业经营者",
                "targets": ["小红书", "微信公众号"],
            }
        )

    def create_trend_fixture(self) -> Path:
        run = core.TREND_RUNS_ROOT / "fixture-run"
        run.mkdir(parents=True)
        (run / "04-editorial-topics.json").write_text(
            json.dumps(
                {
                    "generatedAt": "2026-07-26T09:00:00+08:00",
                    "clusters": [
                        {
                            "id": "topic-1",
                            "title": "企业 AI 的瓶颈不是工具，而是流程",
                            "summary": "把 AI 接入真实业务流程，才能形成可核验结果。",
                            "keywords": ["AI", "流程"],
                        },
                        {
                            "id": "topic-2",
                            "title": "内容自动化开始进入交付阶段",
                            "summary": "选题、内容、配图和发布需要一个闭环。",
                            "keywords": ["内容自动化"],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run / "05-topic-scores.json").write_text(
            json.dumps(
                [
                    {
                        "topicId": "topic-1",
                        "finalScore": 92,
                        "reason": "命中企业效率痛点",
                        "recommendedUse": "publish",
                    },
                    {
                        "topicId": "topic-2",
                        "finalScore": 84,
                        "reason": "适合方法论内容",
                        "recommendedUse": "watch",
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run / "18-final-title.json").write_text(
            json.dumps({"title": "AI 工具越买越多，为什么效率没有提升？"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (run / "19-final-article.html").write_text(
            "<!doctype html><html><body><h1>AI 工具越买越多</h1><p>真正的问题在流程。</p></body></html>",
            encoding="utf-8",
        )
        (run / "13-quality-review.json").write_text(
            json.dumps(
                {
                    "overallScore": 91,
                    "allowPublish": True,
                    "summary": "来源和表达通过",
                    "issues": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (run / "01-sources.json").write_text(
            json.dumps(
                [{"title": "公开研究", "url": "https://example.org/source"}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return run

    def test_create_job_rejects_empty_brief_and_deduplicates_targets(self) -> None:
        with self.assertRaisesRegex(core.HubError, "请输入"):
            core.create_job({"brief": "", "targets": ["小红书"]})
        job = core.create_job(
            {
                "brief": "AI 内容自动化",
                "targets": ["小红书", "小红书", "未知平台"],
            }
        )
        self.assertEqual(job["targets"], ["小红书"])
        self.assertEqual(job["status"], "created")

    def test_create_job_keeps_selected_accounts_and_layout(self) -> None:
        job = core.create_job(
            {
                "brief": "测试账号和排版",
                "targets": ["小红书", "微信公众号"],
                "account_ids": {
                    "小红书": "xhs-account-01",
                    "微信公众号": "wechat-account-02",
                    "未知平台": "ignored-account",
                },
                "layout": "clean",
            }
        )
        self.assertEqual(job["layout"], "clean")
        self.assertEqual(
            job["account_ids"],
            {"小红书": "xhs-account-01", "微信公众号": "wechat-account-02"},
        )
        with self.assertRaisesRegex(core.HubError, "排版模板无效"):
            core.create_job({"brief": "错误排版", "targets": ["小红书"], "layout": "fake"})

    def test_publish_settings_change_invalidates_dry_run_and_fingerprint(self) -> None:
        job = self.create_job()
        raw = core.load_job(job["id"])
        raw["status"] = "preflight_passed"
        raw["images"] = {"status": "ready", "items": [{"file": "assets/01.png"}]}
        raw["publish"] = {"status": "dry_run_passed", "fingerprint": "old"}
        core.save_job(raw)
        before = core.content_fingerprint(raw)
        updated = core.update_publish_settings(
            job["id"],
            {
                "layout": "song",
                "account_ids": {
                    "小红书": "xhs-account-02",
                    "微信公众号": "wechat-account-01",
                },
            },
        )
        self.assertEqual(updated["status"], "images_ready")
        self.assertEqual(updated["publish"]["status"], "not_started")
        self.assertEqual(updated["publish"]["previous_status"], "dry_run_passed")
        self.assertEqual(updated["layout"], "song")
        self.assertNotEqual(before, core.content_fingerprint(core.load_job(job["id"])))

    def test_publish_settings_are_locked_after_external_submission(self) -> None:
        job = self.create_job()
        raw = core.load_job(job["id"])
        raw["publish"] = {"status": "failed", "task_set_ids": ["external-task"]}
        core.save_job(raw)
        with self.assertRaisesRegex(core.HubError, "已经提交到平台"):
            core.update_publish_settings(job["id"], {"layout": "clean"})

    def test_preview_layout_is_responsive_and_removes_active_content(self) -> None:
        job = self.create_job()
        raw = core.load_job(job["id"])
        raw["layout"] = "song"
        raw["content"] = {
            "title": "宋式测试文章",
            "article_html": (
                "<h1>宋式测试文章</h1><p onclick=\"alert(1)\">正文</p>"
                "<script>alert(2)</script>"
            ),
        }
        preview = core.render_article_preview(raw)
        self.assertIn('data-layout="song"', preview)
        self.assertIn("@media (max-width: 600px)", preview)
        self.assertNotIn("onclick=", preview)
        self.assertNotIn("<script>alert(2)</script>", preview)

    def test_update_job_adds_timeline_without_leaking_event_field(self) -> None:
        job = self.create_job()
        updated = core.update_job(
            job["id"],
            status="content_ready",
            event={"stage": "content", "label": "内容完成"},
        )
        self.assertNotIn("event", updated)
        self.assertEqual(updated["timeline"][-1]["label"], "内容完成")

    def test_import_trend_run_creates_content_and_risk_result(self) -> None:
        self.create_trend_fixture()
        job = self.create_job()
        imported = core.import_latest_trend(job["id"])
        self.assertEqual(imported["status"], "content_ready")
        self.assertEqual(imported["content"]["quality"]["score"], 91)
        self.assertEqual(imported["research"]["selected"]["id"], "topic-1")
        self.assertEqual(imported["risk"]["level"], "low")
        self.assertTrue(imported["content"]["preview_path"].endswith("19-final-article.html"))

    def test_public_copy_gate_blocks_internal_and_absolute_promises(self) -> None:
        violations = core.public_copy_violations(
            "作者：颜汝",
            "百分之百有效，绝不封号",
            "加微信看二维码",
        )
        self.assertIn("内部作者标签", violations)
        self.assertIn("绝对化承诺", violations)
        self.assertIn("站外导流", violations)

    def test_source_links_in_article_do_not_block_clean_platform_copy(self) -> None:
        job = self.create_job()
        stored = core.store_codex_content(
            job["id"],
            [{"title": "公开研究", "url": "https://example.org/source"}],
            {
                "candidates": [
                    {
                        "id": "topic-1",
                        "title": "企业 AI 从回答走向执行",
                        "summary": "把模型接入真实流程。",
                        "score": 88,
                    }
                ],
                "selected_id": "topic-1",
                "title": "企业 AI 从回答走向执行",
                "xhs_title": "AI 要进入真实流程",
                "xhs_body": "先定义任务，再结构化输出，最后保留复核与回退。#企业AI",
                "article_html": (
                    "<h1>企业 AI 从回答走向执行</h1>"
                    "<p>参考来源：<a href=\"https://example.org/source\">公开研究</a></p>"
                ),
                "quality": {"score": 88, "summary": "来源和表达通过", "issues": []},
            },
        )
        self.assertTrue(stored["content"]["quality"]["allow_publish"])
        self.assertEqual(stored["risk"]["level"], "low")

    def test_duplicate_image_gate_detects_exact_content(self) -> None:
        core.PUBLISHED_REFERENCES.mkdir(parents=True)
        reference = core.PUBLISHED_REFERENCES / "published.png"
        current = self.root / "current.png"
        for path in (reference, current):
            image = Image.new("RGB", (80, 120), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 39, 119), fill="black")
            draw.ellipse((22, 38, 64, 80), fill="red")
            image.save(path)
        job = self.create_job()
        matches = core.duplicate_image_matches(job["id"], [current])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["distance"], 0)

    def test_rate_limit_gate_blocks_fourth_submission_and_short_interval(self) -> None:
        account = "account-123456"
        for index in range(3):
            job = self.create_job()
            raw = core.load_job(job["id"])
            raw["publish"] = {
                "status": "success",
                "account_ids": [account],
                "submitted_at": (
                    dt.datetime.now().astimezone() - dt.timedelta(minutes=index * 20)
                ).isoformat(),
            }
            core.save_job(raw)
        checks = core.rate_limit_checks({}, [account])
        self.assertTrue(any(not item["ok"] and "今日发布" in item["label"] for item in checks))
        self.assertTrue(any(not item["ok"] and "距上次" in item["label"] for item in checks))

    def test_build_xhs_payload_enforces_title_length(self) -> None:
        payload = core.build_xhs_payload(
            "account-1",
            "这是一个超过二十个汉字的小红书内容标题需要自动截断",
            "正文",
            [{"key": "image-key"}],
        )
        form = payload["publishArgs"]["accountForms"][0]["contentPublishForm"]
        self.assertLessEqual(len(form["title"]), 20)
        self.assertEqual(payload["publishType"], "imageText")

    def test_validate_upload_keeps_xhs_required_image_metadata(self) -> None:
        uploaded = core.validate_upload(
            {
                "key": "folder/cover.png",
                "bucket": "cloud-publish",
                "contentType": "image/png",
                "size": 123,
                "width": 1086,
                "height": 1448,
            }
        )
        self.assertEqual(uploaded["format"], "png")
        self.assertEqual(uploaded["bucket"], "cloud-publish")
        self.assertEqual(uploaded["contentType"], "image/png")

    def test_live_publish_requires_dry_run_before_any_external_call(self) -> None:
        job = self.create_job()
        with self.assertRaisesRegex(core.HubError, "dry-run"):
            core.run_publish(job["id"], live=True, confirmation="确认正式发布")

    def test_preflight_refuses_published_job_without_mutating_history(self) -> None:
        job = self.create_job()
        core.update_job(
            job["id"],
            status="published",
            message="平台已返回公开链接",
            publish={
                "status": "success",
                "publish_id": "published-item",
                "public_urls": ["https://example.org/published"],
            },
        )

        with self.assertRaisesRegex(core.HubError, "新建任务"):
            core.run_publish(job["id"], live=False)

        preserved = core.load_job(job["id"])
        self.assertEqual(preserved["status"], "published")
        self.assertEqual(preserved["publish"]["status"], "success")
        self.assertEqual(
            preserved["publish"]["public_urls"],
            ["https://example.org/published"],
        )

    def test_live_publish_preserves_success_when_another_platform_fails(self) -> None:
        job = self.create_job()
        core.update_job(
            job["id"],
            status="preflight_passed",
            publish={"status": "dry_run_passed"},
        )
        manifest = self.root / "publish-job.json"
        manifest.write_text("{}", encoding="utf-8")

        def fake_run(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True)
            (output / "summary.json").write_text(
                json.dumps(
                    {
                        "ok": False,
                        "items": [
                            {
                                "platform": "小红书",
                                "api_submission": "蚁小二已接受任务",
                                "platform_result": "success",
                                "public_urls": ["https://example.org/xhs"],
                                "task_set_ids": ["xhs-task"],
                                "blockers": [],
                            },
                            {
                                "platform": "微信公众号",
                                "api_submission": "蚁小二已接受任务",
                                "platform_result": "failed",
                                "public_urls": [],
                                "task_set_ids": ["wechat-task"],
                                "blockers": ["登录失效"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return core.CommandResult(1, "", "partial failure")

        with (
            mock.patch.object(
                core,
                "prepare_publish_package",
                return_value=(manifest, ["xhs-account", "wechat-account"]),
            ),
            mock.patch.object(core, "run_command", side_effect=fake_run),
        ):
            published = core.run_publish(
                job["id"],
                live=True,
                confirmation="确认正式发布",
            )
        self.assertEqual(published["status"], "partial_success")
        self.assertEqual(published["publish"]["status"], "partial_success")
        self.assertEqual(published["publish"]["public_urls"], ["https://example.org/xhs"])
        self.assertIn("登录失效", published["message"])

    def test_settings_keep_live_automation_off_and_clamp_limits(self) -> None:
        settings = core.save_settings(
            {
                "schedule_enabled": True,
                "schedule_time": "08:15",
                "weekdays": [1, 8],
                "daily_limit_per_account": 9,
                "minimum_interval_minutes": 10,
                "live_automation_enabled": True,
            }
        )
        self.assertEqual(settings["daily_limit_per_account"], 3)
        self.assertEqual(settings["minimum_interval_minutes"], 180)
        self.assertEqual(settings["weekdays"], [1])
        self.assertFalse(settings["live_automation_enabled"])

    def test_parse_public_feed_supports_rss_and_atom(self) -> None:
        rss = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><title>RSS Source</title><item>
        <title>AI workflow efficiency</title>
        <link>https://example.org/rss-item</link>
        <pubDate>Sun, 26 Jul 2026 08:00:00 GMT</pubDate>
        <description>Teams are redesigning workflows.</description>
        </item></channel></rss>"""
        atom = b"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Source</title><entry>
        <title>Agent productivity benchmark</title>
        <link href="https://example.org/atom-entry"/>
        <updated>2026-07-26T08:00:00Z</updated>
        <summary>Measured results from real teams.</summary>
        </entry></feed>"""
        rows = core.parse_public_feed(rss, "rss") + core.parse_public_feed(atom, "atom")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["url"], "https://example.org/rss-item")
        self.assertEqual(rows[1]["title"], "Agent productivity benchmark")

    def test_progress_detail_is_visible_and_keeps_stage_percentage(self) -> None:
        job = self.create_job()
        updated = core.set_job_progress(
            job["id"],
            phase="research",
            phase_label="抓取公开来源",
            stage_percent=35,
            overall_percent=18,
            message="已抓取 8 条，正在去重",
            current_step="去重与筛选",
            completed_steps=2,
            total_steps=6,
        )
        self.assertEqual(updated["progress"], 18)
        self.assertEqual(updated["progress_detail"]["stage_percent"], 35)
        self.assertEqual(updated["progress_detail"]["current_step"], "去重与筛选")

    def test_reconcile_stale_image_job_replaces_false_running_state(self) -> None:
        job = self.create_job()
        core.update_job(
            job["id"],
            status="imaging",
            progress_detail={"image_job_id": "image-job-1", "stage_percent": 5},
        )
        with mock.patch.object(
            core,
            "http_json",
            return_value={
                "status": "failed",
                "progress": 5,
                "message": "九图生成没有完成",
            },
        ):
            count = core.reconcile_stale_image_jobs()
        updated = core.load_job(job["id"])
        self.assertEqual(count, 1)
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["progress_detail"]["error"], "九图生成没有完成")


if __name__ == "__main__":
    unittest.main()

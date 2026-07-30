from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - health check reports this clearly.
    Image = None


APP_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_ROOT.parents[1]
RUNTIME_ROOT = APP_ROOT / "runtime"
JOBS_ROOT = RUNTIME_ROOT / "jobs"
SETTINGS_FILE = RUNTIME_ROOT / "settings.json"
TREND_ROOT = WORKSPACE_ROOT / "external" / "ai-trend-publish"
TREND_RUNS_ROOT = TREND_ROOT / "src" / "temp" / "runs"
IMAGE_STUDIO_ROOT = WORKSPACE_ROOT / "wechat-image-studio"
IMAGE_STUDIO_OUTPUTS = WORKSPACE_ROOT / "outputs" / "wechat-image-studio"
IMAGE_STUDIO_URL = "http://127.0.0.1:8765"
AUDITED_PUBLISHER = (
    Path.home()
    / ".codex"
    / "skills"
    / "codex-yixiaoer-autopublish"
    / "scripts"
    / "codex_yixiaoer_autopublish.py"
)
STICKER_BUILDER = (
    Path.home()
    / ".codex"
    / "skills"
    / "wechat-image-sticker-publisher"
    / "scripts"
    / "build_wechat_sticker_payload.py"
)
PUBLISHED_REFERENCES = IMAGE_STUDIO_ROOT / "assets" / "published-references"
PUBLIC_FEEDS = [
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
]
CODEX_CONTENT_MODEL = os.environ.get("YANFLOW_CODEX_MODEL", "gpt-5.4-mini")

DEFAULT_LAYOUT = "editorial"
LAYOUTS = {
    "editorial": {
        "id": "editorial",
        "label": "商业杂志",
        "description": "深墨标题区、青柠强调，适合观点和商业判断",
        "image_style": "editorial",
        "palette": "ink",
        "content_pattern": "framework",
    },
    "clean": {
        "id": "clean",
        "label": "清爽阅读",
        "description": "白底松石绿、短段落，适合教程和行动清单",
        "image_style": "notion",
        "palette": "jade",
        "content_pattern": "checklist",
    },
    "song": {
        "id": "song",
        "label": "宋式留白",
        "description": "米白纸感、朱砂点题，适合故事和深度文章",
        "image_style": "song",
        "palette": "orange",
        "content_pattern": "framework",
    },
}

CONTENT_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "candidates",
        "selected_id",
        "title",
        "xhs_title",
        "xhs_body",
        "article_html",
        "quality",
    ],
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "title",
                    "summary",
                    "score",
                    "reason",
                    "recommended_use",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string"},
                    "recommended_use": {"type": "string"},
                },
            },
        },
        "selected_id": {"type": "string"},
        "title": {"type": "string"},
        "xhs_title": {"type": "string"},
        "xhs_body": {"type": "string"},
        "article_html": {"type": "string"},
        "quality": {
            "type": "object",
            "additionalProperties": False,
            "required": ["score", "summary", "issues"],
            "properties": {
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                "summary": {"type": "string"},
                "issues": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
            },
        },
    },
}

SUBMITTED_STATES = {
    "submitted",
    "reviewing",
    "success",
    "allsuccessful",
    "partial_success",
}
IN_FLIGHT_STATES = {
    "researching",
    "writing",
    "imaging",
    "preflighting",
    "publishing",
}
PUBLIC_FORBIDDEN = [
    ("内部作者标签", re.compile(r"作者：颜汝|作者：|author\s*:", re.I)),
    (
        "内部素材标签",
        re.compile(
            r"\bplaceholder\b|\bpayload\b|\bpreview\b|\bdraft\b|封面图|正文图|测试稿|TODO|ahropci",
            re.I,
        ),
    ),
    (
        "站外导流",
        re.compile(r"微信号|加微信|二维码|联系方式|\bvx\b|v信|https?://|www\.", re.I),
    ),
    (
        "绝对化承诺",
        re.compile(r"百分之百|100%有效|保证赚钱|绝不封号|一定爆|国家指定|官方背书", re.I),
    ),
]


class HubError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    code: int
    stdout: str
    stderr: str


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_runtime() -> None:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)


def read_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def atomic_json(path: Path, value: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(pending, mode)
    pending.replace(path)


def redact(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"sk-[A-Za-z0-9._-]+", "sk-***", text)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer ***", text, flags=re.I)
    text = re.sub(
        r"(YIXIAOER_API_KEY|OPENAI_API_KEY|API_KEY)\s*[=:]\s*\S+",
        r"\1=***",
        text,
        flags=re.I,
    )
    return text[-6000:]


def load_local_env() -> dict[str, str]:
    merged = dict(os.environ)
    for candidate in [
        Path.home() / ".hermes" / ".env",
        Path(os.environ.get("HERMES_ENV_FILE", "")) if os.environ.get("HERMES_ENV_FILE") else None,
    ]:
        if not candidate or not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            merged.setdefault(key, value.strip().strip("\"'"))
    return merged


def run_command(
    command: list[str],
    *,
    cwd: Path = APP_ROOT,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env or os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout or "", redact(completed.stderr))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(1, "", redact(str(exc)))


def run_json_command(
    command: list[str],
    *,
    cwd: Path = APP_ROOT,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = run_command(command, cwd=cwd, timeout=timeout, env=env)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HubError(redact(result.stderr or result.stdout or str(exc))) from exc
    if result.code != 0 or payload.get("ok") is False:
        raise HubError(
            redact(
                str(
                    payload.get("error")
                    or payload.get("message")
                    or result.stderr
                    or f"command failed: {' '.join(command[:3])}"
                )
            )
        )
    return payload


def clean_public_copy(value: str, limit: int = 1000) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def render_article_preview(job: dict[str, Any]) -> str:
    content = job.get("content") or {}
    article_html = str(content.get("article_html") or "")
    if not article_html:
        preview_path = Path(str(content.get("preview_path") or ""))
        if preview_path.exists():
            article_html = preview_path.read_text(encoding="utf-8", errors="ignore")
    if not article_html:
        raise HubError("还没有可预览的公众号正文")

    body_match = re.search(r"<body\b[^>]*>(.*?)</body>", article_html, flags=re.I | re.S)
    body = body_match.group(1) if body_match else article_html
    body = re.sub(
        r"<(script|style|iframe|object|embed|template)\b[^>]*>.*?</\1>",
        "",
        body,
        flags=re.I | re.S,
    )
    body = re.sub(r"</?(?:html|head|body|form)\b[^>]*>", "", body, flags=re.I)
    body = re.sub(r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", "", body, flags=re.I)
    body = re.sub(
        r"\s+(href|src)\s*=\s*([\"'])\s*javascript:.*?\2",
        "",
        body,
        flags=re.I | re.S,
    )

    layout_id = str(job.get("layout") or DEFAULT_LAYOUT)
    layout = LAYOUTS.get(layout_id, LAYOUTS[DEFAULT_LAYOUT])
    title = clean_public_copy(content.get("title") or job.get("brief") or "公众号文章", 120)
    return f"""<!doctype html>
<html lang="zh-CN" data-layout="{html.escape(layout_id)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --serif: "Songti SC","STSong",serif; --sans: "PingFang SC","Hiragino Sans GB",sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--page); color: var(--ink); font-family: var(--sans); }}
    .page {{ width: min(100%, 860px); margin: 0 auto; padding: 54px 24px 88px; }}
    .layout-note {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 22px; color: var(--muted); font-size: 12px; letter-spacing: .06em; }}
    article {{ background: var(--paper); padding: clamp(28px, 6vw, 72px); box-shadow: var(--shadow); }}
    h1 {{ margin: 0 0 32px; font: 700 clamp(32px, 7vw, 58px)/1.16 var(--serif); letter-spacing: -.035em; }}
    h2 {{ margin: 52px 0 20px; padding-top: 18px; border-top: 2px solid var(--accent); font: 700 28px/1.35 var(--serif); }}
    h3 {{ margin: 34px 0 14px; font: 700 21px/1.45 var(--serif); }}
    p, li {{ font-size: 17px; line-height: 1.95; letter-spacing: .015em; }}
    p {{ margin: 0 0 20px; }}
    ul, ol {{ margin: 18px 0 26px; padding-left: 1.4em; }}
    li {{ margin-bottom: 10px; }}
    strong {{ color: var(--strong); background: var(--strong-bg); padding: 0 .18em; }}
    blockquote {{ margin: 28px 0; padding: 20px 22px; border-left: 4px solid var(--accent); background: var(--quote); }}
    a {{ color: var(--link); text-underline-offset: 3px; overflow-wrap: anywhere; }}
    img {{ display: block; max-width: 100%; height: auto; margin: 28px auto; }}
    [data-layout="editorial"] {{ --page:#10120f; --paper:#f2efe5; --ink:#161914; --muted:#757b70; --accent:#bce833; --strong:#10120f; --strong-bg:#d6ff66; --quote:#e4e9d7; --link:#416200; --shadow:0 30px 90px rgba(0,0,0,.32); }}
    [data-layout="editorial"] article {{ border-top: 12px solid var(--accent); }}
    [data-layout="editorial"] h1 {{ padding-bottom: 30px; border-bottom: 1px solid #c7cabb; }}
    [data-layout="clean"] {{ --page:#e7f2ee; --paper:#ffffff; --ink:#17312a; --muted:#688078; --accent:#1e9b78; --strong:#0e634e; --strong-bg:#dff7ee; --quote:#eff9f5; --link:#08785b; --shadow:0 24px 70px rgba(31,91,73,.12); }}
    [data-layout="clean"] article {{ border-radius: 28px; }}
    [data-layout="clean"] h1 {{ color:#0e6f54; }}
    [data-layout="clean"] h2 {{ border-top:0; border-left:6px solid var(--accent); padding:4px 0 4px 16px; }}
    [data-layout="song"] {{ --page:#e9e0d0; --paper:#faf4e8; --ink:#2b241d; --muted:#8c7868; --accent:#b63b2b; --strong:#8f2b20; --strong-bg:#f4dfce; --quote:#f1e5d5; --link:#9a3025; --shadow:0 28px 80px rgba(75,51,31,.18); }}
    [data-layout="song"] article {{ border:1px solid #d9c8b2; }}
    [data-layout="song"] h1, [data-layout="song"] h2, [data-layout="song"] h3 {{ font-family:var(--serif); }}
    [data-layout="song"] h1 {{ text-align:center; padding:0 3vw 34px; border-bottom:1px solid #d7c4ad; }}
    [data-layout="song"] h2 {{ border-top:0; text-align:center; color:var(--accent); }}
    @media (max-width: 600px) {{
      .page {{ padding: 18px 0 48px; }}
      .layout-note {{ padding: 0 16px; }}
      article {{ padding: 30px 20px 52px; box-shadow:none; border-radius:0 !important; }}
      h1 {{ font-size:34px; }}
      h2 {{ margin-top:42px; font-size:25px; }}
      p, li {{ font-size:16px; line-height:1.9; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <div class="layout-note"><span>{html.escape(str(layout["label"]))}</span><span>手机与网页自适应</span></div>
    <article>{body}</article>
  </main>
</body>
</html>"""


def parse_public_feed(data: bytes, source_name: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise HubError(f"{source_name} 返回的 RSS 无法解析") from exc

    def local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    def child_value(node: ET.Element, names: set[str]) -> str:
        for child in list(node):
            if local_name(child.tag) not in names:
                continue
            if local_name(child.tag) == "link" and child.attrib.get("href"):
                return str(child.attrib["href"]).strip()
            return "".join(child.itertext()).strip()
        return ""

    rows: list[dict[str, str]] = []
    for node in root.iter():
        if local_name(node.tag) not in {"item", "entry"}:
            continue
        title = clean_public_copy(child_value(node, {"title"}), 240)
        url = child_value(node, {"link"})
        if not title or not url.startswith(("http://", "https://")):
            continue
        rows.append(
            {
                "title": title,
                "url": url[:600],
                "published_at": clean_public_copy(
                    child_value(node, {"pubdate", "published", "updated"}),
                    100,
                ),
                "summary": clean_public_copy(
                    child_value(node, {"description", "summary", "content"}),
                    900,
                ),
                "source": source_name,
            }
        )
    return rows


def public_copy_violations(*values: str) -> list[str]:
    combined = "\n".join(values)
    return [label for label, pattern in PUBLIC_FORBIDDEN if pattern.search(combined)]


def job_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def safe_job_dir(identifier: str) -> Path:
    if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}", identifier):
        raise HubError("任务编号无效")
    path = JOBS_ROOT / identifier
    if not path.exists():
        raise HubError("没有找到这个任务")
    return path


def load_job(identifier: str) -> dict[str, Any]:
    value = read_json(safe_job_dir(identifier) / "job.json")
    if not isinstance(value, dict):
        raise HubError("任务文件损坏")
    return value


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    job["updated_at"] = now_iso()
    atomic_json(JOBS_ROOT / job["id"] / "job.json", job)
    return public_job(job)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "brief",
        "audience",
        "targets",
        "account_ids",
        "layout",
        "mode",
        "status",
        "message",
        "progress",
        "progress_detail",
        "created_at",
        "updated_at",
        "timeline",
        "research",
        "content",
        "images",
        "risk",
        "publish",
        "source_run",
        "demo",
    }
    return {key: job[key] for key in allowed if key in job}


def update_job(identifier: str, **changes: Any) -> dict[str, Any]:
    job = load_job(identifier)
    event = changes.pop("event", None)
    job.update(changes)
    if event:
        timeline = list(job.get("timeline") or [])
        timeline.append({"at": now_iso(), **event})
        job["timeline"] = timeline[-80:]
    return save_job(job)


def set_job_progress(
    identifier: str,
    *,
    phase: str,
    phase_label: str,
    stage_percent: int,
    overall_percent: int,
    message: str,
    current_step: str,
    completed_steps: int,
    total_steps: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail = {
        "phase": phase,
        "phase_label": phase_label,
        "stage_percent": max(0, min(int(stage_percent), 100)),
        "current_step": clean_public_copy(current_step, 120),
        "completed_steps": max(0, int(completed_steps)),
        "total_steps": max(1, int(total_steps)),
        "updated_at": now_iso(),
    }
    if extra:
        detail.update(extra)
    return update_job(
        identifier,
        progress=max(0, min(int(overall_percent), 100)),
        progress_detail=detail,
        message=clean_public_copy(message, 500),
    )


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime()
    brief = clean_public_copy(payload.get("brief") or "", 500)
    audience = clean_public_copy(payload.get("audience") or "企业经营者与内容创作者", 160)
    targets = [
        item
        for item in payload.get("targets", ["小红书", "微信公众号"])
        if item in {"小红书", "微信公众号"}
    ]
    targets = list(dict.fromkeys(targets))
    if not brief:
        raise HubError("请输入本轮内容方向")
    if not targets:
        raise HubError("至少选择一个发布平台")
    layout = str(payload.get("layout") or DEFAULT_LAYOUT)
    if layout not in LAYOUTS:
        raise HubError("排版模板无效")
    account_ids = normalize_account_ids(payload.get("account_ids"), targets)
    identifier = job_id()
    job_dir = JOBS_ROOT / identifier
    job_dir.mkdir(parents=True, mode=0o700)
    job = {
        "id": identifier,
        "brief": brief,
        "audience": audience,
        "targets": targets,
        "account_ids": account_ids,
        "layout": layout,
        "mode": payload.get("mode") if payload.get("mode") in {"safe_auto", "manual"} else "safe_auto",
        "status": "created",
        "message": "任务已创建，等待启动安全自动流程",
        "progress": 3,
        "progress_detail": {
            "phase": "created",
            "phase_label": "准备任务",
            "stage_percent": 0,
            "current_step": "等待启动",
            "completed_steps": 0,
            "total_steps": 6,
            "updated_at": now_iso(),
        },
        "created_at": now_iso(),
        "timeline": [{"at": now_iso(), "stage": "created", "label": "任务创建"}],
        "risk": {"level": "pending", "checks": []},
        "publish": {"status": "not_started"},
    }
    return save_job(job)


def layout_options() -> list[dict[str, str]]:
    return [
        {
            "id": str(item["id"]),
            "label": str(item["label"]),
            "description": str(item["description"]),
        }
        for item in LAYOUTS.values()
    ]


def normalize_account_ids(value: Any, targets: list[str]) -> dict[str, str]:
    rows = value if isinstance(value, dict) else {}
    normalized: dict[str, str] = {}
    for platform in targets:
        account_id = str(rows.get(platform) or "").strip()
        if not account_id:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,100}", account_id):
            raise HubError(f"{platform}账号编号无效")
        normalized[platform] = account_id
    return normalized


def update_publish_settings(identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
    job = load_job(identifier)
    publish = job.get("publish") or {}
    publish_state = str(publish.get("status") or "")
    if job.get("status") in IN_FLIGHT_STATES:
        raise HubError("任务正在运行，完成当前阶段后才能换账号或排版")
    if publish_state in SUBMITTED_STATES or any(
        publish.get(key)
        for key in ("task_set_ids", "taskSetIds", "publish_id", "publishId", "public_urls")
    ):
        raise HubError("任务已经提交到平台，不能再换账号或排版；请新建任务避免重复发布")

    layout = str(payload.get("layout") or job.get("layout") or DEFAULT_LAYOUT)
    if layout not in LAYOUTS:
        raise HubError("排版模板无效")
    account_ids = (
        normalize_account_ids(payload.get("account_ids"), list(job.get("targets") or []))
        if "account_ids" in payload
        else dict(job.get("account_ids") or {})
    )
    if layout == (job.get("layout") or DEFAULT_LAYOUT) and account_ids == (
        job.get("account_ids") or {}
    ):
        return public_job(job)

    job["layout"] = layout
    job["account_ids"] = account_ids
    if publish_state != "not_started":
        job["publish"] = {
            "status": "not_started",
            "settings_changed_at": now_iso(),
            "previous_status": publish_state,
        }
    if job.get("status") in {"preflight_passed", "failed", "blocked"}:
        job["status"] = "images_ready" if (job.get("images") or {}).get("items") else "content_ready"
    job["message"] = "发布账号和排版已更新；旧的发布预检已作废"
    timeline = list(job.get("timeline") or [])
    timeline.append(
        {
            "at": now_iso(),
            "stage": "settings",
            "label": f"切换为{LAYOUTS[layout]['label']}排版",
        }
    )
    job["timeline"] = timeline[-80:]
    return save_job(job)


def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    ensure_runtime()
    rows: list[dict[str, Any]] = []
    for path in sorted(JOBS_ROOT.glob("*/job.json"), reverse=True):
        value = read_json(path)
        if isinstance(value, dict):
            rows.append(public_job(value))
        if len(rows) >= limit:
            break
    return rows


def connector_status(include_accounts: bool = False) -> dict[str, Any]:
    deno = shutil.which("deno")
    yxer = shutil.which("yxer")
    python_ok = bool(sys.executable)
    trend_ready = bool(deno and TREND_ROOT.exists() and (TREND_ROOT / "trendpublish.config.ts").exists())
    image_ready = bool(
        python_ok and (IMAGE_STUDIO_ROOT / "server.py").exists() and Image is not None
    )
    yxer_version = ""
    yxer_ready = False
    account_rows: list[dict[str, Any]] = []
    yxer_error = ""
    if yxer:
        version = run_command([yxer, "--version"], timeout=15, env=load_local_env())
        yxer_version = clean_public_copy(version.stdout or version.stderr, 100)
        yxer_ready = version.code == 0
        if include_accounts and yxer_ready:
            try:
                accounts = run_json_command(
                    [yxer, "accounts", "--all", "--json"],
                    timeout=45,
                    env=load_local_env(),
                )
                raw_rows = accounts.get("data")
                if isinstance(raw_rows, dict):
                    raw_rows = raw_rows.get("data") or raw_rows.get("list") or []
                for row in raw_rows if isinstance(raw_rows, list) else []:
                    platform = str(row.get("platformName") or "")
                    if platform not in {"小红书", "微信公众号"}:
                        continue
                    reason = ""
                    if int(row.get("status") or 0) != 1:
                        reason = "账号状态不可用"
                    elif row.get("isLock"):
                        reason = str(row.get("lock_reason") or "账号已锁定")
                    elif row.get("isFreeze"):
                        reason = "账号已冻结"
                    account_rows.append(
                        {
                            "id": str(row.get("id") or ""),
                            "platform": platform,
                            "name": str(row.get("platformAccountName") or "未命名账号"),
                            "ready": not reason,
                            "reason": reason,
                        }
                    )
            except HubError as exc:
                yxer_error = str(exc)
    publish_ready = bool(yxer_ready and AUDITED_PUBLISHER.exists() and STICKER_BUILDER.exists())
    return {
        "ok": trend_ready and image_ready and publish_ready,
        "checked_at": now_iso(),
        "layouts": layout_options(),
        "connectors": {
            "trend": {
                "ready": trend_ready,
                "label": "TrendPublish",
                "detail": "多源选题、证据、写稿、审稿",
            },
            "image": {
                "ready": image_ready,
                "label": "Image2 贴图工厂",
                "detail": "小红书与公众号 3:4 图组",
            },
            "publish": {
                "ready": publish_ready,
                "label": "蚁小二 yxer",
                "detail": yxer_version or "未检测到 yxer",
                "error": yxer_error,
            },
        },
        "accounts": account_rows,
        "policy": {
            "official_route_first": True,
            "daily_limit_per_account": 3,
            "minimum_interval_minutes": 180,
            "duplicate_images_blocked": True,
            "live_requires_explicit_confirmation": True,
            "captcha_or_realname_stops": True,
        },
    }


def reconcile_stale_image_jobs() -> int:
    ensure_runtime()
    reconciled = 0
    for path in JOBS_ROOT.glob("*/job.json"):
        job = read_json(path, {}) or {}
        if job.get("status") != "imaging":
            continue
        detail = job.get("progress_detail") or {}
        image_job_id = str(detail.get("image_job_id") or "")
        if not image_job_id:
            continue
        try:
            image_job = http_json(f"{IMAGE_STUDIO_URL}/api/jobs/{image_job_id}", timeout=5)
        except HubError:
            continue
        if str(image_job.get("status") or "") != "failed":
            continue
        message = clean_public_copy(
            image_job.get("message") or image_job.get("error") or "图片生成失败",
            500,
        )
        detail.update(
            {
                "stage_percent": max(0, min(int(image_job.get("progress") or 0), 100)),
                "current_step": "图片生成已停止",
                "error": message,
                "updated_at": now_iso(),
            }
        )
        update_job(
            str(job.get("id") or ""),
            status="failed",
            message=message,
            progress_detail=detail,
            event={"stage": "images", "label": "同步图片任务失败状态"},
        )
        reconciled += 1
    return reconciled


def completed_trend_runs() -> list[Path]:
    if not TREND_RUNS_ROOT.exists():
        return []
    rows = []
    for path in TREND_RUNS_ROOT.iterdir():
        if not path.is_dir():
            continue
        if (path / "04-editorial-topics.json").exists() and (
            (path / "19-final-article.html").exists()
            or (path / "12-rendered-article.html").exists()
        ):
            rows.append(path)
    return sorted(rows, key=lambda item: item.stat().st_mtime, reverse=True)


def load_trend_run(run_dir: Path, brief: str = "") -> dict[str, Any]:
    topics_payload = read_json(run_dir / "04-editorial-topics.json", {}) or {}
    topics = topics_payload.get("clusters") if isinstance(topics_payload, dict) else []
    scores = read_json(run_dir / "05-topic-scores.json", []) or []
    score_map = {str(item.get("topicId")): item for item in scores if isinstance(item, dict)}
    brief_tokens = {token.lower() for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", brief)}
    candidates = []
    for topic in topics if isinstance(topics, list) else []:
        if not isinstance(topic, dict):
            continue
        score = score_map.get(str(topic.get("id")), {})
        haystack = f"{topic.get('title', '')} {topic.get('summary', '')}".lower()
        brief_match = sum(1 for token in brief_tokens if token in haystack)
        candidates.append(
            {
                "id": str(topic.get("id") or ""),
                "title": clean_public_copy(topic.get("title") or "", 120),
                "summary": clean_public_copy(topic.get("summary") or "", 360),
                "keywords": list(topic.get("keywords") or [])[:8],
                "score": int(score.get("finalScore") or topic.get("confidence") or 0),
                "reason": clean_public_copy(score.get("reason") or "", 300),
                "recommended_use": score.get("recommendedUse") or "watch",
                "_brief_match": brief_match,
            }
        )
    candidates.sort(key=lambda item: (item["_brief_match"], item["score"]), reverse=True)
    for item in candidates:
        item.pop("_brief_match", None)

    title_data = read_json(run_dir / "18-final-title.json", {}) or read_json(
        run_dir / "10-title.json", {}
    )
    final_title = (
        str(title_data.get("title") or "") if isinstance(title_data, dict) else str(title_data or "")
    )
    article_path = (
        run_dir / "19-final-article.html"
        if (run_dir / "19-final-article.html").exists()
        else run_dir / "12-rendered-article.html"
    )
    article_html = article_path.read_text(encoding="utf-8", errors="ignore")
    review = read_json(run_dir / "13-quality-review.json", {}) or {}
    sources = read_json(run_dir / "01-sources.json", []) or []
    if isinstance(sources, dict):
        sources = sources.get("sources") or sources.get("data") or []
    compact_sources = []
    for item in sources if isinstance(sources, list) else []:
        if isinstance(item, str):
            compact_sources.append({"url": item})
        elif isinstance(item, dict):
            compact_sources.append(
                {
                    "title": clean_public_copy(item.get("title") or item.get("name") or "", 100),
                    "url": str(item.get("url") or "")[:500],
                }
            )
    selected = candidates[0] if candidates else {
        "id": "generated",
        "title": clean_public_copy(final_title, 120),
        "summary": clean_public_copy(article_html, 360),
        "score": int(review.get("overallScore") or 0),
    }
    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "generated_at": topics_payload.get("generatedAt") if isinstance(topics_payload, dict) else "",
        "candidates": candidates[:8],
        "selected": selected,
        "sources": compact_sources[:20],
        "final_title": clean_public_copy(final_title or selected.get("title") or "", 120),
        "quality": {
            "score": int(review.get("overallScore") or selected.get("score") or 0),
            "allow_publish": bool(review.get("allowPublish", False)),
            "summary": clean_public_copy(review.get("summary") or "", 420),
            "issues": [
                {
                    "severity": item.get("severity") or "medium",
                    "message": clean_public_copy(item.get("message") or "", 280),
                }
                for item in (review.get("issues") or [])[:8]
                if isinstance(item, dict)
            ],
        },
        "article_html": article_html,
        "article_text": clean_public_copy(article_html, 12000),
        "preview_path": str(article_path),
    }


def import_latest_trend(identifier: str, *, started_after: float | None = None) -> dict[str, Any]:
    job = load_job(identifier)
    for run_dir in completed_trend_runs():
        if started_after and run_dir.stat().st_mtime < started_after:
            continue
        result = load_trend_run(run_dir, job.get("brief") or "")
        selected = result["selected"]
        content = {
            "title": result["final_title"] or selected.get("title"),
            "xhs_title": clean_public_copy(selected.get("title") or result["final_title"], 20),
            "xhs_body": clean_public_copy(
                f"{selected.get('summary', '')}\n\n"
                "真正值得关注的不是又多了一个工具，而是它能否进入真实业务流程，"
                "带来可以核验的效率、客户或收入结果。\n\n"
                "#AI实战 #内容自动化 #企业AI",
                920,
            ),
            "article_html": result["article_html"],
            "article_text": result["article_text"],
            "quality": result["quality"],
            "preview_path": result["preview_path"],
        }
        violations = public_copy_violations(
            str(content["title"]), str(content["xhs_title"]), str(content["xhs_body"])
        )
        risk = {
            "level": "blocked" if violations else ("review" if result["quality"]["score"] < 80 else "low"),
            "checks": [
                {"label": "来源证据已保留", "ok": bool(result["sources"])},
                {"label": "质量审稿达到 80 分", "ok": result["quality"]["score"] >= 80},
                {"label": "公开文案无内部残留", "ok": not violations, "detail": "、".join(violations)},
                {"label": "尚未执行正式发布", "ok": True},
            ],
        }
        return update_job(
            identifier,
            status="content_ready",
            message="自动选题、内容生成和质量审稿完成",
            progress=52,
            research={key: value for key, value in result.items() if key not in {"article_html", "article_text"}},
            content=content,
            risk=risk,
            source_run=run_dir.name,
            event={"stage": "content", "label": "选题与内容完成"},
        )
    raise HubError("没有找到本轮新生成的 TrendPublish 产物")


def fetch_public_sources(identifier: str, brief: str) -> list[dict[str, str]]:
    evidence_dir = safe_job_dir(identifier) / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    rows: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for index, (name, url) in enumerate(PUBLIC_FEEDS, start=1):
        set_job_progress(
            identifier,
            phase="research",
            phase_label="抓取公开来源",
            stage_percent=8 + index * 10,
            overall_percent=7 + index * 4,
            message=f"正在读取 {name}，已完成 {index - 1}/{len(PUBLIC_FEEDS)} 个来源",
            current_step=f"读取 {name}",
            completed_steps=index - 1,
            total_steps=6,
            extra={"sources_completed": index - 1, "sources_total": len(PUBLIC_FEEDS)},
        )
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                "User-Agent": "YanFlow/1.1 (+local content research)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                rows.extend(parse_public_feed(response.read(), name))
        except (urllib.error.URLError, TimeoutError, HubError) as exc:
            failures.append({"source": name, "url": url, "error": redact(str(exc))})

    interest_tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", brief)
    }
    if any(token in brief for token in ("效率", "提效", "生产力")):
        interest_tokens.update(
            {"efficiency", "productivity", "workflow", "agent", "inference", "automation"}
        )

    def relevance(item: dict[str, str]) -> tuple[int, str]:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        return sum(1 for token in interest_tokens if token in text), item.get("published_at", "")

    rows.sort(key=relevance, reverse=True)
    deduplicated: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in rows:
        identity = item["url"].split("#", 1)[0].rstrip("/")
        if identity in seen:
            continue
        seen.add(identity)
        deduplicated.append(item)
    selected = deduplicated[:18]
    atomic_json(
        evidence_dir / "public-sources.json",
        {
            "brief": brief,
            "fetched_at": now_iso(),
            "feeds": [{"name": name, "url": url} for name, url in PUBLIC_FEEDS],
            "failures": failures,
            "items": selected,
        },
    )
    if not selected:
        details = "；".join(item["error"] for item in failures) or "公开来源没有返回内容"
        raise HubError(details)
    set_job_progress(
        identifier,
        phase="research",
        phase_label="抓取公开来源",
        stage_percent=38,
        overall_percent=18,
        message=f"已抓取并去重 {len(selected)} 条公开内容，正在匹配“{brief}”",
        current_step="去重与相关性排序",
        completed_steps=2,
        total_steps=6,
        extra={
            "items_found": len(rows),
            "items_selected": len(selected),
            "sources_completed": len(PUBLIC_FEEDS) - len(failures),
            "sources_total": len(PUBLIC_FEEDS),
        },
    )
    return selected


def content_generation_prompt(
    job: dict[str, Any],
    sources: list[dict[str, str]],
) -> str:
    compact_sources = [
        {
            "index": index,
            "title": item["title"],
            "summary": item.get("summary") or "",
            "source": item.get("source") or "",
            "published_at": item.get("published_at") or "",
            "url": item["url"],
        }
        for index, item in enumerate(sources, start=1)
    ]
    return f"""你是中文商业内容总编。只根据下方公开来源，完成一次可核验的自动选题和内容生产。

用户方向：{job.get("brief")}
核心读者：{job.get("audience")}
目标平台：{"、".join(job.get("targets") or [])}

公开来源：
{json.dumps(compact_sources, ensure_ascii=False, indent=2)}

严格要求：
1. 给出 5 个候选选题，评分 0-100，选出最适合“{job.get("brief")}”的一个。
2. 不得捏造来源中不存在的数字、研究结论、官方背书或政策结论；信息不足时明确写成判断或建议。
3. 公众号正文用简体中文，1200-1800 字，HTML 只使用 h1/h2/h3/p/strong/ul/li/a。
4. 正文末尾添加“参考来源”小节，每个来源写标题与可点击 URL。
5. 小红书标题不超过 20 个汉字，正文不超过 900 字，包含 3-5 个普通话题标签。
6. 不出现作者标签、封面/正文图/placeholder/payload/preview/draft、二维码、微信号、绝不封号、保证赚钱、百分之百有效。
7. 质量评分要根据来源一致性、结构、表达和平台适配综合给出；真实问题写入 issues。
8. 只返回符合给定 JSON Schema 的结果，不执行工具，不修改文件。
"""


def run_codex_content_generation(
    identifier: str,
    sources: list[dict[str, str]],
) -> dict[str, Any]:
    job = load_job(identifier)
    codex = shutil.which("codex")
    if not codex:
        raise HubError("本机 Codex CLI 未就绪，不能完成内容生成")
    evidence_dir = safe_job_dir(identifier) / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    schema_path = evidence_dir / "content-output.schema.json"
    prompt_path = evidence_dir / "content-generation.prompt.md"
    output_path = evidence_dir / "content-generation.json"
    log_path = evidence_dir / "content-generation.log"
    atomic_json(schema_path, CONTENT_OUTPUT_SCHEMA)
    prompt = content_generation_prompt(job, sources)
    prompt_path.write_text(prompt, encoding="utf-8")

    command = [
        codex,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "-C",
        str(APP_ROOT),
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "-m",
        CODEX_CONTENT_MODEL,
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "-",
    ]
    set_job_progress(
        identifier,
        phase="content",
        phase_label="自动选题与写作",
        stage_percent=45,
        overall_percent=25,
        message="公开来源已准备，Codex 正在评分候选选题",
        current_step="生成候选选题",
        completed_steps=3,
        total_steps=6,
        extra={"items_selected": len(sources)},
    )
    started = time.time()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=APP_ROOT,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process.stdin is None:
            raise HubError("内容生成进程没有输入通道")
        process.stdin.write(prompt)
        process.stdin.close()
        deadline = started + 480
        while process.poll() is None:
            if time.time() >= deadline:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise HubError("内容生成超过 8 分钟，已停止并保留日志")
            elapsed = int(time.time() - started)
            stage_percent = min(84, 48 + elapsed // 4)
            set_job_progress(
                identifier,
                phase="content",
                phase_label="自动选题与写作",
                stage_percent=stage_percent,
                overall_percent=min(47, 25 + stage_percent // 4),
                message=f"Codex 正在生成正文与双平台文案，内容阶段 {stage_percent}%",
                current_step="生成公众号正文和小红书文案",
                completed_steps=4,
                total_steps=6,
                extra={"elapsed_seconds": elapsed, "items_selected": len(sources)},
            )
            time.sleep(3)
        return_code = process.returncode

    if return_code != 0 or not output_path.exists():
        detail = log_path.read_text(encoding="utf-8", errors="ignore")[-3000:]
        raise HubError(redact(detail or "本机 Codex 没有返回内容"))
    payload = read_json(output_path)
    if not isinstance(payload, dict):
        raise HubError("本机 Codex 返回的内容不是有效 JSON")
    return payload


def store_codex_content(
    identifier: str,
    sources: list[dict[str, str]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    candidates = []
    for index, item in enumerate(payload.get("candidates") or [], start=1):
        if not isinstance(item, dict):
            continue
        candidates.append(
            {
                "id": clean_public_copy(item.get("id") or f"topic-{index}", 60),
                "title": clean_public_copy(item.get("title") or "", 120),
                "summary": clean_public_copy(item.get("summary") or "", 420),
                "score": max(0, min(int(item.get("score") or 0), 100)),
                "reason": clean_public_copy(item.get("reason") or "", 300),
                "recommended_use": clean_public_copy(
                    item.get("recommended_use") or "watch",
                    80,
                ),
            }
        )
    if not candidates:
        raise HubError("内容引擎没有返回候选选题")
    selected_id = str(payload.get("selected_id") or "")
    selected = next(
        (item for item in candidates if item["id"] == selected_id),
        max(candidates, key=lambda item: item["score"]),
    )
    article_html = str(payload.get("article_html") or "")
    title = clean_public_copy(payload.get("title") or selected["title"], 120)
    xhs_title = clean_public_copy(payload.get("xhs_title") or selected["title"], 20)
    xhs_body = clean_public_copy(payload.get("xhs_body") or "", 920)
    quality_payload = payload.get("quality") or {}
    quality_score = max(0, min(int(quality_payload.get("score") or 0), 100))
    violations = public_copy_violations(title, xhs_title, xhs_body)
    article_path = safe_job_dir(identifier) / "evidence" / "generated-article.html"
    article_path.parent.mkdir(exist_ok=True)
    article_path.write_text(article_html, encoding="utf-8")
    quality = {
        "score": quality_score,
        "allow_publish": quality_score >= 80 and not violations,
        "summary": clean_public_copy(quality_payload.get("summary") or "", 420),
        "issues": [
            {"severity": "medium", "message": clean_public_copy(item, 280)}
            for item in (quality_payload.get("issues") or [])[:6]
        ],
    }
    research = {
        "run_id": f"yanflow-rss-codex-{identifier}",
        "generated_at": now_iso(),
        "engine": "公开 RSS + 本机 Codex",
        "candidates": candidates,
        "selected": selected,
        "sources": [
            {
                "title": item["title"],
                "url": item["url"],
                "source": item.get("source") or "",
                "published_at": item.get("published_at") or "",
            }
            for item in sources
        ],
        "quality": quality,
        "final_title": title,
        "preview_path": str(article_path),
    }
    content = {
        "title": title,
        "xhs_title": xhs_title,
        "xhs_body": xhs_body,
        "article_html": article_html,
        "article_text": clean_public_copy(article_html, 12000),
        "quality": quality,
        "preview_path": str(article_path),
    }
    risk = {
        "level": "blocked" if violations else ("review" if quality_score < 80 else "low"),
        "checks": [
            {"label": "公开来源已保留", "ok": bool(sources)},
            {"label": "质量审稿达到 80 分", "ok": quality_score >= 80},
            {
                "label": "公开文案无内部残留",
                "ok": not violations,
                "detail": "、".join(violations),
            },
            {"label": "尚未执行正式发布", "ok": True},
        ],
    }
    return update_job(
        identifier,
        status="content_ready",
        message=f"已完成 5 个候选选题和双平台内容，质量评分 {quality_score}",
        progress=52,
        progress_detail={
            "phase": "content",
            "phase_label": "自动选题与写作",
            "stage_percent": 100,
            "current_step": "内容生成与审稿完成",
            "completed_steps": 6,
            "total_steps": 6,
            "updated_at": now_iso(),
            "items_selected": len(sources),
        },
        research=research,
        content=content,
        risk=risk,
        source_run=research["run_id"],
        event={"stage": "content", "label": "真实来源内容生成完成"},
    )


def run_rss_codex_research(identifier: str) -> dict[str, Any]:
    job = load_job(identifier)
    sources = fetch_public_sources(identifier, str(job.get("brief") or ""))
    payload = run_codex_content_generation(identifier, sources)
    set_job_progress(
        identifier,
        phase="content",
        phase_label="自动选题与写作",
        stage_percent=92,
        overall_percent=49,
        message="正文已经生成，正在做公开表达和质量检查",
        current_step="质量审稿与禁用词检查",
        completed_steps=5,
        total_steps=6,
        extra={"items_selected": len(sources)},
    )
    return store_codex_content(identifier, sources, payload)


def run_research(identifier: str, *, use_latest: bool = False) -> dict[str, Any]:
    job = load_job(identifier)
    if job.get("status") in IN_FLIGHT_STATES:
        raise HubError("当前任务正在运行")
    update_job(
        identifier,
        status="researching",
        message="正在抓取来源、去重、评分、选题和生成内容",
        progress=12,
        event={"stage": "research", "label": "启动选题与写作"},
    )
    if use_latest:
        return import_latest_trend(identifier)
    env = load_local_env()
    if not env.get("MINIMAX_API_KEY"):
        try:
            return run_rss_codex_research(identifier)
        except Exception as exc:
            update_job(
                identifier,
                status="failed",
                message=f"选题与内容流程停止：{redact(str(exc))}",
                progress_detail={
                    "phase": "research",
                    "phase_label": "选题与内容",
                    "stage_percent": 0,
                    "current_step": "流程停止",
                    "completed_steps": 0,
                    "total_steps": 6,
                    "error": redact(str(exc)),
                    "updated_at": now_iso(),
                },
                event={"stage": "research", "label": "选题失败"},
            )
            raise
    deno = shutil.which("deno")
    if not deno or not TREND_ROOT.exists():
        raise HubError("TrendPublish 未就绪")
    started = time.time()
    result = run_command(
        [deno, "task", "article", "--dry-run", "--max-articles", "5"],
        cwd=TREND_ROOT,
        timeout=900,
        env=load_local_env(),
    )
    evidence_dir = safe_job_dir(identifier) / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    (evidence_dir / "trendpublish.log").write_text(
        redact(result.stdout + "\n" + result.stderr), encoding="utf-8"
    )
    if result.code != 0:
        update_job(
            identifier,
            status="failed",
            message=f"选题与内容流程停止：{redact(result.stderr or result.stdout or '未知错误')}",
            progress=12,
            progress_detail={
                "phase": "research",
                "phase_label": "选题与内容",
                "stage_percent": 0,
                "current_step": "TrendPublish 停止",
                "completed_steps": 0,
                "total_steps": 6,
                "error": redact(result.stderr or result.stdout or "未知错误"),
                "updated_at": now_iso(),
            },
            event={"stage": "research", "label": "选题失败"},
        )
        raise HubError(redact(result.stderr or result.stdout or "TrendPublish 运行失败"))
    return import_latest_trend(identifier, started_after=started - 2)


def http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HubError(redact(str(exc))) from exc


def image_studio_healthy() -> bool:
    try:
        return bool(http_json(f"{IMAGE_STUDIO_URL}/api/health", timeout=2).get("ok"))
    except HubError:
        return False


def ensure_image_studio() -> None:
    if image_studio_healthy():
        return
    log_path = RUNTIME_ROOT / "image-studio.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, str(IMAGE_STUDIO_ROOT / "server.py"), "--port", "8765"],
        cwd=WORKSPACE_ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(30):
        if image_studio_healthy():
            return
        time.sleep(1)
    raise HubError("公众号贴图工作台未能启动")


def run_images(identifier: str) -> dict[str, Any]:
    job = load_job(identifier)
    if job.get("status") not in {"content_ready", "images_ready", "preflight_passed"}:
        raise HubError("请先完成自动选题和内容生成")
    update_job(
        identifier,
        status="imaging",
        message="正在生成 3:4 图组并执行中文、裁切、重复图片检查",
        progress=58,
        progress_detail={
            "phase": "images",
            "phase_label": "Image2 配图",
            "stage_percent": 5,
            "current_step": "准备九张图的内容大纲",
            "completed_steps": 0,
            "total_steps": 9,
            "updated_at": now_iso(),
        },
        event={"stage": "images", "label": "启动 Image2 图组"},
    )
    ensure_image_studio()
    content = job.get("content") or {}
    layout_id = str(job.get("layout") or DEFAULT_LAYOUT)
    layout = LAYOUTS.get(layout_id, LAYOUTS[DEFAULT_LAYOUT])
    response = http_json(
        f"{IMAGE_STUDIO_URL}/api/generate",
        method="POST",
        payload={
            "keyword": content.get("title") or job.get("brief"),
            "content_mode": "knowledge",
            "style": layout["image_style"],
            "palette": layout["palette"],
            "density": "ultra",
            "card_count": 9,
            "aspect_ratio": "3:4",
            "audience": job.get("audience"),
            "content_pattern": layout["content_pattern"],
            "source_text": str(content.get("article_text") or "")[:10000],
            "auto_publish": False,
        },
        timeout=30,
    )
    image_job_id = str(response.get("job_id") or response.get("id") or "")
    if not image_job_id:
        raise HubError("贴图工作台没有返回任务编号")
    for _ in range(180):
        image_job = http_json(f"{IMAGE_STUDIO_URL}/api/jobs/{image_job_id}", timeout=15)
        state = str(image_job.get("status") or "")
        image_percent = max(0, min(int(image_job.get("progress") or 0), 100))
        card_rows = image_job.get("card_progress") or []
        completed_cards = sum(
            1
            for item in card_rows
            if str(item.get("status") or "") in {"generated", "passed"}
        )
        set_job_progress(
            identifier,
            phase="images",
            phase_label="Image2 配图",
            stage_percent=image_percent,
            overall_percent=52 + round(image_percent * 0.3),
            message=str(image_job.get("message") or "Image2 正在生成图组"),
            current_step={
                "planning": "生成九张内容大纲",
                "validating_content": "校验每张图的信息量",
                "generating": f"生成图片 {completed_cards}/9",
                "quality_check": f"视觉质检 {completed_cards}/9",
            }.get(state, state or "等待图片引擎"),
            completed_steps=completed_cards,
            total_steps=9,
            extra={"image_job_id": image_job_id},
        )
        if state in {"completed", "failed"}:
            break
        time.sleep(5)
    else:
        raise HubError("图片生成超时，任务仍保留在贴图工作台")
    if state != "completed":
        raise HubError(str(image_job.get("message") or "图片生成失败"))
    source_dir = IMAGE_STUDIO_OUTPUTS / image_job_id
    assets_dir = safe_job_dir(identifier) / "assets"
    assets_dir.mkdir(exist_ok=True)
    images = []
    for index, item in enumerate(image_job.get("images") or [], start=1):
        source = source_dir / str(item.get("file") or "")
        if not source.exists():
            continue
        target = assets_dir / f"{index:02d}{source.suffix.lower()}"
        shutil.copy2(source, target)
        images.append(
            {
                "file": str(target.relative_to(safe_job_dir(identifier))),
                "width": item.get("width"),
                "height": item.get("height"),
                "source": item.get("source") or "Image2",
            }
        )
    if not images:
        raise HubError("图片任务完成但没有找到成品")
    return update_job(
        identifier,
        status="images_ready",
        message=f"{len(images)} 张图已生成并通过贴图工作台质检",
        progress=78,
        images={
            "status": "ready",
            "job_id": image_job_id,
            "layout": layout_id,
            "items": images,
        },
        progress_detail={
            "phase": "images",
            "phase_label": "Image2 配图",
            "stage_percent": 100,
            "current_step": f"{len(images)} 张图片生成与质检完成",
            "completed_steps": len(images),
            "total_steps": len(images),
            "updated_at": now_iso(),
        },
        event={"stage": "images", "label": f"{len(images)} 张图完成"},
    )


def image_hash(path: Path) -> str:
    if Image is None:
        raise HubError("缺少 Pillow，不能执行重复图片检查")
    with Image.open(path) as image:
        gray = image.convert("L").resize((16, 16))
        pixels = list(gray.getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):064x}"


def hash_distance(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def duplicate_image_matches(identifier: str, paths: list[Path]) -> list[dict[str, Any]]:
    candidates: list[tuple[str, Path]] = []
    if PUBLISHED_REFERENCES.exists():
        for path in PUBLISHED_REFERENCES.iterdir():
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                candidates.append(("用户确认已发布", path))
    for job_path in JOBS_ROOT.glob("*/job.json"):
        other = read_json(job_path, {}) or {}
        if other.get("id") == identifier:
            continue
        publish_state = str((other.get("publish") or {}).get("status") or "")
        if publish_state not in SUBMITTED_STATES:
            continue
        for item in (other.get("images") or {}).get("items") or []:
            path = job_path.parent / str(item.get("file") or "")
            if path.exists():
                candidates.append((f"历史任务 {other.get('id')}", path))
    matches = []
    known = []
    for label, path in candidates:
        try:
            known.append((label, path, image_hash(path)))
        except (OSError, HubError):
            continue
    for current in paths:
        current_hash = image_hash(current)
        for label, path, old_hash in known:
            distance = hash_distance(current_hash, old_hash)
            if distance <= 5:
                matches.append(
                    {
                        "current": current.name,
                        "source": label,
                        "reference": path.name,
                        "distance": distance,
                    }
                )
    return matches


def content_fingerprint(job: dict[str, Any]) -> str:
    content = job.get("content") or {}
    value = json.dumps(
        {
            "targets": job.get("targets"),
            "account_ids": job.get("account_ids") or {},
            "layout": job.get("layout") or DEFAULT_LAYOUT,
            "title": content.get("title"),
            "xhs_title": content.get("xhs_title"),
            "xhs_body": content.get("xhs_body"),
            "images": [item.get("file") for item in (job.get("images") or {}).get("items") or []],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rate_limit_checks(job: dict[str, Any], account_ids: list[str]) -> list[dict[str, Any]]:
    settings = read_json(SETTINGS_FILE, {}) or {}
    minimum_minutes = int(settings.get("minimum_interval_minutes") or 180)
    daily_limit = int(settings.get("daily_limit_per_account") or 3)
    today = dt.date.today()
    now = dt.datetime.now().astimezone()
    checks = []
    for account_id in account_ids:
        timestamps = []
        for path in JOBS_ROOT.glob("*/job.json"):
            other = read_json(path, {}) or {}
            publication = other.get("publish") or {}
            if account_id not in publication.get("account_ids", []):
                continue
            if str(publication.get("status") or "") not in SUBMITTED_STATES:
                continue
            raw = publication.get("submitted_at")
            try:
                timestamps.append(dt.datetime.fromisoformat(str(raw)))
            except (TypeError, ValueError):
                continue
        today_count = sum(1 for stamp in timestamps if stamp.astimezone().date() == today)
        latest = max(timestamps) if timestamps else None
        interval_ok = (
            latest is None
            or (now - latest.astimezone()).total_seconds() >= minimum_minutes * 60
        )
        checks.append(
            {
                "label": f"账号 {account_id[-6:]} 今日发布不超过 {daily_limit} 次",
                "ok": today_count < daily_limit,
                "detail": f"当前 {today_count} 次",
            }
        )
        checks.append(
            {
                "label": f"账号 {account_id[-6:]} 距上次发布至少 {minimum_minutes} 分钟",
                "ok": interval_ok,
                "detail": latest.isoformat(timespec="minutes") if latest else "无历史提交",
            }
        )
    return checks


def available_account(platform: str, preferred_id: str = "") -> dict[str, Any]:
    yxer = shutil.which("yxer")
    if not yxer:
        raise HubError("yxer 未安装")
    payload = run_json_command(
        [yxer, "accounts", "list", platform, "--status", "1", "--json"],
        timeout=60,
        env=load_local_env(),
    )
    rows = payload.get("data")
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    rows = (
        [
            item
            for item in rows
            if isinstance(item, dict) and not item.get("isLock") and not item.get("isFreeze")
        ]
        if isinstance(rows, list)
        else []
    )
    if preferred_id:
        rows = [item for item in rows if str(item.get("id") or "") == preferred_id]
    if platform == "微信公众号":
        preferred = [item for item in rows if item.get("platformAccountName") == "颜汝的世界"]
        if preferred:
            return preferred[0]
    if platform == "小红书":
        preferred = [item for item in rows if item.get("platformAccountName") == "颜汝AI"]
        if preferred:
            return preferred[0]
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise HubError(f"{platform}没有可用账号")
    raise HubError(f"{platform}有多个账号，请先在设置中指定")


def validate_upload(value: dict[str, Any]) -> dict[str, Any]:
    key = str(value.get("key") or value.get("path") or "")
    if not key:
        raise HubError("蚁小二上传结果缺少素材 key")
    uploaded = {
        key_name: value[key_name]
        for key_name in [
            "key",
            "name",
            "url",
            "bucket",
            "contentType",
            "format",
            "size",
            "width",
            "height",
            "duration",
        ]
        if key_name in value
    } | {"key": key}
    if not uploaded.get("format"):
        suffix = Path(key).suffix.lower().lstrip(".")
        content_type = str(uploaded.get("contentType") or "")
        uploaded["format"] = suffix or content_type.removeprefix("image/")
    return uploaded


def build_xhs_payload(
    account_id: str,
    title: str,
    description: str,
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    title = clean_public_copy(title, 20)
    description = clean_public_copy(description, 1000)
    form = {
        "formType": "task",
        "title": title,
        "description": description,
        "visibleType": 0,
        "images": images,
    }
    cover = images[0]
    return {
        "action": "publish",
        "publishType": "imageText",
        "platforms": ["小红书"],
        "publishChannel": "cloud",
        "publishArgs": {
            "accountForms": [
                {
                    "platformAccountId": account_id,
                    "contentPublishForm": form,
                    "cover": cover,
                    "coverKey": cover["key"],
                    "images": images,
                }
            ]
        },
    }


def prepare_publish_package(
    identifier: str,
    *,
    reuse_existing: bool = False,
) -> tuple[Path, list[str]]:
    job = load_job(identifier)
    image_items = (job.get("images") or {}).get("items") or []
    image_paths = [safe_job_dir(identifier) / str(item.get("file") or "") for item in image_items]
    if not image_paths or not all(path.exists() for path in image_paths):
        raise HubError("请先完成图片生成")
    violations = public_copy_violations(
        str((job.get("content") or {}).get("title") or ""),
        str((job.get("content") or {}).get("xhs_title") or ""),
        str((job.get("content") or {}).get("xhs_body") or ""),
    )
    if violations:
        raise HubError("公开文案未通过：" + "、".join(violations))
    duplicate_matches = duplicate_image_matches(identifier, image_paths)
    if duplicate_matches:
        update_job(
            identifier,
            status="blocked",
            message="图片与已发布内容相似，已阻止上传",
            progress=78,
            risk={"level": "blocked", "checks": [], "duplicate_matches": duplicate_matches},
        )
        raise HubError("图片与已发布内容重复或近似，已阻止发布")

    publish_dir = safe_job_dir(identifier) / "publish"
    publish_dir.mkdir(exist_ok=True)
    yxer = shutil.which("yxer")
    if not yxer or not AUDITED_PUBLISHER.exists():
        raise HubError("蚁小二审计发布工具未就绪")
    accounts = {
        platform: available_account(platform, str((job.get("account_ids") or {}).get(platform) or ""))
        for platform in job.get("targets") or []
    }
    account_ids = [str(account.get("id") or "") for account in accounts.values()]
    rate_checks = rate_limit_checks(job, account_ids)
    if not all(item["ok"] for item in rate_checks):
        update_job(
            identifier,
            status="blocked",
            message="账号发布频率达到安全上限，已停止",
            progress=80,
            risk={"level": "blocked", "checks": rate_checks},
        )
        raise HubError("账号发布频率达到安全上限")

    if reuse_existing:
        publication = job.get("publish") or {}
        manifest_value = str(publication.get("manifest") or "")
        manifest = Path(manifest_value)
        publish_root = (safe_job_dir(identifier) / "publish").resolve()
        if (
            not manifest_value
            or not manifest.exists()
            or not manifest.resolve().is_relative_to(publish_root)
        ):
            raise HubError("Dry-run 发布包已失效，请重新运行发布预检")
        if publication.get("fingerprint") != content_fingerprint(job):
            raise HubError("内容或图片在 Dry-run 后发生变化，请重新运行发布预检")
        return manifest, account_ids

    uploaded = []
    for path in image_paths:
        response = run_json_command(
            [yxer, "upload", "--file", str(path), "--bucket", "cloud-publish", "--json"],
            timeout=240,
            env=load_local_env(),
        )
        data = response.get("data")
        if not isinstance(data, dict):
            raise HubError("素材上传结果格式不正确")
        uploaded.append(validate_upload(data))
    atomic_json(publish_dir / "uploads.json", uploaded)

    items = []
    content = job.get("content") or {}
    if "小红书" in accounts:
        path = publish_dir / "xiaohongshu-imageText.json"
        atomic_json(
            path,
            build_xhs_payload(
                str(accounts["小红书"]["id"]),
                str(content.get("xhs_title") or content.get("title") or ""),
                str(content.get("xhs_body") or content.get("article_text") or ""),
                uploaded,
            ),
        )
        items.append(
            {"platform": "小红书", "type": "imageText", "payload": str(path), "channel": "cloud"}
        )
    if "微信公众号" in accounts:
        if not STICKER_BUILDER.exists():
            raise HubError("公众号贴图 payload 工具未就绪")
        path = publish_dir / "wechat-imageText.json"
        result = run_command(
            [
                sys.executable,
                str(STICKER_BUILDER),
                "--images-json",
                str(publish_dir / "uploads.json"),
                "--account-id",
                str(accounts["微信公众号"]["id"]),
                "--title",
                clean_public_copy(content.get("title") or job.get("brief"), 64),
                "--desc",
                clean_public_copy(content.get("article_text") or "", 180),
                "--content",
                clean_public_copy(content.get("xhs_body") or content.get("article_text") or "", 180),
                "--channel",
                "cloud",
                "--out",
                str(path),
            ],
            timeout=60,
        )
        if result.code != 0 or not path.exists():
            raise HubError(result.stderr or result.stdout or "公众号贴图 payload 生成失败")
        items.append(
            {"platform": "微信公众号", "type": "imageText", "payload": str(path), "channel": "cloud"}
        )
    manifest = publish_dir / "job.json"
    atomic_json(
        manifest,
        {
            "name": f"内容自动化中枢 {identifier}",
            "forbidden_terms": ["internal-only", "ahropci"],
            "items": items,
        },
    )
    update_job(
        identifier,
        risk={
            "level": "low",
            "checks": rate_checks
            + [
                {"label": "图片未命中历史发布库", "ok": True},
                {"label": "公开文案无内部标签和绝对化承诺", "ok": True},
                {"label": "只使用蚁小二审计发布入口", "ok": True},
            ],
        },
        publish={
            "status": "package_ready",
            "account_ids": account_ids,
            "fingerprint": content_fingerprint(job),
            "manifest": str(manifest),
        },
    )
    return manifest, account_ids


def run_publish(identifier: str, *, live: bool, confirmation: str = "") -> dict[str, Any]:
    job = load_job(identifier)
    current = str((job.get("publish") or {}).get("status") or "")
    if current in SUBMITTED_STATES:
        raise HubError("该任务已经提交或成功；请新建任务后再运行预检，避免破坏历史记录或重复发布")
    if live:
        if confirmation.strip() != "确认正式发布":
            raise HubError("正式发布需要输入：确认正式发布")
        if current != "dry_run_passed":
            raise HubError("正式发布前必须先通过完整 dry-run")
    update_job(
        identifier,
        status="publishing" if live else "preflighting",
        message="正在正式提交并核验平台详情" if live else "正在执行账号、Schema、校验与 dry-run",
        progress=94 if live else 84,
        progress_detail={
            "phase": "publish",
            "phase_label": "正式发布" if live else "发布预检",
            "stage_percent": 15,
            "current_step": "账号、素材、Schema 与重复任务检查",
            "completed_steps": 1,
            "total_steps": 5,
            "updated_at": now_iso(),
        },
        event={"stage": "publish", "label": "正式提交" if live else "启动发布预检"},
    )
    manifest, account_ids = prepare_publish_package(identifier, reuse_existing=live)
    publish_root = safe_job_dir(identifier) / "publish"
    run_dir = publish_root / ("live" if live else "dry-run") / (
        dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    )
    command = [
        sys.executable,
        str(AUDITED_PUBLISHER),
        "--yxer",
        shutil.which("yxer") or "yxer",
        "run",
        str(manifest),
        "--output",
        str(run_dir),
        "--poll-attempts",
        "18",
        "--poll-seconds",
        "5",
    ]
    if live:
        command.append("--live")
    result = run_command(command, cwd=WORKSPACE_ROOT, timeout=720, env=load_local_env())
    summary = read_json(run_dir / "summary.json")
    if not isinstance(summary, dict):
        try:
            summary = json.loads(result.stdout)
        except json.JSONDecodeError:
            summary = {"ok": False, "items": [], "error": result.stderr or result.stdout}
    items = summary.get("items") or []
    task_ids = []
    public_urls = []
    platform_results = []
    blockers = []
    successful_platforms = []
    for item in items:
        task_ids.extend(item.get("task_set_ids") or [])
        public_urls.extend(item.get("public_urls") or [])
        blockers.extend(str(value) for value in item.get("blockers") or [])
        platform_result = str(item.get("platform_result") or "")
        if platform_result.lower() in {"success", "allsuccessful"} or item.get("public_urls"):
            successful_platforms.append(str(item.get("platform") or "目标平台"))
        platform_results.append(
            {
                "platform": item.get("platform"),
                "api_submission": item.get("api_submission"),
                "platform_result": item.get("platform_result"),
                "public_urls": item.get("public_urls") or [],
                "blockers": item.get("blockers") or [],
            }
        )
    if result.code != 0 or not summary.get("ok"):
        message = "；".join(blockers) or str(summary.get("error") or "发布审计未通过")
        if live and successful_platforms:
            return update_job(
                identifier,
                status="partial_success",
                message=f"{'、'.join(successful_platforms)}发布成功；其他平台已停止：{clean_public_copy(message, 320)}",
                progress=100,
                publish={
                    "status": "partial_success",
                    "mode": "live",
                    "run_dir": str(run_dir),
                    "blockers": blockers,
                    "account_ids": account_ids,
                    "task_set_ids": task_ids,
                    "public_urls": public_urls,
                    "platform_results": platform_results,
                    "submitted_at": now_iso(),
                    "fingerprint": content_fingerprint(job),
                },
                progress_detail={
                    "phase": "publish",
                    "phase_label": "正式发布",
                    "stage_percent": 100,
                    "current_step": f"{'、'.join(successful_platforms)}成功，其他平台保留阻断原因",
                    "completed_steps": 5,
                    "total_steps": 5,
                    "error": clean_public_copy(message, 500),
                    "updated_at": now_iso(),
                },
                event={"stage": "publish", "label": "部分平台发布成功"},
            )
        return update_job(
            identifier,
            status="failed",
            message=clean_public_copy(message, 500),
            progress=86 if not live else 95,
            publish={
                "status": "failed",
                "mode": "live" if live else "dry-run",
                "run_dir": str(run_dir),
                "blockers": blockers,
                "account_ids": account_ids,
            },
            progress_detail={
                "phase": "publish",
                "phase_label": "正式发布" if live else "发布预检",
                "stage_percent": 0,
                "current_step": "发布闸门阻止",
                "completed_steps": 0,
                "total_steps": 5,
                "error": clean_public_copy(message, 500),
                "updated_at": now_iso(),
            },
            event={"stage": "publish", "label": "发布闸门阻止"},
        )
    if not live:
        return update_job(
            identifier,
            status="preflight_passed",
            message="完整发布预检通过，尚未正式发表",
            progress=92,
            publish={
                "status": "dry_run_passed",
                "run_dir": str(run_dir),
                "account_ids": account_ids,
                "platform_results": platform_results,
                "fingerprint": content_fingerprint(job),
                "manifest": str(manifest),
            },
            progress_detail={
                "phase": "publish",
                "phase_label": "发布预检",
                "stage_percent": 100,
                "current_step": "账号、Schema、字段和重复任务检查全部通过",
                "completed_steps": 5,
                "total_steps": 5,
                "updated_at": now_iso(),
            },
            event={"stage": "publish", "label": "Dry-run 通过"},
        )
    status = "success" if public_urls else "submitted"
    return update_job(
        identifier,
        status="published" if public_urls else "submitted",
        message="平台已返回公开链接" if public_urls else "已提交平台，等待平台审核或公开链接",
        progress=100,
        publish={
            "status": status,
            "run_dir": str(run_dir),
            "account_ids": account_ids,
            "task_set_ids": task_ids,
            "public_urls": public_urls,
            "platform_results": platform_results,
            "submitted_at": now_iso(),
            "fingerprint": content_fingerprint(job),
        },
        progress_detail={
            "phase": "publish",
            "phase_label": "正式发布",
            "stage_percent": 100,
            "current_step": "平台详情与公开链接核验完成" if public_urls else "平台已接收，等待审核",
            "completed_steps": 5,
            "total_steps": 5,
            "updated_at": now_iso(),
        },
        event={"stage": "publish", "label": "正式发布完成" if public_urls else "已提交平台"},
    )


def run_safe_pipeline(identifier: str, *, use_latest: bool = False) -> None:
    try:
        run_research(identifier, use_latest=use_latest)
        run_images(identifier)
        run_publish(identifier, live=False)
    except Exception as exc:  # Background worker must leave a visible, redacted state.
        try:
            job = load_job(identifier)
            if job.get("status") not in {"failed", "blocked"}:
                update_job(
                    identifier,
                    status="failed",
                    message=redact(str(exc)),
                    event={"stage": "system", "label": "流程停止"},
                )
        except Exception:
            pass


def seed_demo_from_latest() -> dict[str, Any] | None:
    ensure_runtime()
    if list_jobs(limit=1):
        return None
    runs = completed_trend_runs()
    if not runs:
        return None
    created = create_job(
        {
            "brief": "企业 AI 内容自动化与真实业务落地",
            "audience": "企业老板、业务负责人和内容创作者",
            "targets": ["小红书", "微信公众号"],
            "mode": "manual",
        }
    )
    imported = import_latest_trend(created["id"])
    job = load_job(imported["id"])
    job["demo"] = True
    job["message"] = "已导入一条历史真实选题产物作为界面样本，未生成新图片、未发布"
    return save_job(job)


def default_settings() -> dict[str, Any]:
    value = read_json(SETTINGS_FILE, {}) or {}
    return {
        "schedule_enabled": bool(value.get("schedule_enabled", False)),
        "schedule_time": str(value.get("schedule_time") or "09:30"),
        "weekdays": value.get("weekdays") or [1, 2, 3, 4, 5],
        "daily_limit_per_account": int(value.get("daily_limit_per_account") or 3),
        "minimum_interval_minutes": int(value.get("minimum_interval_minutes") or 180),
        "live_automation_enabled": False,
    }


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = default_settings()
    settings["schedule_enabled"] = bool(payload.get("schedule_enabled", False))
    time_value = str(payload.get("schedule_time") or settings["schedule_time"])
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value):
        raise HubError("定时时间格式应为 HH:MM")
    settings["schedule_time"] = time_value
    weekdays = [int(value) for value in payload.get("weekdays", settings["weekdays"])]
    settings["weekdays"] = sorted({value for value in weekdays if 1 <= value <= 7})
    settings["daily_limit_per_account"] = max(
        1, min(int(payload.get("daily_limit_per_account") or 3), 3)
    )
    settings["minimum_interval_minutes"] = max(
        180, int(payload.get("minimum_interval_minutes") or 180)
    )
    settings["live_automation_enabled"] = False
    atomic_json(SETTINGS_FILE, settings)
    return settings


class Scheduler:
    def __init__(self) -> None:
        self._last_key = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(30):
            settings = default_settings()
            if not settings["schedule_enabled"]:
                continue
            current = dt.datetime.now()
            key = current.strftime("%Y-%m-%d %H:%M")
            if (
                current.isoweekday() not in settings["weekdays"]
                or current.strftime("%H:%M") != settings["schedule_time"]
                or key == self._last_key
            ):
                continue
            self._last_key = key
            job = create_job(
                {
                    "brief": "从已配置来源中选择今天最值得讲、最适合企业经营者的 AI 主题",
                    "audience": "企业老板、业务负责人和内容创作者",
                    "targets": ["小红书", "微信公众号"],
                    "mode": "safe_auto",
                }
            )
            threading.Thread(
                target=run_safe_pipeline,
                args=(job["id"],),
                daemon=True,
            ).start()

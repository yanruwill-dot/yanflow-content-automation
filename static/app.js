"use strict";

const token = document.querySelector('meta[name="yanflow-token"]').content;
const state = {
  jobs: [],
  currentJob: null,
  connectors: null,
  settings: null,
  settingsDirty: false,
  busy: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function clampText(value, length = 180) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

const fallbackLayouts = [
  { id: "editorial", label: "商业杂志", description: "深墨标题区、青柠强调，适合观点和商业判断" },
  { id: "clean", label: "清爽阅读", description: "白底松石绿、短段落，适合教程和行动清单" },
  { id: "song", label: "宋式留白", description: "米白纸感、朱砂点题，适合故事和深度文章" },
];

function layoutRows() {
  return state.connectors?.layouts?.length ? state.connectors.layouts : fallbackLayouts;
}

function accountRows(platform) {
  return (state.connectors?.accounts || []).filter((item) => item.platform === platform && item.ready);
}

function defaultAccountId(platform) {
  const rows = accountRows(platform);
  const preferred = platform === "小红书" ? "颜汝AI" : "颜汝的世界";
  return rows.find((item) => item.name === preferred)?.id || rows[0]?.id || "";
}

function fillAccountSelect(select, platform, selectedId = "", enabled = true) {
  if (!select) return;
  const rows = accountRows(platform);
  const options = [];
  if (!rows.length) {
    options.push('<option value="">暂无可用账号，先重新检查连接</option>');
  } else {
    options.push(...rows.map((account) => (
      `<option value="${escapeHtml(account.id)}">${escapeHtml(account.name)} · ${escapeHtml(account.id.slice(-6))}</option>`
    )));
  }
  if (selectedId && !rows.some((item) => item.id === selectedId)) {
    options.unshift(`<option value="${escapeHtml(selectedId)}">当前配置 · ${escapeHtml(selectedId.slice(-6))}</option>`);
  }
  select.innerHTML = options.join("");
  select.value = selectedId || defaultAccountId(platform);
  select.disabled = !enabled || !rows.length;
}

function fillLayoutSelect(select, selectedId = "editorial", enabled = true) {
  if (!select) return;
  const rows = layoutRows();
  select.innerHTML = rows
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)}</option>`)
    .join("");
  select.value = rows.some((item) => item.id === selectedId) ? selectedId : "editorial";
  select.disabled = !enabled;
}

function selectedLayoutDescription() {
  const selected = layoutRows().find((item) => item.id === $("#layoutSelect").value);
  $("#layoutDescription").textContent = selected?.description || "";
}

function syncNewJobSettings() {
  const targets = new Set($$('input[name="target"]:checked').map((input) => input.value));
  const xhsSelected = $("#xhsAccountSelect").value;
  const wechatSelected = $("#wechatAccountSelect").value;
  fillAccountSelect($("#xhsAccountSelect"), "小红书", xhsSelected, targets.has("小红书"));
  fillAccountSelect($("#wechatAccountSelect"), "微信公众号", wechatSelected, targets.has("微信公众号"));
  fillLayoutSelect($("#layoutSelect"), $("#layoutSelect").value || "editorial", true);
  selectedLayoutDescription();
}

async function api(path, options = {}) {
  const init = {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      "X-Yanflow-Token": token,
      ...(options.headers || {}),
    },
    ...options,
  };
  if (options.body && typeof options.body !== "string") {
    init.body = JSON.stringify(options.body);
    init.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, init);
  const payload = await response.json().catch(() => ({ ok: false, error: "服务返回了无法识别的结果" }));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败（${response.status}）`);
  }
  return payload;
}

function toast(title, detail = "", error = false) {
  const node = document.createElement("div");
  node.className = `toast${error ? " error" : ""}`;
  node.innerHTML = `<b>${escapeHtml(title)}</b><small>${escapeHtml(detail)}</small>`;
  $("#toastStack").append(node);
  window.setTimeout(() => node.remove(), 5200);
}

function stageLabel(status) {
  const labels = {
    created: "待启动",
    researching: "选题中",
    content_ready: "内容完成",
    imaging: "配图中",
    images_ready: "图片完成",
    preflighting: "发布预检",
    preflight_passed: "预检通过",
    publishing: "正式提交",
    submitted: "平台处理中",
    published: "已核验发布",
    partial_success: "部分发布成功",
    failed: "流程已停止",
    blocked: "风控已拦截",
  };
  return labels[status] || status || "待启动";
}

function stageFlags(job) {
  const status = job?.status || "";
  const hasResearch = Boolean(job?.research);
  const hasContent = Boolean(job?.content);
  const hasImages = Boolean(job?.images?.items?.length);
  const hasRisk = ["low", "review", "blocked"].includes(job?.risk?.level);
  const publishState = job?.publish?.status || "";
  return {
    research: {
      done: hasResearch,
      active: status === "researching",
    },
    content: {
      done: hasContent,
      active: status === "researching" && hasResearch,
    },
    images: {
      done: hasImages,
      active: status === "imaging",
    },
    risk: {
      done: hasRisk && publishState !== "not_started",
      active: status === "preflighting" || (hasImages && !["dry_run_passed", "success", "submitted", "partial_success"].includes(publishState)),
    },
    publish: {
      done: ["dry_run_passed", "success", "submitted", "partial_success"].includes(publishState),
      active: ["preflighting", "publishing", "submitted"].includes(status),
    },
  };
}

function renderJobSelect() {
  const select = $("#jobSelect");
  const currentId = state.currentJob?.id || select.value;
  if (!state.jobs.length) {
    select.innerHTML = '<option value="">暂无任务</option>';
    return;
  }
  select.innerHTML = state.jobs
    .map((job) => {
      const marker = job.demo ? "样本" : stageLabel(job.status);
      return `<option value="${escapeHtml(job.id)}">${escapeHtml(marker)} · ${escapeHtml(clampText(job.brief, 34))}</option>`;
    })
    .join("");
  select.value = state.jobs.some((job) => job.id === currentId) ? currentId : state.jobs[0].id;
}

function renderMetrics(job) {
  const today = new Date().toLocaleDateString("sv-SE");
  $("#todayJobs").textContent = state.jobs.filter((item) => String(item.created_at || "").slice(0, 10) === today).length;
  $("#currentStage").textContent = stageLabel(job?.status);
  $("#currentMessage").textContent = job?.message || "选择一个任务查看";
  const score = job?.content?.quality?.score ?? job?.research?.quality?.score;
  $("#qualityScore").textContent = Number.isFinite(Number(score)) ? `${score}` : "—";
  const risk = job?.risk?.level;
  $("#riskLevel").textContent = {
    low: "低风险",
    review: "需复核",
    blocked: "已拦截",
    pending: "未检查",
  }[risk] || "未检查";
}

function renderPipeline(job) {
  const flags = stageFlags(job);
  $$("#pipeline article").forEach((node) => {
    const value = flags[node.dataset.stage] || {};
    node.classList.toggle("done", Boolean(value.done));
    node.classList.toggle("active", Boolean(value.active));
  });
}

function renderProgress(job) {
  const detail = job?.progress_detail || {};
  const overall = Math.max(0, Math.min(Number(job?.progress || 0), 100));
  const stage = Math.max(0, Math.min(Number(detail.stage_percent || 0), 100));
  const completed = Number(detail.completed_steps || 0);
  const total = Number(detail.total_steps || 6);
  $("#overallProgressBar").style.width = `${overall}%`;
  $("#stageProgressBar").style.width = `${stage}%`;
  $("#overallProgressText").textContent = `${overall}%`;
  $("#stageProgressText").textContent = `${stage}%`;
  $("#progressPercent").textContent = `${stage}%`;
  $("#progressPhase").textContent = detail.phase_label || stageLabel(job?.status);
  $("#progressStep").textContent = detail.error
    ? `停止原因：${detail.error}`
    : detail.current_step || job?.message || "等待任务";
  $("#progressCount").textContent = `${completed} / ${Math.max(total, 1)} 步`;
  const stats = [];
  if (detail.sources_total) {
    stats.push(`来源 ${detail.sources_completed || 0}/${detail.sources_total}`);
  }
  if (detail.items_selected) {
    stats.push(`有效内容 ${detail.items_selected} 条`);
  }
  if (detail.elapsed_seconds) {
    stats.push(`已运行 ${detail.elapsed_seconds} 秒`);
  }
  if (detail.image_job_id) {
    stats.push(`图片任务 ${String(detail.image_job_id).slice(-8)}`);
  }
  $("#progressStats").textContent = stats.join(" · ") || job?.message || "等待任务";
  const updated = detail.updated_at ? new Date(detail.updated_at) : null;
  $("#progressUpdated").textContent = updated && !Number.isNaN(updated.getTime())
    ? `更新 ${updated.toLocaleTimeString("zh-CN", { hour12: false })}`
    : "—";
  $("#progressConsole").classList.toggle("failed", ["failed", "blocked"].includes(job?.status));
}

function renderTopics(job) {
  const topics = job?.research?.candidates || [];
  const selectedId = job?.research?.selected?.id;
  $("#topicCount").textContent = `${topics.length} 条`;
  if (!topics.length) {
    $("#topicList").innerHTML = `
      <div class="empty-state">
        <span>${job?.status === "researching" ? "正在寻找信号" : "尚未运行"}</span>
        <p>自动选题完成后，这里会显示评分、判断理由和推荐用途。</p>
      </div>`;
    return;
  }
  $("#topicList").innerHTML = topics
    .map((topic, index) => `
      <article class="topic-card${topic.id === selectedId || (!selectedId && index === 0) ? " selected" : ""}">
        <span>${String(index + 1).padStart(2, "0")}</span>
        <div>
          <h4>${escapeHtml(topic.title || "未命名选题")}</h4>
          <p>${escapeHtml(clampText(topic.reason || topic.summary || "已进入候选池", 110))}</p>
        </div>
        <strong>${escapeHtml(topic.score ?? "—")}<small>SCORE</small></strong>
      </article>`)
    .join("");
}

function renderContent(job) {
  const content = job?.content;
  const quality = content?.quality || job?.research?.quality || {};
  if (!content) {
    $("#contentPreview").innerHTML = `
      <div class="content-kicker">SELECTED STORY</div>
      <h4>等待系统选出今天最值得讲的主题</h4>
      <p>正文生成后，这里会显示公众号标题、小红书标题、内容摘要和质量审稿。</p>`;
    $("#openPreviewButton").disabled = true;
  } else {
    const urls = job?.publish?.public_urls || [];
    $("#contentPreview").innerHTML = `
      <div class="content-kicker">${job.demo ? "IMPORTED REAL RUN · 未发布" : "SELECTED STORY"}</div>
      <h4>${escapeHtml(content.title || "内容标题")}</h4>
      <p>${escapeHtml(clampText(content.article_text || content.xhs_body, 330))}</p>
      <div class="platform-copy">
        <div><span>小红书标题</span><b>${escapeHtml(content.xhs_title || "—")}</b></div>
        <div><span>发布状态</span><b>${escapeHtml(urls.length ? "已返回公开链接" : stageLabel(job.status))}</b></div>
      </div>`;
    $("#openPreviewButton").disabled = !content.preview_path;
  }
  const score = Number(quality.score || 0);
  $("#factScore").textContent = score ? `${Math.min(99, score + 2)}` : "—";
  $("#expressionScore").textContent = score ? `${score}` : "—";
  $("#platformScore").textContent = score ? `${Math.max(0, score - 3)}` : "—";
}

function renderImages(job) {
  const items = job?.images?.items || [];
  const grid = $("#imageGrid");
  if (!items.length) {
    grid.innerHTML = `
      <div class="image-placeholder"><span>01</span><b>封面</b></div>
      <div class="image-placeholder"><span>02</span><b>痛点</b></div>
      <div class="image-placeholder"><span>03</span><b>逻辑</b></div>
      <div class="image-placeholder"><span>04—09</span><b>流程与行动</b></div>`;
  } else {
    grid.innerHTML = items
      .map((item, index) => {
        const name = String(item.file || "").split("/").pop();
        return `<figure class="image-tile">
          <img src="/api/jobs/${encodeURIComponent(job.id)}/assets/${encodeURIComponent(name)}" alt="内容配图 ${index + 1}" loading="lazy" />
          <span>${String(index + 1).padStart(2, "0")} · ${escapeHtml(item.source || "Image2")}</span>
        </figure>`;
      })
      .join("");
  }
  $("#imageButton").disabled = state.busy || !job?.content || ["imaging", "preflighting", "publishing"].includes(job?.status);
  $("#imageButton").textContent = job?.status === "imaging" ? "正在生成…" : items.length ? "重新生成图组" : "生成图组";
}

function renderCurrentPublishSettings(job) {
  const xhs = $("#currentXhsAccount");
  const wechat = $("#currentWechatAccount");
  const layout = $("#currentLayout");
  const button = $("#saveTaskSettingsButton");
  if (!job) {
    fillAccountSelect(xhs, "小红书", "", false);
    fillAccountSelect(wechat, "微信公众号", "", false);
    fillLayoutSelect(layout, "editorial", false);
    button.disabled = true;
    return;
  }
  const targets = new Set(job.targets || []);
  const publish = job.publish || {};
  const locked = state.busy ||
    ["researching", "writing", "imaging", "preflighting", "publishing", "submitted", "published", "partial_success"].includes(job.status) ||
    ["submitted", "reviewing", "success", "allsuccessful", "partial_success"].includes(publish.status) ||
    Boolean(publish.task_set_ids?.length || publish.public_urls?.length || publish.publishId || publish.publish_id);
  if (!state.settingsDirty) {
    fillAccountSelect(xhs, "小红书", job.account_ids?.["小红书"] || "", targets.has("小红书") && !locked);
    fillAccountSelect(wechat, "微信公众号", job.account_ids?.["微信公众号"] || "", targets.has("微信公众号") && !locked);
    fillLayoutSelect(layout, job.layout || "editorial", !locked);
  } else {
    xhs.disabled = !targets.has("小红书") || locked || !accountRows("小红书").length;
    wechat.disabled = !targets.has("微信公众号") || locked || !accountRows("微信公众号").length;
    layout.disabled = locked;
  }
  button.disabled = locked;
  button.textContent = locked ? "设置已锁定" : "保存本任务设置";
}

function renderChecks(job) {
  const riskChecks = job?.risk?.checks || [];
  const publishState = job?.publish?.status || "";
  const defaults = [
    {
      label: "来源与事实",
      detail: "保留原始来源和风险说明",
      ok: Boolean(job?.research?.sources?.length && (job?.content?.quality?.score || 0) >= 80),
    },
    {
      label: "内容与图片不重复",
      detail: "感知哈希对比历史发布库",
      ok: riskChecks.some((item) => String(item.label).includes("图片未命中")),
    },
    {
      label: "账号与发布频率",
      detail: "3小时间隔、单账号每日最多3次",
      ok: riskChecks.filter((item) => String(item.label).includes("账号")).every((item) => item.ok) &&
        riskChecks.some((item) => String(item.label).includes("账号")),
    },
    {
      label: "蚁小二完整 Dry-run",
      detail: "账号、Schema、校验、重复任务",
      ok: ["dry_run_passed", "success", "submitted", "partial_success"].includes(publishState),
    },
  ];
  $("#checkList").innerHTML = defaults
    .map((item) => `
      <label class="${item.ok ? "ok" : ""}">
        <span></span><p><b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.detail)}</small></p>
      </label>`)
    .join("");

  const hasImages = Boolean(job?.images?.items?.length);
  const blocked = ["blocked", "publishing", "submitted", "published", "partial_success"].includes(job?.status);
  $("#dryRunButton").disabled = state.busy || !hasImages || blocked;
  $("#dryRunButton").textContent = job?.status === "preflighting" ? "正在预检…" : "运行发布预检";
  $("#liveButton").disabled = state.busy || publishState !== "dry_run_passed";
  $("#gateState").textContent = publishState === "dry_run_passed" ? "READY" : job?.risk?.level === "blocked" ? "BLOCKED" : "LOCKED";
  $("#gateState").classList.toggle("open", publishState === "dry_run_passed");
}

function renderJob(job) {
  state.currentJob = job || null;
  renderMetrics(job);
  renderPipeline(job);
  renderProgress(job);
  renderTopics(job);
  renderContent(job);
  renderImages(job);
  renderCurrentPublishSettings(job);
  renderChecks(job);
}

async function loadJobs(selectId = "") {
  const payload = await api("/api/jobs");
  state.jobs = payload.jobs || [];
  if (selectId) {
    const summary = state.jobs.find((job) => job.id === selectId);
    if (summary) state.currentJob = summary;
  }
  renderJobSelect();
  const id = selectId || state.currentJob?.id || state.jobs[0]?.id;
  if (id) {
    await loadJob(id);
  } else {
    renderJob(null);
  }
}

async function loadJob(id, quiet = false) {
  try {
    const payload = await api(`/api/jobs/${encodeURIComponent(id)}`);
    if (state.currentJob?.id !== id) state.settingsDirty = false;
    renderJob(payload.job);
    const index = state.jobs.findIndex((item) => item.id === id);
    if (index >= 0) state.jobs[index] = payload.job;
    renderJobSelect();
  } catch (error) {
    if (!quiet) toast("任务读取失败", error.message, true);
  }
}

function renderConnectors(payload) {
  state.connectors = payload;
  const connectors = Object.values(payload.connectors || {});
  $("#connectorList").innerHTML = connectors
    .map((item) => `
      <div class="connector ${item.ready ? "ready" : ""}">
        <span></span>
        <div><b>${escapeHtml(item.label)}</b><small>${escapeHtml(item.error || item.detail || "未连接")}</small></div>
      </div>`)
    .join("");
  const ready = connectors.length && connectors.every((item) => item.ready);
  $("#systemPill").classList.toggle("ready", ready);
  $("#systemPill").querySelector("b").textContent = ready ? "本机能力已就绪" : "部分能力待处理";
  const accounts = payload.accounts || [];
  $("#accountList").innerHTML = accounts.length
    ? `<h4>可用发布账号</h4>${accounts
        .map((account) => `
          <div class="account-row">
            <span>${escapeHtml(account.platform)} · ${escapeHtml(account.name)}</span>
            <small class="${account.ready ? "ready" : ""}">${escapeHtml(account.ready ? "可用" : account.reason || "需检查")}</small>
          </div>`)
        .join("")}`
    : '<h4>账号列表仅在“重新检查”时读取</h4>';
  syncNewJobSettings();
  if (state.currentJob) renderCurrentPublishSettings(state.currentJob);
}

async function loadStatus(includeAccounts = false) {
  $("#refreshStatusButton").disabled = true;
  try {
    const payload = await api(`/api/status${includeAccounts ? "?accounts=1" : ""}`);
    renderConnectors(payload);
    if (includeAccounts) toast("连接检查完成", "只读取状态，没有发出内容");
  } catch (error) {
    $("#systemPill").querySelector("b").textContent = "系统检查失败";
    toast("连接检查失败", error.message, true);
  } finally {
    $("#refreshStatusButton").disabled = false;
  }
}

function renderSettings(settings) {
  state.settings = settings;
  $("#scheduleEnabled").checked = Boolean(settings.schedule_enabled);
  $("#scheduleTime").value = settings.schedule_time || "09:30";
  const active = new Set((settings.weekdays || []).map(Number));
  $$("#weekdayRow input").forEach((input) => {
    input.checked = active.has(Number(input.value));
  });
  $("#dailyLimit").value = settings.daily_limit_per_account || 3;
  $("#minimumInterval").value = settings.minimum_interval_minutes || 180;
}

async function loadSettings() {
  try {
    const payload = await api("/api/settings");
    renderSettings(payload.settings);
  } catch (error) {
    toast("设置读取失败", error.message, true);
  }
}

async function runAction(path, detail) {
  if (!state.currentJob || state.busy) return;
  state.busy = true;
  renderJob(state.currentJob);
  try {
    await api(path, { method: "POST", body: {} });
    toast(detail, "任务已进入后台，可在当前页面查看实时阶段");
    window.setTimeout(() => loadJob(state.currentJob.id, true), 600);
  } catch (error) {
    toast(`${detail}失败`, error.message, true);
  } finally {
    state.busy = false;
    if (state.currentJob) renderJob(state.currentJob);
  }
}

$("#jobForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const brief = $("#briefInput").value.trim();
  const audience = $("#audienceInput").value.trim();
  const targets = $$('input[name="target"]:checked').map((input) => input.value);
  const accountIds = {};
  if (targets.includes("小红书") && $("#xhsAccountSelect").value) {
    accountIds["小红书"] = $("#xhsAccountSelect").value;
  }
  if (targets.includes("微信公众号") && $("#wechatAccountSelect").value) {
    accountIds["微信公众号"] = $("#wechatAccountSelect").value;
  }
  state.busy = true;
  try {
    const created = await api("/api/jobs", {
      method: "POST",
      body: {
        brief,
        audience,
        targets,
        account_ids: accountIds,
        layout: $("#layoutSelect").value,
        mode: "safe_auto",
      },
    });
    state.currentJob = created.job;
    toast("内容任务已创建", "开始从真实来源进行选题和生成，默认只跑到 Dry-run");
    await api(`/api/jobs/${created.job.id}/run`, {
      method: "POST",
      body: { use_latest: false },
    });
    $("#briefInput").value = "";
    await loadJobs(created.job.id);
  } catch (error) {
    toast("无法启动任务", error.message, true);
  } finally {
    state.busy = false;
    if (state.currentJob) renderJob(state.currentJob);
  }
});

$("#jobSelect").addEventListener("change", (event) => loadJob(event.target.value));
$$('input[name="target"]').forEach((input) => input.addEventListener("change", syncNewJobSettings));
$("#layoutSelect").addEventListener("change", selectedLayoutDescription);
$("#newJobButton").addEventListener("click", () => {
  document.querySelector(".command-deck").scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => $("#briefInput").focus(), 450);
});
$("#imageButton").addEventListener("click", () => runAction(`/api/jobs/${state.currentJob.id}/images`, "配图生成"));
$("#dryRunButton").addEventListener("click", () => runAction(`/api/jobs/${state.currentJob.id}/publish/dry-run`, "发布预检"));
$("#openPreviewButton").addEventListener("click", () => {
  if (state.currentJob) window.open(`/api/jobs/${encodeURIComponent(state.currentJob.id)}/preview`, "_blank", "noopener");
});

["#currentXhsAccount", "#currentWechatAccount", "#currentLayout"].forEach((selector) => {
  $(selector).addEventListener("change", () => {
    state.settingsDirty = true;
    $("#saveTaskSettingsButton").disabled = false;
    $("#saveTaskSettingsButton").textContent = "保存本任务设置";
  });
});

$("#saveTaskSettingsButton").addEventListener("click", async () => {
  if (!state.currentJob || state.busy) return;
  const accountIds = {};
  if ((state.currentJob.targets || []).includes("小红书") && $("#currentXhsAccount").value) {
    accountIds["小红书"] = $("#currentXhsAccount").value;
  }
  if ((state.currentJob.targets || []).includes("微信公众号") && $("#currentWechatAccount").value) {
    accountIds["微信公众号"] = $("#currentWechatAccount").value;
  }
  state.busy = true;
  try {
    const payload = await api(`/api/jobs/${state.currentJob.id}/publish-settings`, {
      method: "POST",
      body: {
        account_ids: accountIds,
        layout: $("#currentLayout").value,
      },
    });
    state.settingsDirty = false;
    renderJob(payload.job);
    toast("发布设置已保存", "账号或排版变化后，旧 Dry-run 已作废");
  } catch (error) {
    toast("发布设置未保存", error.message, true);
  } finally {
    state.busy = false;
    if (state.currentJob) renderJob(state.currentJob);
  }
});

function closeModal() {
  $("#liveModal").hidden = true;
  $("#liveConfirmation").value = "";
}

$("#liveButton").addEventListener("click", () => {
  $("#liveModal").hidden = false;
  window.setTimeout(() => $("#liveConfirmation").focus(), 50);
});
$("#modalCloseButton").addEventListener("click", closeModal);
$("#modalCancelButton").addEventListener("click", closeModal);
$("#liveModal").addEventListener("click", (event) => {
  if (event.target === $("#liveModal")) closeModal();
});
$("#modalPublishButton").addEventListener("click", async () => {
  const confirmation = $("#liveConfirmation").value.trim();
  if (confirmation !== "确认正式发布") {
    toast("确认短语不正确", "系统没有提交任何内容", true);
    return;
  }
  const id = state.currentJob?.id;
  closeModal();
  state.busy = true;
  try {
    await api(`/api/jobs/${id}/publish/live`, {
      method: "POST",
      body: { confirmation },
    });
    toast("已进入正式发布核验", "公开链接返回前，只会显示为“已提交”");
    window.setTimeout(() => loadJob(id, true), 600);
  } catch (error) {
    toast("正式发布被阻止", error.message, true);
  } finally {
    state.busy = false;
  }
});

$("#settingsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = await api("/api/settings", {
      method: "POST",
      body: {
        schedule_enabled: $("#scheduleEnabled").checked,
        schedule_time: $("#scheduleTime").value,
        weekdays: $$("#weekdayRow input:checked").map((input) => Number(input.value)),
        daily_limit_per_account: Number($("#dailyLimit").value),
        minimum_interval_minutes: Number($("#minimumInterval").value),
      },
    });
    renderSettings(payload.settings);
    toast("设置已保存", "定时任务只自动运行到 Dry-run，不会自动正式发表");
  } catch (error) {
    toast("设置保存失败", error.message, true);
  }
});

$("#refreshStatusButton").addEventListener("click", () => loadStatus(true));

$$(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item === button));
    $$(".view").forEach((view) => view.classList.remove("active"));
    $(`#${button.dataset.view}View`).classList.add("active");
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    if (button.dataset.view === "settings" && !state.connectors?.accounts?.length) {
      loadStatus(true);
    }
  });
});

window.setInterval(() => {
  if (state.currentJob?.id && !document.hidden) {
    loadJob(state.currentJob.id, true);
  }
}, 3500);

Promise.all([loadJobs(), loadStatus(true), loadSettings()]).catch((error) => {
  toast("系统初始化失败", error.message, true);
});

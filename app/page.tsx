"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type LayoutId = "editorial" | "clean" | "song";
type PlatformId = "xhs" | "wechat";
type BridgeState = "disconnected" | "connecting" | "connected" | "error";

type Topic = {
  id: string;
  title: string;
  score: number;
  reason: string;
  summary?: string;
};

type Account = {
  id: string;
  platform: "小红书" | "微信公众号";
  name: string;
  ready: boolean;
  reason: string;
};

type Job = {
  id: string;
  brief: string;
  audience: string;
  status: string;
  message: string;
  progress: number;
  progress_detail?: {
    phase?: string;
    phase_label?: string;
    stage_percent?: number;
    current_step?: string;
  };
  research?: {
    candidates?: Topic[];
    selected?: Topic;
  };
  content?: {
    title?: string;
    xhs_title?: string;
    xhs_body?: string;
    article_text?: string;
    quality?: { score?: number };
  };
  images?: {
    items?: { file: string; width?: number; height?: number; source?: string }[];
  };
  publish?: {
    status?: string;
    public_urls?: string[];
    blockers?: string[];
  };
};

type Output = {
  brief: string;
  title: string;
  xhsTitle: string;
  summary: string;
  topics: Topic[];
  sections: { heading: string; body: string }[];
  xhsBody: string;
  tags: string[];
  quality: number;
};

const DEFAULT_BRIEF = "传统企业为什么买了很多 AI 工具，效率还是没有提升？";
const DEFAULT_AUDIENCE = "企业老板、业务负责人和内容创作者";
const DEFAULT_BRIDGE = "http://127.0.0.1:8786";
const REMOTE_APP_URL =
  "https://yanruwill-dot.github.io/yanflow-content-automation/";
const PAIR_URL = `${DEFAULT_BRIDGE}/connect?return=${encodeURIComponent(REMOTE_APP_URL)}`;
const DEMO_OUTPUT_STORAGE_KEY = "yanflow-demo-output-v2";
const SAMPLE_IMAGE_URLS = Array.from(
  { length: 9 },
  (_, index) => `./sample-ai-tools-workflow/${String(index + 1).padStart(2, "0")}.png`,
);

function revokeBlobUrls(urls: string[]) {
  urls.filter((url) => url.startsWith("blob:")).forEach((url) => URL.revokeObjectURL(url));
}

const layouts: Record<
  LayoutId,
  { name: string; description: string; kicker: string }
> = {
  editorial: {
    name: "商业杂志",
    description: "深墨标题区、青柠强调，适合商业判断",
    kicker: "BUSINESS EDITORIAL",
  },
  clean: {
    name: "清爽阅读",
    description: "明亮留白、短段落，适合教程和行动清单",
    kicker: "CLEAR ACTION",
  },
  song: {
    name: "宋式留白",
    description: "米白纸感、朱砂点题，适合故事和深度文章",
    kicker: "SONG EDITION",
  },
};

const pipeline = [
  ["01", "爆款选题池", "公开来源、评分与近似主题去重"],
  ["02", "内容生成", "选中后生成双平台正文"],
  ["03", "Image2 高清图", "9 张 3:4 中文成品图与质检"],
  ["04", "发布风控", "账号、限频、重复图片检查"],
  ["05", "发布与核验", "Dry-run 后人工确认正式发布"],
] as const;

function buildOutput(rawBrief: string, rawAudience: string): Output {
  const brief = rawBrief.trim() || DEFAULT_BRIEF;
  const audience = rawAudience.trim() || DEFAULT_AUDIENCE;
  const subject = brief.replace(/[？?。！!]+$/g, "");
  return {
    brief,
    title: "买了AI工具，为什么效率没起来？",
    xhsTitle: "买再多AI工具也不提效",
    summary: `真正的问题不是工具少，而是 ${audience} 没有把工具接进一条可执行、可复核的业务工作流。`,
    topics: [
      {
        id: "demo-1",
        title: subject,
        score: 96,
        reason: "直接击中老板已经花钱、团队却没有明显变快的落差。",
      },
      {
        id: "demo-2",
        title: "别再培训提示词了，先把业务流程画出来",
        score: 92,
        reason: "从工具使用切到流程改造，观点清晰，也便于给行动方案。",
      },
      {
        id: "demo-3",
        title: "企业上 AI，最贵的不是模型，是反复返工",
        score: 89,
        reason: "把抽象的转型问题换成老板能感知的成本问题。",
      },
      {
        id: "demo-4",
        title: "一个 AI 员工真正上岗，要过哪三关？",
        score: 86,
        reason: "适合做成清单和贴图，阅读门槛低。",
      },
      {
        id: "demo-5",
        title: "从个人提效到组织提效，中间差了一套什么？",
        score: 83,
        reason: "适合公众号深度展开，强调组织协作。",
      },
    ],
    sections: [
      {
        heading: "假提效：单点变快，整条流程更忙",
        body: "员工先让AI生成，再把结果复制到文档、表格和业务系统里，最后继续人工核对、催进度、补异常。工具多了，但流程没变。",
      },
      {
        heading: "任务和交接没有标准",
        body: "同一件事，多人多种输入和做法，AI输出无法稳定复用；AI写完还要人工搬到下一个系统，快在生成，慢在流转。",
      },
      {
        heading: "例外没有出口，也没有结果责任人",
        body: "一碰到缺资料、改需求或系统报错，员工不知道何时继续、何时交给人；IT管工具、业务管结果，却没人对整条流程负责。",
      },
      {
        heading: "不要看调用次数，要看三个指标",
        body: "真正判断提效，要连续看真实任务里的单次处理时长、一次通过率和人工接管率，而不是看一次演示有多漂亮。",
      },
      {
        heading: "老板7天就能启动第一轮",
        body: "画流程、选一个重复任务、准备合格与不合格样例，让AI接其中一步，补异常规则，小批量试跑，最后复盘成SOP。",
      },
    ],
    xhsBody: `很多老板上AI，第一步是买工具、开账号、让员工学提示词。

一两周后演示很多，真正的业务结果却没有明显变化。员工不是不用AI，而是多了一道新工作：先让AI生成，再把结果复制到文档、表格和业务系统里，最后继续人工核对、催进度、补异常。

这就是很多公司的“假提效”：单点变快了，整条流程反而更忙。

问题通常卡在5个地方。

1. 任务没有标准
同一件事，不同员工有不同输入、判断和输出。AI只能把每个人原来的做法放大，结果当然不稳定。

2. 交接没有标准
AI写完以后，谁接收、放到哪里、用什么格式、什么时候完成，都没有定义。快在生成，慢在流转。

3. 例外没有出口
正常情况能自动跑，一碰到缺资料、特殊审批、客户临时修改或系统报错，流程就停。员工不知道什么时候该继续、什么时候必须交给人。

4. 没有结果责任人
IT负责工具，业务负责结果，中间却没有人对整条流程负责。出了问题，大家都只管自己那一段。

5. 没有统一指标
很多公司只看“用了多少次AI”，却不看单次处理时长、一次通过率和人工接管率。没有指标，就不知道AI到底是在提效，还是在制造返工。

更有效的顺序是：
第一，先挑一个高频、规则清楚、出错可控的场景。
第二，把现在的人工流程画出来，找出最慢、最重复的一段。
第三，定义输入、判断、输出和验收标准。
第四，让AI只接其中一段，同时设置异常升级和人工回退。
第五，连续看几轮真实任务，用处理时长、一次通过率、人工接管率判断是否有效。

老板本周可以直接这样做：
第1天，画出一条真实业务流程；
第2天，只选一个重复任务；
第3天，准备合格和不合格样例；
第4天，让AI接手其中一步；
第5天，补上异常和人工接管规则；
第6天，小批量试跑；
第7天，复盘后写成SOP。

AI不是装上就会快。先把一条流程跑顺，再扩工具；流程不重做，工具只会更热闹。`,
    tags: ["企业AI", "内容自动化", "组织提效", "AI工作流", "老板思维"],
    quality: 96,
  };
}

function outputFromJob(job: Job, audience: string): Output {
  const fallback = buildOutput(job.brief, audience);
  const topics = (job.research?.candidates || []).map((topic, index) => ({
    id: topic.id || `topic-${index + 1}`,
    title: topic.title,
    score: Number(topic.score || 0),
    reason: topic.reason || topic.summary || "已进入候选池",
    summary: topic.summary,
  }));
  const selected = job.research?.selected || topics[0];
  return {
    ...fallback,
    brief: job.brief,
    title: job.content?.title || selected?.title || fallback.title,
    xhsTitle: job.content?.xhs_title || selected?.title || fallback.xhsTitle,
    summary: selected?.summary || selected?.reason || fallback.summary,
    topics: topics.length ? topics : fallback.topics,
    xhsBody: job.content?.xhs_body || fallback.xhsBody,
    quality: Number(job.content?.quality?.score || fallback.quality),
  };
}

function normalizeSavedOutput(value: Output): Output {
  return {
    ...value,
    topics: (value.topics || []).map((topic, index) => ({
      ...topic,
      id: topic.id || `saved-${index + 1}`,
    })),
  };
}

function isRestorableJob(job: Job) {
  return (
    ["images_ready", "preflight_passed", "submitted", "published", "partial_success"].includes(
      job.status,
    ) && Boolean(job.images?.items?.length)
  );
}

function publishGatePassed(job: Job) {
  return (
    ["preflight_passed", "submitted", "published", "partial_success"].includes(job.status) ||
    ["dry_run_passed", "submitted", "success", "partial_success"].includes(
      job.publish?.status || "",
    )
  );
}

function stageFromJob(job: Job) {
  const phase = job.progress_detail?.phase || job.status;
  if (phase === "images" || job.status === "images_ready") return 2;
  if (
    phase === "publish" ||
    ["preflight_passed", "published", "submitted", "partial_success"].includes(job.status)
  ) return 4;
  if (phase === "content") return 1;
  return 0;
}

export default function Home() {
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [audience, setAudience] = useState(DEFAULT_AUDIENCE);
  const [platforms, setPlatforms] = useState<Record<PlatformId, boolean>>({
    xhs: true,
    wechat: true,
  });
  const [layout, setLayout] = useState<LayoutId>("editorial");
  const [xhsAccount, setXhsAccount] = useState("");
  const [wechatAccount, setWechatAccount] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [bridgeState, setBridgeState] = useState<BridgeState>("disconnected");
  const [bridgeToken, setBridgeToken] = useState("");
  const [bridgeBase, setBridgeBase] = useState(DEFAULT_BRIDGE);
  const [output, setOutput] = useState<Output>(
    buildOutput(DEFAULT_BRIEF, DEFAULT_AUDIENCE),
  );
  const [selectedTopicId, setSelectedTopicId] = useState("demo-1");
  const [job, setJob] = useState<Job | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressLabel, setProgressLabel] = useState(
    "示例预览已加载；连接本机后生成真实内容",
  );
  const [activeStage, setActiveStage] = useState(0);
  const [running, setRunning] = useState(false);
  const [riskChecked, setRiskChecked] = useState(false);
  const [imageUrls, setImageUrls] = useState<string[]>(SAMPLE_IMAGE_URLS);
  const [toast, setToast] = useState(
    "点击“连接本机”后，可用真实账号、Image2 和发布通道",
  );

  const xhsAccounts = accounts.filter((item) => item.platform === "小红书");
  const wechatAccounts = accounts.filter(
    (item) => item.platform === "微信公众号",
  );
  const selectedTopic =
    output.topics.find((item) => item.id === selectedTopicId) || output.topics[0];
  const publishedUrl = job?.publish?.public_urls?.[0] || "";
  const terminalPublish = Boolean(
    job &&
      (["published", "submitted", "partial_success"].includes(job.status) ||
        ["success", "submitted", "partial_success"].includes(job.publish?.status || "")),
  );

  async function bridgeFetch(
    path: string,
    init: RequestInit = {},
    token = bridgeToken,
    base = bridgeBase,
  ) {
    const headers = new Headers(init.headers || {});
    headers.set("Accept", "application/json");
    headers.set("X-Yanflow-Token", token);
    if (init.body) headers.set("Content-Type", "application/json");
    const response = await fetch(`${base}${path}`, {
      ...init,
      headers,
      mode: "cors",
      credentials: "omit",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `本机接口返回 ${response.status}`);
    }
    return payload;
  }

  async function refreshAccounts(
    token = bridgeToken,
    base = bridgeBase,
  ) {
    setBridgeState("connecting");
    try {
      const payload = await bridgeFetch(
        "/api/status?accounts=1",
        {},
        token,
        base,
      );
      const nextAccounts = (payload.accounts || []) as Account[];
      setAccounts(nextAccounts);
      setXhsAccount((current) =>
        nextAccounts.some((item) => item.id === current)
          ? current
          : nextAccounts.find(
              (item) => item.platform === "小红书" && item.ready,
            )?.id || "",
      );
      setWechatAccount((current) =>
        nextAccounts.some((item) => item.id === current)
          ? current
          : nextAccounts.find(
              (item) => item.platform === "微信公众号" && item.ready,
            )?.id || "",
      );
      setBridgeState("connected");
      let restoredJob: Job | null = null;
      try {
        const jobsPayload = await bridgeFetch("/api/jobs", {}, token, base);
        const latestReady = ((jobsPayload.jobs || []) as Job[]).find(isRestorableJob);
        if (latestReady) {
          updateFromJob(latestReady);
          const nextOutput = outputFromJob(latestReady, audience);
          setOutput(nextOutput);
          setSelectedTopicId(
            latestReady.research?.selected?.id || nextOutput.topics[0]?.id || "",
          );
          const blobs = await fetchJobImageUrls(latestReady, token, base);
          setImageUrls((current) => {
            revokeBlobUrls(current);
            return blobs;
          });
          restoredJob = latestReady;
        }
      } catch {
        // 账号连接成功即可继续；历史成品恢复失败时保留内置示例。
      }
      setToast(
        restoredJob
          ? `本机已连接，已恢复${restoredJob.status === "published" ? "已发布" : "最新"}任务、九图和 ${nextAccounts.length} 个真实账号槽`
          : `本机已连接，读到 ${nextAccounts.length} 个真实账号槽`,
      );
    } catch (error) {
      setBridgeState("error");
      setToast(`本机连接失败：${(error as Error).message}`);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const pairedToken = params.get("yanflow_token") || "";
    const pairedBase = params.get("yanflow_bridge") || "";
    if (pairedToken && pairedBase) {
      window.sessionStorage.setItem("yanflow-bridge-token", pairedToken);
      window.sessionStorage.setItem("yanflow-bridge-base", pairedBase);
      window.history.replaceState(null, "", window.location.pathname);
    }
    const token =
      pairedToken || window.sessionStorage.getItem("yanflow-bridge-token") || "";
    const base =
      pairedBase ||
      window.sessionStorage.getItem("yanflow-bridge-base") ||
      DEFAULT_BRIDGE;
    setBridgeToken(token);
    setBridgeBase(base);
    if (token) void refreshAccounts(token, base);

    const saved = window.localStorage.getItem(DEMO_OUTPUT_STORAGE_KEY);
    if (saved) {
      try {
        const restored = normalizeSavedOutput(JSON.parse(saved) as Output);
        setOutput(restored);
        setSelectedTopicId(restored.topics[0]?.id || "");
        window.localStorage.setItem(DEMO_OUTPUT_STORAGE_KEY, JSON.stringify(restored));
      } catch {
        window.localStorage.removeItem(DEMO_OUTPUT_STORAGE_KEY);
      }
    }
  }, []);

  useEffect(
    () => () => {
      revokeBlobUrls(imageUrls);
    },
    [imageUrls],
  );

  const platformLabel = useMemo(() => {
    const selected = [
      platforms.xhs ? "小红书" : "",
      platforms.wechat ? "微信公众号" : "",
    ].filter(Boolean);
    return selected.join(" + ") || "尚未选择";
  }, [platforms]);

  function pairBridge() {
    setBridgeState("connecting");
    window.location.href = PAIR_URL;
  }

  function accountIds() {
    return {
      ...(platforms.xhs && xhsAccount ? { 小红书: xhsAccount } : {}),
      ...(platforms.wechat && wechatAccount
        ? { 微信公众号: wechatAccount }
        : {}),
    };
  }

  function updateFromJob(next: Job) {
    setJob(next);
    setRiskChecked(publishGatePassed(next));
    setProgress(Number(next.progress || 0));
    setProgressLabel(
      next.progress_detail?.current_step || next.message || "正在处理",
    );
    setActiveStage(stageFromJob(next));
  }

  async function fetchJobImageUrls(
    next: Job,
    token = bridgeToken,
    base = bridgeBase,
  ) {
    return Promise.all(
      (next.images?.items || []).map(async (item) => {
        const filename = item.file.split("/").pop();
        if (!filename) throw new Error("图片文件名无效");
        const response = await fetch(
          `${base}/api/jobs/${next.id}/assets/${filename}`,
          {
            headers: { "X-Yanflow-Token": token },
            mode: "cors",
            credentials: "omit",
          },
        );
        if (!response.ok) throw new Error(`读取图片失败：${filename}`);
        return URL.createObjectURL(await response.blob());
      }),
    );
  }

  async function waitForJob(
    id: string,
    accepted: string[],
    maxAttempts = 360,
  ): Promise<Job> {
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      const payload = await bridgeFetch(`/api/jobs/${id}`);
      const next = payload.job as Job;
      updateFromJob(next);
      if (accepted.includes(next.status)) return next;
      if (["failed", "blocked", "partial_success"].includes(next.status)) {
        throw new Error(next.message || "任务已停止");
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
    throw new Error("任务仍在本机运行，请稍后刷新查看");
  }

  async function createRealJob(topicBrief: string) {
    const payload = await bridgeFetch("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        brief: topicBrief,
        audience,
        targets: [
          ...(platforms.xhs ? ["小红书"] : []),
          ...(platforms.wechat ? ["微信公众号"] : []),
        ],
        account_ids: accountIds(),
        layout,
        mode: "manual",
      }),
    });
    return payload.job as Job;
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running) return;
    if (bridgeState !== "connected") {
      pairBridge();
      return;
    }
    if (!brief.trim()) {
      setToast("先输入一个要解决的问题");
      return;
    }
    if (!platforms.xhs && !platforms.wechat) {
      setToast("至少选择一个目标平台");
      return;
    }
    setRunning(true);
    setRiskChecked(false);
    setImageUrls((current) => {
      revokeBlobUrls(current);
      return [];
    });
    try {
      const created = await createRealJob(brief);
      updateFromJob(created);
      await bridgeFetch(`/api/jobs/${created.id}/research`, {
        method: "POST",
        body: JSON.stringify({ use_latest: false }),
      });
      const finished = await waitForJob(created.id, ["content_ready"]);
      const nextOutput = outputFromJob(finished, audience);
      setOutput(nextOutput);
      setSelectedTopicId(
        finished.research?.selected?.id || nextOutput.topics[0]?.id || "",
      );
      window.localStorage.setItem(DEMO_OUTPUT_STORAGE_KEY, JSON.stringify(nextOutput));
      setToast("真实爆款候选已生成：先点选一条，再用 Image2 出 9 张高清图");
      document.getElementById("results")?.scrollIntoView({ behavior: "smooth" });
    } catch (error) {
      setToast(`选题生成停止：${(error as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  async function generateImages() {
    if (bridgeState !== "connected") {
      pairBridge();
      return;
    }
    if (!selectedTopic) {
      setToast("先选择一条爆款候选");
      return;
    }
    setRunning(true);
    setRiskChecked(false);
    try {
      let targetJob = job;
      const currentSelected = job?.research?.selected?.title;
      if (!targetJob || currentSelected !== selectedTopic.title) {
        setProgressLabel("正在按你选中的爆款题目重写内容");
        const created = await createRealJob(selectedTopic.title);
        updateFromJob(created);
        await bridgeFetch(`/api/jobs/${created.id}/research`, {
          method: "POST",
          body: JSON.stringify({ use_latest: false }),
        });
        targetJob = await waitForJob(created.id, ["content_ready"]);
        const nextOutput = outputFromJob(targetJob, audience);
        setOutput(nextOutput);
        setSelectedTopicId(
          targetJob.research?.selected?.id || nextOutput.topics[0]?.id || "",
        );
      }
      await bridgeFetch(`/api/jobs/${targetJob.id}/images`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const finished = await waitForJob(targetJob.id, ["images_ready"], 420);
      const blobs = await fetchJobImageUrls(finished);
      setImageUrls((current) => {
        revokeBlobUrls(current);
        return blobs;
      });
      setOutput(outputFromJob(finished, audience));
      setToast(`${blobs.length} 张 Image2 高清图已完成，可继续发布预检`);
      document.querySelector(".visualBoard")?.scrollIntoView({ behavior: "smooth" });
    } catch (error) {
      setToast(`Image2 生成停止：${(error as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  async function openAccountLogin(platform: Account["platform"]) {
    if (bridgeState !== "connected") {
      pairBridge();
      return;
    }
    try {
      const payload = await bridgeFetch("/api/accounts/login", {
        method: "POST",
        body: JSON.stringify({ platform }),
      });
      setToast(payload.checkpoint);
    } catch (error) {
      setToast(`账号登录入口失败：${(error as Error).message}`);
    }
  }

  async function copyText(value: string, label: string) {
    await navigator.clipboard.writeText(value);
    setToast(`${label}已复制`);
  }

  function accountName(platform: Account["platform"], id: string) {
    return (
      accounts.find((item) => item.platform === platform && item.id === id)
        ?.name || "未选择"
    );
  }

  function downloadPack() {
    const body = [
      output.title,
      "",
      output.summary,
      "",
      ...output.sections.flatMap((section) => [
        section.heading,
        section.body,
        "",
      ]),
      "—— 小红书版本 ——",
      output.xhsTitle,
      output.xhsBody,
      output.tags.map((tag) => `#${tag}`).join(" "),
      "",
      `发布账号：${accountName("小红书", xhsAccount)} / ${accountName("微信公众号", wechatAccount)}`,
      `排版：${layouts[layout].name}`,
      `状态：${job?.publish?.status || "尚未发布"}`,
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([body], { type: "text/plain;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "YanFlow-内容包.txt";
    anchor.click();
    URL.revokeObjectURL(url);
    setToast("内容包已下载");
  }

  async function runPreflight() {
    if (bridgeState !== "connected" || !job) {
      pairBridge();
      return;
    }
    if (!job.images?.items?.length) {
      setToast("先用 Image2 生成并质检图片");
      return;
    }
    setRunning(true);
    try {
      await bridgeFetch(`/api/jobs/${job.id}/publish/dry-run`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      const finished = await waitForJob(job.id, ["preflight_passed"], 520);
      setRiskChecked(true);
      setToast(finished.message);
    } catch (error) {
      setToast(`发布预检停止：${(error as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  async function requestLivePublish() {
    if (!job || job.publish?.status !== "dry_run_passed") {
      setToast("正式发布前必须先通过完整 Dry-run");
      return;
    }
    const confirmation = window.prompt(
      "正式发布会提交到已选账号。请输入：确认正式发布",
      "",
    );
    if (confirmation !== "确认正式发布") {
      setToast("未输入确认短语，没有提交");
      return;
    }
    setRunning(true);
    try {
      await bridgeFetch(`/api/jobs/${job.id}/publish/live`, {
        method: "POST",
        body: JSON.stringify({ confirmation }),
      });
      const finished = await waitForJob(
        job.id,
        ["published", "submitted"],
        560,
      );
      const url = finished.publish?.public_urls?.[0];
      setToast(url ? `已发布并拿到公开链接：${url}` : finished.message);
    } catch (error) {
      setToast(`正式发布停止：${(error as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  const bridgeCopy = {
    disconnected: "连接本机",
    connecting: "连接中…",
    connected: "本机已连接",
    error: "重新连接",
  }[bridgeState];

  return (
    <main className="shell">
      <aside className="rail" aria-label="工作台导航">
        <a className="brand" href="#top" aria-label="回到顶部">
          <span className="brandMark" aria-hidden="true"><i /><i /><i /></span>
          <strong>焰流</strong>
          <small>YANFLOW</small>
        </a>
        <nav>
          <a href="#factory"><b>01</b><span>内容工厂</span></a>
          <a href="#results"><b>02</b><span>爆款选题</span></a>
          <a href="#risk"><b>03</b><span>发布风控</span></a>
        </nav>
        <div className="railStatus"><i /><span>{bridgeState === "connected" ? "真机" : "云端"}</span></div>
      </aside>

      <div className="workspace" id="top">
        <header className="topbar">
          <div>
            <p className="eyebrow">CONTENT OPERATIONS / IMAGE2 / REAL ACCOUNTS</p>
            <h1>先选爆款，<em>再出高清图。</em></h1>
            <p className="lead">
              GitHub 负责中台界面；真实账号、Image2 和发布凭证只留在你的本机。
            </p>
          </div>
          <button className={`livePill bridgePill ${bridgeState}`} onClick={pairBridge}>
            <i />{bridgeCopy}
          </button>
        </header>

        <section className="metrics" aria-label="任务概览">
          <article className="metric primary">
            <span>当前任务</span>
            <strong>{running ? "运行中" : job ? "已连接" : "待开始"}</strong>
            <small>{platformLabel}</small>
          </article>
          <article className="metric">
            <span>内容质量</span>
            <strong>{output.quality}</strong>
            <small>真实来源、结构、表达、平台适配</small>
          </article>
          <article className="metric">
            <span>真实进度</span>
            <strong>{progress}%</strong>
            <small>{progressLabel}</small>
          </article>
          <article className="metric safe">
            <span>账号槽</span>
            <strong>{bridgeState === "connected" ? accounts.length : "—"}</strong>
            <small>{bridgeState === "connected" ? "可换号，可打开登录" : "连接后读取真实状态"}</small>
          </article>
        </section>

        <section className="commandDeck" id="factory">
          <header className="sectionHeading">
            <div className="sectionIndex">A</div>
            <div>
              <p className="eyebrow">TOPIC FIRST, IMAGE2 NEXT</p>
              <h2>今天想做什么内容？</h2>
            </div>
            <span className="safeTag">先出候选，不会直接发表</span>
          </header>

          <form onSubmit={generate}>
            <label className="field fieldWide">
              <span>内容方向</span>
              <textarea
                value={brief}
                onChange={(event) => setBrief(event.target.value)}
                rows={4}
                maxLength={500}
                placeholder="输入一个真实业务问题"
              />
              <small>系统会先给 5 条有评分的候选，你点中哪条，再按哪条写稿和出图。</small>
            </label>

            <label className="field">
              <span>核心读者</span>
              <input
                value={audience}
                onChange={(event) => setAudience(event.target.value)}
                maxLength={160}
              />
            </label>

            <fieldset className="field platformField">
              <legend>目标平台</legend>
              <label>
                <input type="checkbox" checked={platforms.xhs} onChange={(event) => setPlatforms({ ...platforms, xhs: event.target.checked })} />
                <span className="platformIcon xhs">红</span><b>小红书</b><small>Image2 3:4 九图</small>
              </label>
              <label>
                <input type="checkbox" checked={platforms.wechat} onChange={(event) => setPlatforms({ ...platforms, wechat: event.target.checked })} />
                <span className="platformIcon wechat">微</span><b>微信公众号</b><small>文章 + 正文贴图</small>
              </label>
            </fieldset>

            <div className="settingsRow accountSettings">
              <div className="field accountField">
                <span>小红书账号槽</span>
                <select value={xhsAccount} onChange={(event) => setXhsAccount(event.target.value)} disabled={!xhsAccounts.length}>
                  {!xhsAccounts.length && <option value="">连接后读取真实账号</option>}
                  {xhsAccounts.map((account) => <option key={account.id} value={account.id}>{account.name} · {account.ready ? "已登录" : account.reason}</option>)}
                </select>
                <div className="accountActions">
                  <small>{xhsAccounts.length ? `${xhsAccounts.length} 个可切换槽位` : "不在 GitHub 保存密码"}</small>
                  <button type="button" onClick={() => openAccountLogin("小红书")}>＋ 登录新账号</button>
                </div>
              </div>
              <div className="field accountField">
                <span>公众号账号槽</span>
                <select value={wechatAccount} onChange={(event) => setWechatAccount(event.target.value)} disabled={!wechatAccounts.length}>
                  {!wechatAccounts.length && <option value="">连接后读取真实账号</option>}
                  {wechatAccounts.map((account) => <option key={account.id} value={account.id}>{account.name} · {account.ready ? "已登录" : account.reason}</option>)}
                </select>
                <div className="accountActions">
                  <small>{wechatAccounts.length ? `${wechatAccounts.length} 个可切换槽位` : "不在 GitHub 保存密码"}</small>
                  <button type="button" onClick={() => openAccountLogin("微信公众号")}>＋ 登录新账号</button>
                </div>
              </div>
              <label className="field">
                <span>文章与贴图排版</span>
                <select value={layout} onChange={(event) => setLayout(event.target.value as LayoutId)}>
                  {Object.entries(layouts).map(([id, item]) => <option key={id} value={id}>{item.name}</option>)}
                </select>
                <small>{layouts[layout].description}</small>
              </label>
            </div>

            <div className="runPanel">
              <div>
                <span>01—05</span>
                <p>先出爆款候选 → 你选择 → Image2 九图 → Dry-run → 人工确认发布</p>
              </div>
              <button type="submit" disabled={running || bridgeState === "connecting"}>
                {bridgeState !== "connected" ? "连接本机开始" : running ? "正在生成…" : "生成 5 个爆款候选"}
                <i aria-hidden="true">↗</i>
              </button>
            </div>
          </form>
        </section>

        <section className="pipelineSection">
          <header className="sectionHeading compact">
            <div className="sectionIndex">B</div>
            <div><p className="eyebrow">LIVE PIPELINE</p><h2>真实进度</h2></div>
          </header>
          <div className="pipeline">
            {pipeline.map(([number, name, note], index) => (
              <article key={name} className={index < activeStage ? "done" : index === activeStage ? "active" : ""}>
                <span>{number}</span><div><b>{name}</b><small>{note}</small></div><i />
              </article>
            ))}
          </div>
          <div className="progressConsole" aria-live="polite">
            <div className="progressCopy">
              <div><span><i /> LIVE PROGRESS</span><h3>{progressLabel}</h3></div>
              <strong>{progress}%</strong>
            </div>
            <div className="progressTrack"><i style={{ width: `${progress}%` }} /></div>
            <div className="progressMeta">
              <span>{Math.max(1, activeStage + 1)} / 5 阶段</span>
              <span>当前排版：{layouts[layout].name}</span>
              <span>{bridgeState === "connected" ? "进度来自本机任务" : "未连接本机"}</span>
            </div>
          </div>
        </section>

        <section className="results" id="results">
          <article className="panel topicsPanel">
            <header>
              <div><p className="eyebrow">VIRAL TOPIC POOL</p><h2>爆款候选</h2></div>
              <span>{output.topics.length} 条 · 点击选择</span>
            </header>
            <div className="topicList">
              {output.topics.map((topic, index) => (
                <button type="button" className={topic.id === selectedTopicId ? "selected" : ""} key={topic.id} onClick={() => setSelectedTopicId(topic.id)}>
                  <strong>{topic.score}</strong>
                  <section>
                    <span>{topic.id === selectedTopicId ? "已选中" : `候选 ${index + 1}`}</span>
                    <h3>{topic.title}</h3>
                    <p>{topic.reason}</p>
                  </section>
                </button>
              ))}
            </div>
            <div className="topicAction">
              <small>当前选中：{selectedTopic?.title}</small>
              <button type="button" onClick={generateImages} disabled={running}>
                {running ? "正在处理…" : "用这条生成 Image2 九图"}
              </button>
            </div>
          </article>

          <article className="panel contentPanel">
            <header>
              <div><p className="eyebrow">MASTER CONTENT</p><h2>一稿双发</h2></div>
              <button onClick={() => copyText(output.xhsBody, "小红书正文")}>复制正文</button>
            </header>
            <div className="articlePreview">
              <span>公众号标题</span>
              <h3>{output.title}</h3>
              <p className="summary">{output.summary}</p>
              {output.sections.map((section) => (
                <section key={section.heading}><h4>{section.heading}</h4><p>{section.body}</p></section>
              ))}
            </div>
            <div className="xhsCopyPreview">
              <span>小红书正文预览</span>
              <h4>{output.xhsTitle}</h4>
              <p>{output.xhsBody}</p>
              <div>{output.tags.map((tag) => `#${tag}`).join(" ")}</div>
            </div>
            <div className="qualityBar">
              <span>内容质量 <b>{output.quality}</b></span>
              <span>候选数量 <b>{output.topics.length}</b></span>
              <span>图片数量 <b>{imageUrls.length || 0}</b></span>
            </div>
          </article>
        </section>

        <section className={`visualBoard ${layout}`} aria-label="Image2 贴图预览">
          <header className="sectionHeading compact visualHeading">
            <div className="sectionIndex">C</div>
            <div>
              <p className="eyebrow">IMAGE2 / 3:4 高清成品 / {layouts[layout].kicker}</p>
              <h2>小红书高清图组</h2>
            </div>
            <button className="imageGenerateButton" onClick={generateImages} disabled={running}>
              {imageUrls.length ? "按当前选题重新生成" : "生成 9 张 Image2 高清图"}
            </button>
          </header>
          {imageUrls.length ? (
            <div className="imageCards">
              {imageUrls.map((url, index) => (
                <figure key={url}>
                  <img src={url} alt={`Image2 小红书成品图 ${index + 1}`} />
                  <figcaption>{String(index + 1).padStart(2, "0")} · IMAGE2</figcaption>
                </figure>
              ))}
            </div>
          ) : (
            <div className="cards">
              <article className="coverCard"><span>结构预览 / 01</span><h3>{selectedTopic?.title || output.xhsTitle}</h3><p>选中题目后由 Image2 生成真实成品</p><b>3:4 高清图</b></article>
              <article className="pointCard"><span>真正的卡点</span><strong>内容先选准<br />图片才有力</strong><p>候选 → 选择 → 写稿 → Image2 → 质检</p></article>
              <article className="actionCard"><span>图片标准</span><ol><li>中文清楚</li><li>手机可读</li><li>每张一重点</li></ol><b>这里是结构预览，不是假装成品</b></article>
            </div>
          )}
        </section>

        <section className="riskBoard" id="risk">
          <header className="sectionHeading compact">
            <div className="sectionIndex">D</div>
            <div><p className="eyebrow">PUBLISHING GATE</p><h2>发布风控与账号授权</h2></div>
          </header>
          <div className="riskGrid">
            <article><span className="statusDot" /><div><b>Image2 质检</b><small>中文、裁切、3:4、重复图片</small></div><strong>{imageUrls.length ? "已生成" : "待生成"}</strong></article>
            <article><span className="statusDot" /><div><b>真实账号槽</b><small>可换号，登录动作只在本机完成</small></div><strong>{bridgeState === "connected" ? `${accounts.length} 个已读取` : "待连接"}</strong></article>
            <article className={riskChecked ? "" : "guarded"}><span className="statusDot" /><div><b>完整发布预检</b><small>账号、Schema、限频、重复提交</small></div><strong>{riskChecked ? "已通过" : "待执行"}</strong></article>
          </div>
          <div className="actions">
            <button className="secondary" onClick={() => refreshAccounts()} disabled={bridgeState !== "connected"}>刷新账号状态</button>
            <button className="secondary" onClick={downloadPack}>下载内容包</button>
            <button className="secondary" onClick={runPreflight} disabled={running || terminalPublish}>
              {terminalPublish ? "发布预检已完成" : "运行完整 Dry-run"}
            </button>
            <button className="primaryAction" onClick={requestLivePublish} disabled={running || terminalPublish}>
              {terminalPublish ? (publishedUrl ? "已发布" : "已提交") : "确认后正式发布"}
            </button>
          </div>
          {terminalPublish && (
            <div className="publishReceipt" role="status">
              <div>
                <strong>{publishedUrl ? "平台已发表并返回公开链接" : "平台已接收，等待公开链接"}</strong>
                <small>{job?.message || "真实发布状态已从本机任务恢复"}</small>
              </div>
              {publishedUrl && (
                <a href={publishedUrl} target="_blank" rel="noreferrer">查看小红书公开内容 ↗</a>
              )}
            </div>
          )}
          <p className="boundary">
            GitHub 页面不保存账号密码、Cookie 或 API 密钥。点击登录槽会打开本机蚁小二4.0；扫码、验证码、实名确认必须由你完成。平台审核和风控无法保证“永不封禁”，系统只做合规表达、去重、限频和人工确认。
          </p>
        </section>

        <footer>
          <span>YANFLOW · GITHUB UI + LOCAL SECURE BRIDGE</span>
          <p>爆款候选可选，Image2 真出图，账号槽可登录/切换。</p>
        </footer>
      </div>

      <div className="toast" role="status" aria-live="polite">{toast}</div>
    </main>
  );
}

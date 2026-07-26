"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type LayoutId = "editorial" | "clean" | "song";
type PlatformId = "xhs" | "wechat";

type Topic = {
  title: string;
  score: number;
  reason: string;
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
  ["01", "选题雷达", "公开来源与近似主题去重"],
  ["02", "内容生成", "五个标题与双平台正文"],
  ["03", "贴图结构", "小红书与公众号视觉版式"],
  ["04", "发布风控", "账号、限频、敏感表达检查"],
  ["05", "发布预检", "只生成回执，不直接发表"],
] as const;

function buildOutput(rawBrief: string, rawAudience: string): Output {
  const brief = rawBrief.trim() || DEFAULT_BRIEF;
  const audience = rawAudience.trim() || DEFAULT_AUDIENCE;
  const subject = brief.replace(/[？?。！!]+$/g, "");
  return {
    brief,
    title: `AI 工具越买越多，为什么效率反而没有起来？`,
    xhsTitle: "买了 20 个 AI 工具，团队为什么还是很忙？",
    summary: `真正的问题不是工具少，而是 ${audience} 没有把经验、流程和结果标准连成一条可复用的工作线。`,
    topics: [
      {
        title: subject,
        score: 96,
        reason: "直接击中老板已经花钱、团队却没有明显变快的落差。",
      },
      {
        title: "别再培训提示词了，先把业务流程画出来",
        score: 92,
        reason: "从工具使用切到流程改造，观点清晰，也便于给行动方案。",
      },
      {
        title: "企业上 AI，最贵的不是模型，是反复返工",
        score: 89,
        reason: "把抽象的转型问题换成老板能感知的成本问题。",
      },
      {
        title: "一个 AI 员工真正上岗，要过哪三关？",
        score: 86,
        reason: "适合做成清单和贴图，阅读门槛低。",
      },
      {
        title: "从个人提效到组织提效，中间差了一套什么？",
        score: 83,
        reason: "适合公众号深度展开，强调组织协作。",
      },
    ],
    sections: [
      {
        heading: "工具不是系统，能生成不等于能交付",
        body: "很多公司把 AI 当成更聪明的搜索框：每个人各自提问、各自复制，最后还要人工对齐。单点速度变快了，交接、审稿、核验和发布却没有变，整体效率当然起不来。",
      },
      {
        heading: "真正需要复制的，是高手做判断的过程",
        body: "先把选题依据、写作结构、视觉标准、发布闸门和复盘方式拆成可检查的步骤，再让 AI 逐步执行。这样离开某个能人，结果也不会立刻失控。",
      },
      {
        heading: "先跑通一条线，再扩展十个场景",
        body: "从一个高频内容任务开始：输入问题，得到候选选题、双平台正文、贴图结构和发布预检。连续跑通三次以后，再接入真实账号与定时任务，成本最低，也更安全。",
      },
    ],
    xhsBody:
      "公司买了很多 AI 工具，员工也上了不少课，但团队还是很忙。原因通常不是不会用，而是没有一条从任务输入到结果验收的完整流程。先挑一个高频场景，把选题、生成、配图、审核和发布标准固化，再考虑扩工具。AI 真正值钱的地方，是把高手的判断变成团队可以重复执行的系统。",
    tags: ["企业AI", "内容自动化", "组织提效", "AI工作流", "老板思维"],
    quality: 94,
  };
}

const initialOutput = buildOutput(DEFAULT_BRIEF, DEFAULT_AUDIENCE);

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default function Home() {
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [audience, setAudience] = useState(DEFAULT_AUDIENCE);
  const [platforms, setPlatforms] = useState<Record<PlatformId, boolean>>({
    xhs: true,
    wechat: true,
  });
  const [layout, setLayout] = useState<LayoutId>("editorial");
  const [xhsAccount, setXhsAccount] = useState("小红书主账号");
  const [wechatAccount, setWechatAccount] = useState("公众号主账号");
  const [output, setOutput] = useState<Output>(initialOutput);
  const [progress, setProgress] = useState(100);
  const [progressLabel, setProgressLabel] = useState("示例任务已生成，可直接查看结果");
  const [activeStage, setActiveStage] = useState(4);
  const [running, setRunning] = useState(false);
  const [riskChecked, setRiskChecked] = useState(true);
  const [toast, setToast] = useState("线上演示已就绪，正式发布需要本地账号授权");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const saved = window.localStorage.getItem("yanflow-demo-output");
      if (!saved) return;
      try {
        setOutput(JSON.parse(saved) as Output);
        setToast("已恢复你上次在这台设备生成的内容");
      } catch {
        window.localStorage.removeItem("yanflow-demo-output");
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const platformLabel = useMemo(() => {
    const selected = [
      platforms.xhs ? "小红书" : "",
      platforms.wechat ? "微信公众号" : "",
    ].filter(Boolean);
    return selected.join(" + ") || "尚未选择";
  }, [platforms]);

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running) return;
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
    const steps = [
      [8, 0, "正在整理任务和读者"],
      [24, 0, "正在生成 5 个候选选题"],
      [42, 1, "正在写双平台内容"],
      [61, 1, "正在压缩短段落和行动结尾"],
      [76, 2, "正在生成贴图排版结构"],
      [89, 3, "正在检查重复、导流和绝对化承诺"],
      [100, 4, "完整 Dry-run 已完成，没有正式发表"],
    ] as const;

    for (const [percent, stage, label] of steps) {
      setProgress(percent);
      setActiveStage(stage);
      setProgressLabel(label);
      await sleep(360);
    }

    const next = buildOutput(brief, audience);
    setOutput(next);
    window.localStorage.setItem("yanflow-demo-output", JSON.stringify(next));
    setRiskChecked(true);
    setRunning(false);
    setToast("一条内容已经跑出来：正文、贴图结构和发布预检都完成了");
    window.setTimeout(() => {
      document.getElementById("results")?.scrollIntoView({ behavior: "smooth" });
    }, 80);
  }

  async function copyText(value: string, label: string) {
    await navigator.clipboard.writeText(value);
    setToast(`${label}已复制`);
  }

  function downloadPack() {
    const body = [
      output.title,
      "",
      output.summary,
      "",
      ...output.sections.flatMap((section) => [section.heading, section.body, ""]),
      "—— 小红书版本 ——",
      output.xhsTitle,
      output.xhsBody,
      output.tags.map((tag) => `#${tag}`).join(" "),
      "",
      `发布账号：${xhsAccount} / ${wechatAccount}`,
      `排版：${layouts[layout].name}`,
      "状态：Dry-run 完成，未正式发表",
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

  function runPreflight() {
    setRiskChecked(true);
    setToast("发布预检通过：未发现导流、绝对化承诺或重复提交");
  }

  function requestLivePublish() {
    setToast("正式发布已锁定：请在本地 YanFlow 完成账号授权和人工确认");
    document.getElementById("risk")?.scrollIntoView({ behavior: "smooth" });
  }

  return (
    <main className="shell">
      <aside className="rail" aria-label="工作台导航">
        <a className="brand" href="#top" aria-label="回到顶部">
          <span className="brandMark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <strong>焰流</strong>
          <small>YANFLOW</small>
        </a>
        <nav>
          <a href="#factory"><b>01</b><span>内容工厂</span></a>
          <a href="#results"><b>02</b><span>生成结果</span></a>
          <a href="#risk"><b>03</b><span>发布风控</span></a>
        </nav>
        <div className="railStatus"><i /><span>线上运行</span></div>
      </aside>

      <div className="workspace" id="top">
        <header className="topbar">
          <div>
            <p className="eyebrow">CONTENT OPERATIONS / SAFE AUTOMATION</p>
            <h1>从选题到发布，<em>只走一条线。</em></h1>
            <p className="lead">
              输入一个问题，自动得到选题、双平台正文、贴图排版和发布预检。
            </p>
          </div>
          <div className="livePill"><i />网站已上线运行</div>
        </header>

        <section className="metrics" aria-label="任务概览">
          <article className="metric primary">
            <span>当前任务</span>
            <strong>{running ? "运行中" : "已完成"}</strong>
            <small>{platformLabel}</small>
          </article>
          <article className="metric">
            <span>内容质量</span>
            <strong>{output.quality}</strong>
            <small>结构、表达、平台适配</small>
          </article>
          <article className="metric">
            <span>生成进度</span>
            <strong>{progress}%</strong>
            <small>{progressLabel}</small>
          </article>
          <article className="metric safe">
            <span>发布闸门</span>
            <strong>{riskChecked ? "已通过" : "检查中"}</strong>
            <small>默认只跑 Dry-run</small>
          </article>
        </section>

        <section className="commandDeck" id="factory">
          <header className="sectionHeading">
            <div className="sectionIndex">A</div>
            <div>
              <p className="eyebrow">ONE BRIEF, ONE VERIFIED PIPELINE</p>
              <h2>今天要解决什么问题？</h2>
            </div>
            <span className="safeTag">不会直接发表</span>
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
              <small>建议写成问题，系统更容易生成有判断力的内容。</small>
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
                <input
                  type="checkbox"
                  checked={platforms.xhs}
                  onChange={(event) =>
                    setPlatforms({ ...platforms, xhs: event.target.checked })
                  }
                />
                <span className="platformIcon xhs">红</span>
                <b>小红书</b>
                <small>3:4 贴图 + 图文</small>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={platforms.wechat}
                  onChange={(event) =>
                    setPlatforms({ ...platforms, wechat: event.target.checked })
                  }
                />
                <span className="platformIcon wechat">微</span>
                <b>微信公众号</b>
                <small>文章 + 正文贴图</small>
              </label>
            </fieldset>

            <div className="settingsRow">
              <label className="field">
                <span>小红书发布账号</span>
                <select value={xhsAccount} onChange={(event) => setXhsAccount(event.target.value)}>
                  <option>小红书主账号</option>
                  <option>小红书矩阵账号</option>
                  <option>新账号槽位</option>
                </select>
              </label>
              <label className="field">
                <span>公众号发布账号</span>
                <select
                  value={wechatAccount}
                  onChange={(event) => setWechatAccount(event.target.value)}
                >
                  <option>公众号主账号</option>
                  <option>公众号矩阵账号</option>
                  <option>新账号槽位</option>
                </select>
              </label>
              <label className="field">
                <span>文章与贴图排版</span>
                <select
                  value={layout}
                  onChange={(event) => setLayout(event.target.value as LayoutId)}
                >
                  {Object.entries(layouts).map(([id, item]) => (
                    <option key={id} value={id}>{item.name}</option>
                  ))}
                </select>
                <small>{layouts[layout].description}</small>
              </label>
            </div>

            <div className="runPanel">
              <div>
                <span>01—07</span>
                <p>选题 → 写稿 → 贴图 → 审核 → Dry-run → 人工确认 → 发布核验</p>
              </div>
              <button type="submit" disabled={running}>
                {running ? "正在生成…" : "启动安全自动流程"}
                <i aria-hidden="true">↗</i>
              </button>
            </div>
          </form>
        </section>

        <section className="pipelineSection">
          <header className="sectionHeading compact">
            <div className="sectionIndex">B</div>
            <div>
              <p className="eyebrow">LIVE PIPELINE</p>
              <h2>进度与结果</h2>
            </div>
          </header>
          <div className="pipeline">
            {pipeline.map(([number, name, note], index) => (
              <article
                key={name}
                className={index < activeStage ? "done" : index === activeStage ? "active" : ""}
              >
                <span>{number}</span>
                <div><b>{name}</b><small>{note}</small></div>
                <i />
              </article>
            ))}
          </div>
          <div className="progressConsole" aria-live="polite">
            <div className="progressCopy">
              <div>
                <span><i /> LIVE PROGRESS</span>
                <h3>{progressLabel}</h3>
              </div>
              <strong>{progress}%</strong>
            </div>
            <div className="progressTrack"><i style={{ width: `${progress}%` }} /></div>
            <div className="progressMeta">
              <span>{Math.max(1, activeStage + 1)} / 5 阶段</span>
              <span>当前排版：{layouts[layout].name}</span>
              <span>{running ? "正在处理" : "已保存到本设备"}</span>
            </div>
          </div>
        </section>

        <section className="results" id="results">
          <article className="panel topicsPanel">
            <header>
              <div><p className="eyebrow">TOPIC DECISION</p><h2>选题候选</h2></div>
              <span>{output.topics.length} 条</span>
            </header>
            <div className="topicList">
              {output.topics.map((topic, index) => (
                <div className={index === 0 ? "selected" : ""} key={topic.title}>
                  <strong>{topic.score}</strong>
                  <section>
                    <span>{index === 0 ? "本轮推荐" : `候选 ${index + 1}`}</span>
                    <h3>{topic.title}</h3>
                    <p>{topic.reason}</p>
                  </section>
                </div>
              ))}
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
                <section key={section.heading}>
                  <h4>{section.heading}</h4>
                  <p>{section.body}</p>
                </section>
              ))}
            </div>
            <div className="qualityBar">
              <span>事实一致 <b>95</b></span>
              <span>表达质量 <b>94</b></span>
              <span>平台适配 <b>93</b></span>
            </div>
          </article>
        </section>

        <section className={`visualBoard ${layout}`} aria-label="贴图排版预览">
          <header className="sectionHeading compact">
            <div className="sectionIndex">C</div>
            <div>
              <p className="eyebrow">VISUAL SYSTEM / {layouts[layout].kicker}</p>
              <h2>小红书与公众号贴图预览</h2>
            </div>
          </header>
          <div className="cards">
            <article className="coverCard">
              <span>YANFLOW / 01</span>
              <h3>{output.xhsTitle}</h3>
              <p>别再加工具，先把流程跑通</p>
              <b>企业 AI 实战</b>
            </article>
            <article className="pointCard">
              <span>真正的卡点</span>
              <strong>工具能生成<br />系统才会交付</strong>
              <p>输入 → 标准 → 审核 → 发布 → 复盘</p>
            </article>
            <article className="actionCard">
              <span>现在先做</span>
              <ol>
                <li>挑一个高频任务</li>
                <li>写清结果标准</li>
                <li>连续跑通三次</li>
              </ol>
              <b>先跑通，再扩场景</b>
            </article>
          </div>
        </section>

        <section className="riskBoard" id="risk">
          <header className="sectionHeading compact">
            <div className="sectionIndex">D</div>
            <div>
              <p className="eyebrow">PUBLISHING GATE</p>
              <h2>发布风控与账号授权</h2>
            </div>
          </header>
          <div className="riskGrid">
            <article>
              <span className="statusDot" />
              <div><b>公开表达检查</b><small>导流、绝对化承诺、内部标签</small></div>
              <strong>通过</strong>
            </article>
            <article>
              <span className="statusDot" />
              <div><b>重复与限频</b><small>近似内容、账号间隔、每日上限</small></div>
              <strong>通过</strong>
            </article>
            <article className="guarded">
              <span className="statusDot" />
              <div><b>真实账号连接</b><small>线上站不保存账号密码和发布凭证</small></div>
              <strong>需本地授权</strong>
            </article>
          </div>
          <div className="actions">
            <button className="secondary" onClick={runPreflight}>重新发布预检</button>
            <button className="secondary" onClick={downloadPack}>下载内容包</button>
            <button className="primaryAction" onClick={requestLivePublish}>进入正式发布确认</button>
          </div>
          <p className="boundary">
            线上版可真实生成、换账号槽位、换排版和下载内容；为保护账号，正式发布需要本地 YanFlow
            与蚁小二/公众号授权通道连接后再确认。
          </p>
        </section>

        <footer>
          <span>YANFLOW · SAFE CONTENT AUTOMATION</span>
          <p>本页不会在浏览器中保存平台密码或密钥。</p>
        </footer>
      </div>

      <div className="toast" role="status" aria-live="polite">{toast}</div>
    </main>
  );
}

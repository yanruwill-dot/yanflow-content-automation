# 系统架构

## 数据流

```text
公开来源 / RSS / 搜索
          │
          ▼
TrendPublish
抓取 → 去重 → 聚类 → 评分 → 证据 → 长文 → 质量审稿
          │
          ▼
YanFlow 本地任务库
公众号正文 + 小红书文案 + 来源 + 质量结果 + 任务级账号/排版
          │
          ▼
Image2 贴图工作台
排版映射 → 内容规划 → 9 张 3:4 图 → 中文/尺寸检查
          │
          ▼
发布风控闸门
禁用词 + 感知哈希 + 内容指纹 + 账号状态 + 限频
          │
          ▼
审计发布器
yxer doctor/accounts/schema/validate/dry-run
          │
      手工确认短语
          │
          ▼
yxer live → query details → 平台状态 / 公开链接
```

## 组件

- `server.py`：仅监听本机的 HTTP 服务、会话校验、静态页面和后台任务入口。
- `core.py`：任务状态机、连接器、风控、图片去重、发布包和定时器。
- `app/`：GitHub Pages 中台；负责选爆款、真实进度、账号槽、Image2 成品和发布确认。
- `static/`：无外部前端依赖的单页控制台。
- `runtime/jobs/`：每次任务的内容、图片、发布包、日志和状态。
- `tests/`：核心逻辑和 HTTP 安全边界测试。

## 账号与排版

- 账号来自 `yxer accounts` 的实时可用列表，前端不写死账号。
- 小红书与公众号分别保存账号 ID；发布预检按任务选择解析真实账号。
- 三套排版同时驱动公众号隔离预览和 Image2 的 `style`、`palette`、`content_pattern`。
- 账号与排版进入发布内容指纹；任何变更都会使旧 Dry-run 失效。
- 外部任务一旦产生任务号、提交状态或公开链接，设置立即锁定，避免换账号后重复提交。

## 状态分层

- `content_ready`：选题、正文和质量审稿完成。
- `images_ready`：成品图已经复制进当前任务。
- `preflight_passed`：完整 Dry-run 通过，尚未正式发表。
- `submitted`：平台已接受任务，但未返回可核验公开链接。
- `published`：平台返回公开链接。
- `blocked`：重复、限频或文案等本地硬规则阻止提交。
- `failed`：连接器、账号、登录或平台检查失败。

## 安全设计

- HTTP 服务仅绑定 `127.0.0.1`。
- 所有非健康检查 API 都要求随机会话令牌。
- 跨域只允许 `https://yanruwill-dot.github.io`，不使用通配符；预检只放行明确的方法和请求头。
- GitHub Pages 配对只接受固定回跳地址，令牌通过 fragment 返回并只存于 `sessionStorage`。
- Cookie 使用 `HttpOnly; SameSite=Strict`。
- 页面不可被 iframe 嵌入；响应使用 `nosniff`。
- 生成文章预览使用隔离 CSP，禁止脚本运行、表单提交和顶层跳转。
- 浏览器端只收到连接状态和脱敏任务结果。
- JSON 文件使用临时文件原子替换并设为用户可读写。
- 正式提交复用 Dry-run 发布包，并再次核验内容、账号、排版指纹、账号频率和图片重复。

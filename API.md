# 本地 API

基础地址：`http://127.0.0.1:8786`

写请求必须带首页注入的 `X-Yanflow-Token`，浏览器页面会自动处理。

## 读取

- `GET /api/health`：服务健康。
- `GET /api/status?accounts=1`：连接器、可用账号和三套排版，只返回脱敏状态。
- `GET /api/settings`：定时和限频设置。
- `GET /api/jobs`：任务列表。
- `GET /api/jobs/:id`：单个任务。
- `GET /api/jobs/:id/preview`：公众号 HTML 预览。
- `GET /api/jobs/:id/assets/:file`：当前任务成品图。

## 写入

- `POST /api/jobs`：新建任务，可传 `account_ids` 和 `layout`：

```json
{
  "brief": "企业 AI 如何进入真实流程",
  "targets": ["小红书", "微信公众号"],
  "account_ids": {
    "小红书": "account-id-1",
    "微信公众号": "account-id-2"
  },
  "layout": "editorial"
}
```

- `POST /api/jobs/:id/publish-settings`：正式提交前更新账号和排版。允许的排版为 `editorial`、`clean`、`song`；变更会作废旧 Dry-run。已有平台任务号或公开链接后拒绝修改。
- `POST /api/jobs/:id/run`：自动跑选题、内容、配图和 Dry-run。
- `POST /api/jobs/:id/research`：只跑选题与内容。
- `POST /api/jobs/:id/images`：只跑 Image2 图组。
- `POST /api/jobs/:id/publish/dry-run`：运行蚁小二完整发布预检。
- `POST /api/jobs/:id/publish/live`：正式发布，JSON 必须含：

```json
{"confirmation": "确认正式发布"}
```

- `POST /api/settings`：保存定时和限频。`live_automation_enabled` 无论传什么都固定为 `false`。

## 返回约定

任务对象不含密钥、Cookie 或原始鉴权错误。外部命令输出最多保留末尾 6000 字符并脱敏。

正式发布结果：

- `task_set_ids`：蚁小二任务编号，不代表已发表。
- `platform_results`：平台详情查询结果。
- `public_urls`：已核验的公开链接；有链接时才标记为 `published`。

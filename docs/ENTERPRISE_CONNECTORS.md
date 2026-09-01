# 企业只读连接器（可选扩展）

连接器负责从企业系统读取任务并转换成 `business-pilot/v1` 数据集。所有连接器只执行 GET，不回写 Jira、GitLab、Zendesk、ServiceNow 或 APM。

> **个人开发者不需要配置本页内容。** 如果你没有企业账号、工单系统或 APM，直接使用公开 GitHub 数据、仓库自带 fixtures 和本地业务评测即可。这里的系统只是未来进入企业环境时的可选适配器。

## 个人开发者默认路径

推荐按下面顺序使用项目：

1. 运行仓库自带的费用、文档排障和执行评测；
2. 使用公开 GitHub 仓库验证软件工程任务采集；
3. 用本地脱敏 JSON 运行 `business_pilot`；
4. 只有在获得企业系统授权后，才配置本页的 Jira/GitLab/Zendesk/ServiceNow/APM 连接器。

```powershell
# 本地业务闭环
& '.\.venv\Scripts\python.exe' examples/eval/run_business_pilot.py --source expense

# 公开 GitHub 只读数据
& '.\.venv\Scripts\python.exe' examples/eval/run_github_business_tasks.py `
  --repository weihuaguo270-ops/agent-delivery-sandbox `
  --out docs/snapshots/github_public_read_only_latest.json
```

个人开发者不需要申请 Jira、GitLab、Zendesk、ServiceNow 或 APM 账号，也不需要创建企业服务账号。

## 配置

每个数据源使用独立环境变量：

```text
JIRA_BASE_URL / JIRA_READONLY_TOKEN
GITLAB_BASE_URL / GITLAB_READONLY_TOKEN
ZENDESK_BASE_URL / ZENDESK_READONLY_TOKEN
SERVICENOW_BASE_URL / SERVICENOW_READONLY_TOKEN
APM_BASE_URL / APM_READONLY_TOKEN
```

## 只读凭据的开通

凭据必须由目标系统管理员创建。项目不会自动创建账号、申请 OAuth 授权或提升权限；连接器只使用已经拿到的只读 Token 发起 GET 请求。

### Jira

1. 创建专用服务账号，不使用个人账号。
2. 在目标项目的 Permission scheme 中只授予 `Browse Projects` 和读取 Issue 所需权限。
3. Jira Cloud 在账号安全设置中创建 API token；Jira Server/Data Center 使用管理员允许的 PAT 或 OAuth 只读客户端。
4. Jira Cloud Basic 认证需要把 `邮箱/token:API_TOKEN` 做 Base64 编码，完整值放入 `JIRA_READONLY_TOKEN`：

```powershell
$pair = "service-account@example.com/token:API_TOKEN"
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
```

配置为：

```text
JIRA_AUTH_HEADER=Authorization
JIRA_AUTH_SCHEME=Basic
```

不要把上面命令的输出写进代码仓库或发送到聊天记录。

### GitLab

1. 优先在目标项目创建 Project Access Token；没有该权限时再使用受限的 Group Access Token。
2. 角色使用 `Reporter` 或组织规定的最低只读角色。
3. Scope 只勾选 `read_api`，不要勾选 `api`、`write_repository` 或其他写权限。
4. Token 只显示一次，立即存入 Secret Manager 或本机 `.env`。

```text
GITLAB_AUTH_HEADER=PRIVATE-TOKEN
GITLAB_AUTH_SCHEME=
```

### Zendesk

1. 创建专用 Agent/服务身份，限制到需要读取的组或工单范围。
2. 在 Admin Center 的 API 设置中启用 API token，并创建专用 Token。
3. 使用 `邮箱/token:API_TOKEN` 做 Base64 编码，配置为 Basic 认证：

```text
ZENDESK_AUTH_HEADER=Authorization
ZENDESK_AUTH_SCHEME=Basic
```

4. 只授予 Ticket read；不授予 Ticket write、User admin 或 Account admin。

### ServiceNow

1. 创建专用 Integration User，不使用管理员账号。
2. 在目标表（通常为 `incident`）的 ACL 中只授予读取权限，并限制查询范围。
3. 由管理员注册 OAuth Client 或按组织规范签发短期 Bearer Token。
4. 当前连接器接收已经换取的访问 Token，不负责保存 Client Secret 或执行 OAuth 换 token：

```text
SERVICENOW_AUTH_HEADER=Authorization
SERVICENOW_AUTH_SCHEME=Bearer
```

### APM / Trace

APM 不是统一产品，需按实际供应商创建只读凭据：

- Datadog：只读 API/Application Key，并限制站点和查询范围；
- Elastic：创建只读 API Key，只授予目标索引的读取权限；
- Sentry：只授予事件/Issue 读取权限；
- 自建 OpenTelemetry 或 Trace 服务：提供带只读认证的 GET 查询接口。

当前 `TraceAdapter` 只需要一个可查询的 GET endpoint、Token 和 `trace_id`；不会自动适配各厂商 OAuth、签名或查询 DSL。

## 凭据交付和轮换

推荐链路：

```text
管理员创建只读身份
→ Secret Manager / CI Secret
→ 进程环境变量
→ 配置检查
→ limit=1 只读试采
→ 扩大时间窗和任务量
```

Token 不应出现在 Git、Issue、日志、JSON 任务、命令行参数或截图中。设置过期时间和轮换责任人；轮换时先创建新 Token、验证新 Token，再撤销旧 Token。发生泄露时立即撤销，不要只修改项目文件。

### Windows PowerShell

在当前终端临时配置（关闭终端后失效）：

```powershell
$env:JIRA_BASE_URL = "https://jira.example.com"
$env:JIRA_READONLY_TOKEN = "<只读凭据>"
$env:JIRA_AUTH_HEADER = "Authorization"
$env:JIRA_AUTH_SCHEME = "Bearer"

& '.\.venv\Scripts\python.exe' examples/eval/check_enterprise_connector_config.py --source jira
```

长期使用时，把同样的变量放入本机 `.env` 或 CI Secret；连接器脚本会读取项目根目录 `.env`，并且不会覆盖已经存在的进程环境变量。`.env` 已被 `.gitignore` 忽略，不能提交到仓库。PowerShell 也可以手动加载：

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
  }
}
```

上面的检查只输出 URL、认证头、认证方案和 `token_set`，不会输出 Token。`check_enterprise_connector_config.py` 只检查配置存在，不会联网验证凭据。

### Linux / macOS / CI

```bash
export JIRA_BASE_URL="https://jira.example.com"
export JIRA_READONLY_TOKEN="<只读凭据>"
export JIRA_AUTH_HEADER="Authorization"
export JIRA_AUTH_SCHEME="Bearer"
python examples/eval/check_enterprise_connector_config.py --source jira
```

CI 中应使用平台 Secret 注入环境变量，不要在 workflow YAML、命令行参数、JSON 数据集或报告中写入 Token。

默认认证头为 `Authorization: Bearer <token>`。系统要求其他格式时可设置：

```text
<PREFIX>_AUTH_HEADER=PRIVATE-TOKEN
<PREFIX>_AUTH_SCHEME=
```

GitLab Personal Access Token 常用 `GITLAB_AUTH_HEADER=PRIVATE-TOKEN` 且 scheme 为空。Jira/Zendesk 如果使用 Basic 认证，应把已编码凭据放入只读 Secret，并把 scheme 设为 `Basic`。Token 不写入项目文件。

## 采集命令

```bash
python examples/eval/collect_enterprise_source.py --source jira --out artifacts/import/jira.json
python examples/eval/collect_enterprise_source.py --source gitlab --project-id 42 --out artifacts/import/gitlab.json
python examples/eval/collect_enterprise_source.py --source zendesk --out artifacts/import/zendesk.json
python examples/eval/collect_enterprise_source.py --source servicenow --table incident --out artifacts/import/servicenow.json
python examples/eval/collect_enterprise_source.py --source apm --query-path /traces --trace-id TRACE_ID --out artifacts/import/apm.json
```

采集前先运行配置检查；检查通过后再执行采集。`--project-id`、`--table` 和 `--trace-id` 是业务范围参数，不属于 Secret。

## 输出边界

采集结果只包含来源任务、来源状态和引用。它不会自动生成 baseline、candidate 或人工复核结论。内置脱敏只覆盖常见凭据和邮箱，输出中的 `human_verified=false` 表示仍需业务方复核。

接入 `business_pilot` 前还需要：

1. 运行 baseline 和 candidate，并写入各自的 `passed` 和时延；
2. 由授权人员填写 `human_review.decision`；
3. 从业务系统回填最终状态；
4. 冻结 held-out 切片后再执行版本门禁。

没有对应系统的 URL、只读 Token 和字段权限时，只能运行 mock 测试，不能声称已经连接企业生产系统。

## 权限要求

| 来源 | 最小权限建议 | 不应授予 |
|------|--------------|----------|
| Jira | 目标项目 Issue Browse / API read | Issue 写入、Transition、Admin |
| GitLab | 目标项目 `read_api` 或等价只读范围 | `api`、Repository write |
| Zendesk | Ticket read、User read（如确有需要） | Ticket write、Admin |
| ServiceNow | 目标表 read ACL | Table write、Script、Admin |
| APM / Trace | 指定服务和时间窗的查询权限 | 删除、修改、部署或全库导出 |

配置完成后，建议先用最小 `--limit 1` 做小范围读取，再扩大到业务时间窗。采集出的 `human_verified=false` 必须由授权人员复核后改为 `true`，否则 `business_pilot` 会保持 `hold`。

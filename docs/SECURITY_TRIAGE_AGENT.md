# Security Triage Agent

`security_triage` 是 `react-agent` 中独立、只读的安全垂直应用和跨域评测 benchmark，服务于公开威胁情报辅助研判，不是漏洞扫描器或自动处置平台。它的定位是为通用 Agent 评测提供高风险、强证据约束的被测场景。

## MVP 范围

- CVE 查询：返回描述、严重度、CVSS、CWE 和 NVD 引用。
- KEV 校验：核对 CISA Known Exploited Vulnerabilities Catalog。
- ATT&CK 映射：依据 CWE/描述生成候选 Technique，始终标记 `inferred`、`authoritative=false`。
- IOC 富化：支持 IP、域名、MD5、SHA-1、SHA-256；无命中不等于安全。
- 引用式报告：事实、推断和建议均保留证据 ID，报告末尾列出公开来源 URL 与获取时间。
- 人工复核：默认 `pending_review`；只有请求携带有效 reviewer 和 approve/reject 决定时才转为 `approved`/`rejected`。
- 资产/SBOM 关联：仅关联请求中组件明确声明的 `cve_ids`，不根据名称或版本猜测受影响关系。
- CycloneDX 只读导入：可在请求中携带 inline `sbom` 文档；应用不抓取 URL、不读取任意路径。
- 持久化案件：FastAPI 提供版本化案件、独立复核接口和追加式复核审计事件。

## 快速运行

```bash
python examples/demos/demo_security_triage.py
```

HTTP 请求：

```json
{
  "app": "security_triage",
  "message": "研判 CVE-2021-44228 和 example.invalid",
  "cve_ids": ["CVE-2021-44228"],
  "iocs": ["example.invalid"]
}
```

复核决定通过同一请求的 `review` 字段显式提交：

```json
{
  "app": "security_triage",
  "cve_ids": ["CVE-2021-44228"],
  "message": "review",
  "review": {"decision": "approve", "reviewer": "analyst-01", "notes": "已核对资产范围"}
}
```

上面的 `/v1/chat` 形式保留用于无状态兼容。需要持久化和独立人工复核时，使用案件 API：

```http
POST /v1/security/cases
```

```json
{
  "message": "研判 CVE-2021-44228",
  "cve_ids": ["CVE-2021-44228"],
  "assets": [
    {
      "asset_id": "edge-api-01",
      "name": "Edge API",
      "criticality": "critical",
      "internet_exposed": true,
      "owner": "platform-team",
      "components": [
        {
          "component_id": "pkg-1",
          "name": "log4j-core",
          "version": "2.14.1",
          "cve_ids": ["CVE-2021-44228"],
          "source": "cyclonedx-import"
        }
      ]
    }
  ]
}
```

创建结果固定为 `version=1`、`status=pending_review`。随后可查询和复核：

```http
GET  /v1/security/cases/{case_id}
POST /v1/security/cases/{case_id}/reviews
GET  /v1/security/cases/{case_id}/reviews
```

```json
{
  "decision": "approve",
  "reviewer": "analyst-01",
  "notes": "资产和 SBOM 已复核",
  "expected_version": 1
}
```

复核成功后案件变为 v2；旧版本复核请求返回 HTTP `409 case_version_conflict`，防止并发覆盖。批准表示报告已经复核，不会执行报告中的处置建议。

LLM 报告编辑器默认关闭。设置 `REACT_AGENT_SECURITY_LLM=1` 后才会调用当前 `react_agent.llm` provider；模型只接收结构化证据和引用 ID，输出若含未知引用、丢失 `not executed` 边界或无引用，会自动回退到确定性报告，并在 `case.llm_report.failure` 与 `case.trace` 中记录。

真实模型评测命令：

```bash
python examples/eval/run_security_triage_llm_eval.py --candidates deepseek
```

报告协议现为 `security-triage-report/v2`：模型必须返回 `claims`、`recommendations`、`limitations` JSON；引用缺失时最多执行一次只补引用/边界的修复回合，不改变事实文本，修复仍失败则回退确定性报告。

2026-08-31 v2 在 `deepseek-v4-flash`、36 条离线黄金案件上重复 2 次（共 72 次）实测：确定性基线 `36/36`；模型报告有效率与引用绑定率 `100%`，边界保留率 `100%`，回退率 `0%`，错误安全断言 `0`；模型/最终报告事实一致率 `98.61%`；平均端到端延迟 `4970 ms`，P95 `9422 ms`。分类覆盖 KEV 命中/未命中、未知 CVE、IOC 命中/未命中/多源冲突、单资产/多资产/SBOM/无匹配资产等 16 类场景，分类指标写入 `artifacts/security-triage-llm-eval-20260831.json`。该结果是固定快照上的工程验证，不代表公开情报完整性、模型泛化准确率或自动处置授权。

离线黄金集与回放：

```bash
python examples/eval/run_security_triage_eval.py --replay-out artifacts/security-triage/replays.jsonl
```

同时导出统一跨仓 Episode，供 `llm-eval-engine` 导入、终态验证和发布门禁：

```bash
python examples/eval/run_security_triage_eval.py \
  --episodes-out artifacts/security-triage/security-episodes.jsonl
```

输出为 `evaluation-episode/v1`，包含 `expected_state`、`final_state`、`state_verification`、Format B 轨迹和安全场景元数据。`expected_state` 记录 KEV、资产关联、优先级、复核状态、引用和零执行约束；`final_state` 记录实际案件状态、引用 ID、LLM 回退信息和最终报告。Episode metadata 同时记录 `feedback_targets` 和 `failure_feedback`，把失败映射到 Prompt、工具 Schema、工作流校验器或报告生成节点；黄金集聚合结果的 `feedback_queue` 可直接作为下一版本修复输入。下游可使用 `eval_engine.integrations.episode.import_episode` 与 `verify_episode_state`，再接入业务终态、过程质量、失败回归和性能证据门禁。

评测输出包含案件准确率、引用支持率、事实一致率、边界保留率、自动回退率、错误安全断言数、平均/P95 延迟及按场景分类指标。当前黄金集为 36 条，要求每个候选模型通过 1–3 次重复运行以观察稳定性；`security-triage-replay/v1` 记录可用 `react_agent.apps.security_triage.replay.replay_record` 重演。

案件 API 使用 SQLAlchemy。数据库地址按 `REACT_AGENT_SECURITY_DATABASE_URL`、`REACT_AGENT_DATABASE_URL`、`sqlite:///react_agent_security.db` 的顺序选择。部署环境应先执行：

```bash
alembic upgrade head
```

默认读取 `public_intel_snapshot.json`，保证测试与演示可复现。设置 `REACT_AGENT_SECURITY_LIVE=1` 后，才会以只读请求访问固定的 NVD CVE API、CISA KEV JSON 和 ThreatFox API；可用 `REACT_AGENT_SECURITY_TIMEOUT` 设置超时秒数。

## 安全边界

- 不执行扫描、漏洞利用、封禁、隔离、补丁或配置变更。
- 所有处置建议均为 `execution=not_executed` 且 `requires_human_approval=true`。
- ATT&CK 是行为知识库，不存在本应用可声称权威的 CVE-to-ATT&CK 映射；候选结果必须结合实际遥测和攻击路径复核。
- 离线快照是有界样本。未出现的 CVE、KEV 或 IOC 只代表快照未收录，不能作为“不存在”或“安全”的证据。
- 公共情报不能证明组织资产受影响，仍需由获授权人员结合资产清单、SBOM、版本和日志确认。
- 请求声明的 SBOM→CVE 关系被视为组织证据，不代表系统独立完成了版本影响判定。
- 当前 reviewer 来自请求字段；生产部署必须由认证身份覆盖或校验该字段，并配置 RBAC。

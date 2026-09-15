# 项目定位与优化进度

维护人：郭伟华  
状态：Active  
最近更新：2026-09-12
用途：每次开始项目优化前先阅读；完成优化后更新进度、证据和边界。

## 一句话定位

本项目是一个面向求职展示的、可部署和可评测的企业 Agent 工程原型，当前以
**软件工程交付**为唯一主验证方向，以技术支持作为次级业务示例，以轨迹、评测、
权限和容器 Sandbox 作为共享工程能力。

项目不是已经投入企业生产的 SaaS，也不以“覆盖最多 Agent 方向”为目标。当前优化
目标是证明：Agent 能在受控权限内完成可执行的软件任务，其结果可由外部任务、测试
和人工审查独立验证。

## 求职口径

可以表述：

> 实现了带权限闸门、轨迹、回归评测和容器隔离的企业 Agent 工程原型，并在受控业务
> 任务、公开 GitHub 数据和 Docker 上完成可复现验证；当前继续补充软件交付
> 任务的外部独立结果。

不能表述：

- 已在企业生产环境部署或形成长期线上流量；
- 已证明节省人工成本、提高企业收入或达到生产 SLA；
- 受控夹具成功率等于真实业务成功率；
- 公开 GitHub 元数据读取等于 Issue 解决能力；
- Docker live-check 等于完成企业安全认证；
- 自建子集结果等于 SWE-bench、SWE-bench Verified 等完整榜单结果。

## 当前结构

| 层级 | 内容 | 定位 |
|------|------|------|
| 主业务验证 | GitHub/software delivery：Issue、补丁、测试、审查、候选提交 | 后续优化的唯一主线 |
| 次级业务示例 | docs_troubleshoot 技术支持、费用状态验证 | 保留回归，不继续横向扩张 |
| 共享能力 | ReAct、工具边界、轨迹、评测、版本门禁、RAG（本地 / 可选 Milvus） | 为主业务服务 |
| 安全能力 | permission gate、process/container Sandbox | 证明执行边界，不证明业务价值 |
| 实验能力 | MCP、LangGraph、多 Agent 等 | 非默认路径，除非主线需要否则不扩展 |

## 已有证据

| 证据 | 当前结果 | 能证明什么 | 不能证明什么 |
|------|----------|------------|--------------|
| 费用业务夹具 | reference 8/8；no_action 0/8 并触发 hold | 状态断言和发布门禁可工作 | 真实费用业务收益 |
| GitHub 公开组合集 | 10 仓库、50 个元数据任务，三切片门禁通过 | 外部只读数据采集、追溯和切片可工作 | Agent 解决了 50 个 Issue |
| agent-delivery-sandbox | 真实 GitHub 写入与受控 PR 生命周期 | 写入审批和交付流程可执行 | 真实用户任务或上游采用率 |
| Docker Sandbox | Docker live-check 23/23；安全专测 17 passed | Docker 容器约束实际生效 | 逃逸防护认证、多租户安全 |
| 全量代码回归 | 2026-09-02：267 passed、6 skipped、13 deselected（排除 `real_llm` / `mysql_live`；270 项被收集） | 当前默认离线测试路径无已知回归 | 生产可靠性和外部业务效果 |
| Milvus 本机集成 | Docker Compose 启动 Milvus / etcd / MinIO / Agent；HNSW 写入、检索、来源枚举、清理和 `/v1/chat` 均已联调 | 可选向量库后端与 Agent 容器可协同运行 | 多实例容量、鉴权、备份、生产 SLA |

测试数只能引用相同提交、依赖和收集条件下的结果；`real_llm` 与 `mysql_live` 因依赖外部
凭据/服务未包含在上述本机离线回归中。

## 最大缺口

当前最大缺口不是功能数量，而是缺少由项目外部定义成败的软件交付结果：

```text
公开真实任务
→ 固定基础 commit
→ baseline 和 candidate 独立执行
→ 可执行测试
→ 盲化人工审查
→ 实际采用、拒绝或返工
→ 下一版本回归
```

当前大部分结果仍由本项目同时定义任务、验收条件和结果。下一阶段必须减少“自测
自己”，而不是继续添加新的垂直场景、连接器或孤立指标。

## 外部验证计划

### P0：冻结实验契约

目标：让不同版本在完全相同的条件下可比较。

- 主场景固定为软件工程交付；
- 记录 baseline 的 Git commit/tag、依赖锁定信息和运行配置；
- 定义统一任务 Schema：Issue、base commit、允许修改范围、测试命令、超时和来源；
- 固定结果 Schema：补丁、轨迹、测试结果、成本、时延、人工修改和最终判定；
- 仓库级隔离 dev/golden/held_out，禁止同一仓库跨 split 泄漏；
- baseline 不再使用 `no_action` 代表历史版本；`no_action` 只保留为门禁故障演练。

完成门禁：同一任务可以由两个版本重复执行，报告能够识别提升、持平和逐用例回归。

边界：冻结实验契约只提高可比性，不产生外部业务成绩。

### P1：建立外部历史任务集

目标：使用真实公开 Issue，但先采用离线历史回放，避免未经维护者允许写入上游仓库。

- 从 3 至 5 个 Python 开源仓库选择 10 至 20 个已关闭、带可执行测试的历史 Issue；
- checkout 修复前的 base commit，不向 Agent 提供官方修复补丁；
- 将官方修复后的测试或独立复现测试作为隐藏验收；
- 保存 Issue URL、仓库 commit、许可证边界和数据指纹；
- 初始建议切片：dev 4、golden 6、held_out 10；样本不足时如实记录实际数量；
- 排除依赖外部付费服务、无法稳定构建或验收标准不明确的任务。

完成门禁：至少 10 个任务可重复构建，全部有来源、base commit 和确定性测试；held_out
至少包含两个项目簇。

边界：历史 Issue 是真实外部任务，但离线回放不是生产流量，也不代表维护者接受本项目
生成的补丁。

### P2：运行 baseline/candidate 对比

目标：证明优化来自 Agent 版本变化，而不是数据、测试或人工口径变化。

- baseline 使用冻结的真实旧提交，不使用故障注入代替；
- candidate 使用待发布提交；
- 两个版本使用相同模型、预算、超时、工具权限和任务顺序；
- held_out 在实现完成前不查看隐藏测试结果；
- 每个任务保留完整轨迹、补丁、stdout/stderr、退出码和环境指纹；
- 至少重复运行不确定任务 3 次，单独报告 flaky，而不是挑选最好结果。

核心指标：

| 指标 | 定义 | 是否硬门禁 |
|------|------|------------|
| task_success_rate | 补丁应用成功、验收测试通过且无禁止副作用 | 是 |
| first_attempt_success | 第一次提交即通过验收 | 是 |
| regression_rate | 原有测试由通过变失败 | 是，必须为 0 |
| unauthorized_write_rate | 修改允许范围外文件或产生未授权外部写 | 是，必须为 0 |
| human_edit_ratio | 人工最终修改量 / Agent 初始补丁量 | 否，报告分布 |
| review_rounds | 达到可接受结果所需审查轮次 | 否 |
| duration_p50/p95 | 单任务墙钟时间 | 否 |
| cost_per_success | 成功任务的模型和工具成本 | 否 |

完成门禁：candidate 在 held_out 无硬指标退化；所有百分比同时报告分子、分母和失败清单。

边界：10 至 20 个任务只能形成项目级证据，不能宣称达到行业总体水平。

### P3：独立人工审查

目标：减少作者同时开发、标注和验收造成的偏差。

- 审查材料隐藏版本名称，只展示 Issue、补丁和测试证据；
- 优先邀请另一名开发者按照固定 Rubric 审查；
- 无外部审查者时可以做盲化自审，但证据等级必须标记为 `author_blinded_review`；
- Rubric 至少覆盖正确性、最小改动、可维护性、测试充分性和安全副作用；
- 保存原始判定和修改理由，不只保存 accepted/rejected。

完成门禁：每个 held_out 任务都有审查记录；缺少独立审查时不得写“独立人工验证”。

边界：个人审查或少量志愿审查不等于企业 Code Review 流程。

### P4：小规模真实上游结果

目标：获得最强的外部采用证据，但不把提交 PR 当作完成指标。

- 只选择维护者明确欢迎贡献、范围适当且尚未被他人认领的问题；
- 提交前人工检查补丁、测试、许可证和贡献指南；
- 初期目标为 1 至 3 个高质量 PR，不追求数量；
- 记录 accepted、changes_requested、rejected、closed 和 merged；
- 记录人工修改比例、Review 轮次和从提交到最终状态的时间；
- 不自动批量提交，不让 Agent 直接绕过人工审批写入上游。

完成门禁：至少形成一个可公开追溯的上游最终状态；没有合并也应如实分析拒绝原因。

边界：少量 PR 只能作为案例证据，不能推导企业采用率或稳定业务收益。

## 进度表

| 阶段 | 状态 | 当前产物 | 下一动作 |
|------|------|----------|----------|
| 工程原型 | 已完成 | runtime、权限、轨迹、评测、HTTP、文档 | 仅维护回归 |
| 容器安全基线 | 已完成本机验证 | `sandbox_live_check_latest.json`，23/23 | 保持回归；不扩写为安全认证 |
| 受控 GitHub 交付 | 已完成 | agent-delivery-sandbox | 保留为流程证据 |
| P0 实验契约 | 进行中 | `schemas/software_task.schema.json`、`eval/software_task.py`、`eval/software_task_runner.py`；新增 `skills/business_boundaries.py` 与边界 Schema；DeliveryTask 已支持 `base_commit` | 冻结 baseline/candidate 运行器和结果 Schema，并接入 GitHub Workflow |
| P1 外部历史任务集 | 进行中 | `eval/software_task_dataset_manifest.json`（清单状态 `pending_external_data`）；`src/react_agent/eval/software_task_dataset.py` | 获取并人工审核首批 3 个仓库、约 10 个可回放 Issue |
| P2 版本对比 | 未开始 | no_action 仅为故障演练 | 使用真实旧版本运行 baseline |
| P3 独立审查 | 未开始 | 受控 reviewer 字段 | 建立盲化 Rubric 和原始审查记录 |
| P4 上游结果 | 未开始 | 受控 Draft PR | 人工选择 1 至 3 个适合贡献的问题 |

状态只能使用：`未开始`、`待开始`、`进行中`、`已完成`、`阻塞`。更新状态时必须附产物
路径或明确阻塞条件，不能只修改文字。

## 每次优化前检查

1. 本次修改是否直接改善软件工程交付主线？
2. 它解决的是已观察失败，还是为了“看起来更完整”新增功能？
3. 对应任务、baseline、指标和验收器是什么？
4. 结果属于受控夹具、公开只读、外部回放还是真实上游采用？
5. 是否会改变数据集、Schema、指标或安全边界？
6. 是否需要更新 held_out、证据快照或发布门禁？
7. 是否能在不增加新抽象和新依赖的情况下完成？

出现以下情况时暂停实现：

- 新增第三条业务主线；
- 只有功能描述，没有对应任务和验收标准；
- 用更多自建样本代替外部有效性；
- 为了提高总分修改 held_out 或隐藏测试；
- 将测试通过率直接换算为企业收益；
- 需要自动向第三方仓库写入但没有人工批准。

## 每次优化后检查

1. 运行与风险相称的针对性测试和全量回归；
2. 保存原始 JSON、任务清单、失败清单和环境信息；
3. 更新本文件的进度、指标、证据路径和边界；
4. 更新相关 README/架构文档，删除与最新证据冲突的旧口径；
5. 检查注释是否解释约束和原因，而不是逐行复述代码；
6. 执行 lint、`git diff --check`，确认没有提交密钥或运行时缓存；
7. 报告失败和 skipped，不只报告通过数量；
8. 新增能力必须说明“不证明什么”。

## 优化记录模板

每次更新在本节顶部追加一条：

```text
日期：YYYY-MM-DD
目标：
假设：
修改范围：
数据/任务：
baseline：
candidate：
核心结果：
失败与回归：
证据路径：
证据等级：controlled_fixture | public_read_only | external_replay |
          author_blinded_review | independent_review | upstream_outcome
明确边界：
下一动作：
```

### 2026-08-22：定位冻结

- 目标：停止泛化扩张，将外部验证集中到软件工程交付。
- 当前结果：费用夹具、GitHub 公开数据、受控交付和 Docker 安全证据已归档。
- 明确边界：当前是求职用企业 Agent 工程原型，不是生产企业产品。
- 下一动作：执行 P0，冻结真实 baseline、任务 Schema 和结果 Schema。

### 2026-09-02：Milvus 可选后端与本机容器联调

- 目标：在不破坏离线可复现路径的前提下，为共享 RAG 增加可部署的向量库后端。
- 修改范围：`RAG` local/milvus 后端切换、HNSW 索引、Milvus Compose 覆盖文件、CPU-only
  RAG 镜像依赖和 docs_troubleshoot 批量摄取。
- 核心结果：本机 Docker Compose 下，Milvus、etcd、MinIO 与 Agent 均健康；HNSW 写入、
  检索、来源枚举、清理和 `/v1/chat` 已真实联调。
- 失败与回归：发现 Milvus 查询窗口上限和高频 flush 限流，已改为受限查询窗口与批量 flush；
  默认离线回归为 267 passed、6 skipped、13 deselected（270 项被收集）。
- 证据路径：`docker-compose.milvus.yml`、`src/react_agent/milvus_store.py`、
  `tests/test_rag_milvus.py`、`docs/EXPERIMENTAL.md`。
- 证据等级：`local_integration`（本机容器联调，非外部业务或生产流量）。
- 明确边界：Milvus 能力属于共享 RAG 基础设施，不改变软件工程交付仍为主业务验证方向。
- 下一动作：P0 冻结实验契约仍是主线；Milvus 仅按主线实际需要补充鉴权、备份和容量证据。

### 2026-09-11：第一阶段业务交付边界契约

- 目标：把软件工程交付和技术支持的业务边界从文档约定变成可校验契约，减少模型自行扩展任务范围。
- 修改范围：`src/react_agent/skills/business_boundaries.py`、`SkillDef.boundary`、四个内置 Skill 的边界定义、`schemas/business_boundary.schema.json`、`tests/test_business_boundaries.py`。
- 核心结果：每个 Skill 都声明目的、必经步骤、输入输出、允许工具、成功条件、人工接管条件和禁止动作；注册时检查契约一致性，执行前拒绝显式越界动作；完整边界按 progressive disclosure 提供。
- 验证结果：边界专项测试 `5 passed`；业务 Skill 回归 `19 passed`；默认离线全量回归 `287 passed、6 skipped、13 deselected`。测试临时目录固定在工作区后，不再出现 Windows 临时目录权限错误。
- 证据路径：`tests/test_business_boundaries.py`、`docs/BUSINESS_SKILLS.md`。
- 证据等级：`controlled_fixture`（契约和受控 Workflow 测试，不是外部业务结果）。
- 明确边界：该阶段证明的是边界可声明、可发现和部分越界请求可拒绝，不证明模型对隐含意图的完全服从，也不证明真实生产权限和业务收益。
- 下一动作：将 `SoftwareTask` 的隐藏测试、允许修改路径和 Docker Runner 接入 GitHub 交付 Workflow，随后运行冻结的 baseline/candidate 对比。

### 2026-09-11：技术支持多模态证据输入

- 目标：让截图、文档等文件可以作为技术支持的可追溯证据进入现有排障流程，同时避免把未经过 OCR/VLM 的内容当成已理解事实。
- 修改范围：`apps/docs_troubleshoot/evidence.py`、`skills/builtins.py`、`server/handlers/docs_chat.py`、`apps/docs_troubleshoot/offline_answer.py`、`tests/test_multimodal_input.py`。
- 核心结果：支持最多 10 个本地受控文件；记录 MIME、大小、SHA-256、提取状态和 `evidence_ref`；文件失败返回 `partial/failed`，不阻断其他文本证据；`/v1/chat` 和 `docs_troubleshoot` Skill 返回多模态摘要。
- 验证结果：多模态、技术支持、Skill 和 FastAPI 回归 `32 passed`；多模态专项 `6 passed`。
- 证据路径：`docs/MULTIMODAL_FOUNDATION.md`、`tests/test_multimodal_input.py`。
- 证据等级：`controlled_fixture`（本地文件和离线 Workflow 测试）。
- 明确边界：当前只证明输入归一化和证据登记，不证明 OCR/VLM 识别准确率、图片内容检索、生产上传安全或真实业务收益。
- 下一动作：在 P0 软件交付契约完成后，为技术支持增加受控 OCR/VLM 适配器、脱敏扫描和多模态评测集，再决定是否扩展到报销发票场景。

### 2026-09-11：SoftwareTask 接入 GitHub 交付验收门

- 目标：统一 `DeliveryTask` 与 `SoftwareTask`，让公开测试、隐藏测试、允许修改路径和 Docker 隔离真正参与软件交付结果判定。
- 修改范围：`apps/github_delivery.py`、`eval/software_task_runner.py`、`tests/test_software_task_runner.py`、`tests/test_github_delivery_workflow.py`、`docs/GITHUB_DELIVERY_WORKFLOW.md`。
- 核心结果：`WorkflowConfig.software_task_runner` 启用后，交付流程把任务转换为 `SoftwareTask`；Runner 在同一隔离工作区执行公开/隐藏测试，检查越权路径，并将测试明细、任务哈希和资源边界写回报告。未注入 Runner 时保留旧本地测试路径。
- 验证结果：SoftwareTask Runner、GitHub Workflow 和业务 Skill 回归 `29 passed`；全量默认离线回归此前为 `287 passed、6 skipped、13 deselected`。
- 证据路径：`docs/GITHUB_DELIVERY_WORKFLOW.md`、`tests/test_github_delivery_workflow.py`、`tests/test_software_task_runner.py`。
- 证据等级：`controlled_fixture`（受控 Git 夹具和模拟 Docker Runner；未进行本次真实 Docker 交付联调）。
- 明确边界：该阶段证明统一契约和调用链可工作，不证明真实历史 Issue 修复率、Docker 生产容量或外部仓库采用率。
- 下一动作：冻结首批公开历史 Issue，分别运行真实旧版本 baseline 和当前 candidate，形成可比较的外部回放结果。

### 2026-09-12：历史软件任务集清单与隔离校验

- 目标：为外部 Issue 回放建立可审计的任务集边界，先解决“数据是否可比较”，再开始运行 Agent。
- 修改范围：`src/react_agent/eval/software_task_dataset.py`、`schemas/software_task_dataset.schema.json`、`eval/software_task_dataset_manifest.json`、`tests/test_software_task_dataset.py`、`docs/SOFTWARE_TASK_DATASET.md`。
- 核心结果：清单强制来源、许可证、构建镜像、仓库簇和隐藏测试；拒绝只读 GitHub 元数据或 fixture 冒充代码修复任务；跨 split 仓库簇、重复任务 ID 和不完整任务会在加载阶段失败；任务顺序标准化并提供任务集哈希。
- 验证结果：任务集与单任务 Schema 专项 `13 passed`。当前清单为空且标记 `pending_external_data`，因此尚未声称有外部 Issue 修复结果。
- 证据路径：`docs/SOFTWARE_TASK_DATASET.md`、`eval/software_task_dataset_manifest.json`、`tests/test_software_task_dataset.py`。
- 证据等级：`controlled_fixture`（清单规则和校验器测试）。
- 明确边界：这次只证明任务集元数据和切片规则可校验，不证明任何仓库代码已修复，也不证明 baseline/candidate 差异。
- 下一动作：人工审核并冻结首批外部任务，保存仓库许可、base commit、公开/隐藏测试和构建记录后，才进入 P2 版本对比。

### 2026-09-12：任务集导入和测试环境修复

- 目标：明确外部任务从哪里进入，并修复本机回归无法创建 pytest 临时目录的问题。
- 修改范围：`src/react_agent/eval/software_task_dataset.py`、`scripts/import_software_task_dataset.py`、`tests/conftest.py`、`docs/SOFTWARE_TASK_DATASET.md`。
- 核心结果：支持导入人工审核后的 JSON 数组或 JSONL 记录；导入后仍执行来源、许可证、隐藏测试、构建和 split 隔离校验。pytest 临时目录固定到仓库可写目录，避免 Windows 系统 Temp 权限限制。
- 验证结果：任务集与单任务 Schema `14 passed`；GitHub 交付和业务 Pilot 回归 `14 passed`；默认离线回归（排除 `real_llm` / `mysql_live`）`298 passed、6 skipped、13 deselected`。缺少 `langgraph` 时 MySQL live 测试现在会正确跳过；实时 LLM 仍需有效凭据和可用网络。
- 证据路径：`scripts/import_software_task_dataset.py`、`tests/test_software_task_dataset.py`、`tests/conftest.py`。
- 证据等级：`controlled_fixture`（本地导入和回归测试）。
- 明确边界：导入器不会自动从 GitHub 下载任务，也不会把候选记录视为真实外部回放；必须先人工审核并补齐仓库快照和测试。
- 下一动作：导入首批真实公开 Issue，验证仓库可构建后再运行 baseline/candidate。

### 2026-09-12：证据策略与候选数据转换

- 目标：吸收成熟 Agent 框架的状态治理思想，同时修正普通常识问题被内部检索规则误伤的问题，并给现有 GitHub 快照提供可审核的导入入口。
- 修改范围：`apps/docs_troubleshoot/prompt.py`、`apps/docs_troubleshoot/agent_runner.py`、`scripts/export_github_task_candidates.py`、`docs/SOFTWARE_TASK_DATASET.md`。
- 核心结果：内部文档/API/日志问题仍要求检索和引用；普通常识问题不再强制查询内部知识库。GitHub 只读快照可导出为 `review_queue_only` 候选队列，但缺失字段会显式列出，不能直接执行。
- 验证结果：docs 排障、难度分类、GitHub 候选门禁和任务集校验 `14 passed`；其中
  Golden 34 条全部通过（包括 6 条 held_out）。默认离线全量回归仍需另行运行，实时
  LLM 和外部 Issue 回放不在本次结果内。
- 明确边界：该策略不替代事实核验；常识回答仍受模型准确性影响。候选导出不产生 `SoftwareTask`，不证明外部 Issue 可构建或可修复。
- 下一动作：按 `docs/SOFTWARE_TASK_DATASET.md` 的 8 步标准人工审核候选，补齐 Issue、
  base commit、公开/隐藏测试、允许路径、许可证和固定镜像；在导入首批任务前不报告
  外部 Issue 修复率。

### 2026-09-12：证据路由与任务审核门禁收口

- 目标：让“普通常识”和“项目事实”走不同证据路线，并防止不完整的外部候选误入执行器。
- 修改范围：`apps/docs_troubleshoot/query_policy.py`、`apps/docs_troubleshoot/agent_runner.py`、
  `eval/software_task_review.py`、对应专项测试和评测说明。
- 核心结果：普通常识判为 `trivial`，不强制内部检索；项目 API、分页、CORS、Webhook、
  配置等事实判为 `standard`，必须检索并引用；带现场字段或根因/多服务要求的请求判为
  `complex`，获得更高工具预算。候选审核现在拒绝空数组、错误类型、无效 Issue URL，
  并要求人工提供可复核的版本、测试、路径、许可证、镜像和仓库簇信息。
- 验证结果：专项回归 `14 passed`；默认离线全量回归 `305 passed、6 skipped、13 deselected`。
- 明确边界：难度分类只控制流程预算，不证明回答正确；候选队列仍不是可执行任务，当前没有真实外部 Issue 回放结果。
- 下一动作：人工按八步标准补齐首批任务，执行固定 `base_commit` 的 baseline/candidate 对比。

## 最终判断标准

项目的下一阶段不是以模块数、测试数或文档数判断完成，而是回答以下问题：

> 在冻结的外部软件任务上，candidate 是否比真实 baseline 更可靠、更少返工、成本可控，
> 且没有新增回归、越权写入或安全副作用？

只有当任务来源、版本、验收器和最终状态均可追溯时，这个答案才进入简历和面试口径。
- 2026-09-13 首条真实公开 Issue 回放：`fastapi/fastapi#15764` 已导入正式任务集。基线 `e0f8cadf094bb4cb7a21e7757333d5dfbae46712` 的公开测试通过、隐藏测试失败；修复提交 `b78c82262f5170831ebd3f27873b09d8e579bac2` 的公开和隐藏测试均通过。Runner 使用固定 Docker 镜像和隔离参数，candidate 仅修改 `fastapi/routing.py`。任务集当前为 `active`，包含 1 条 `dev` 任务。该结果只证明单条外部任务可复现和验收，不代表 Agent 自动修复率或生产收益；结果文件见 `artifacts/software-tasks/runs/fastapi-15764-baseline.json`、`artifacts/software-tasks/runs/fastapi-15764-candidate.json`。
- 2026-09-13/14 三条 FastAPI 任务严格验收修订：补齐 `15764`/`15974` 独立 Agent run JSON；`16253` 保持 Agent/参考分离。Agent 成功率 **3/3=100%**（证据 `artifacts/software-tasks/runs/agent_success_rate_20260914.json`）。`SOFTWARE_TASK_DATASET.md` 已与清单对齐为 `active`、3 条任务。报告：`docs/reports/software_task_execution_20260913.md`。
- 2026-09-14 P0 失败回归编排：`examples/eval/run_failure_regression_pipeline.py` 强制依赖 `trace-debugger` + `llm-eval-engine`（缺失即失败）；CI 提前 clone/install 两仓，去掉 flywheel/StepWatcher 的 skip；文档见 `docs/FAILURE_REGRESSION_PIPELINE.md`。
- 2026-09-15 P1 默认挂载：`GitHubDeliveryWorkflow` / `SoftwareTaskRunner` 出口默认跑 `failure_regression_gate`（fail-closed）；共享模块 `src/react_agent/eval/failure_regression_gate.py`；测试 `tests/test_failure_regression_gate.py`。
- 2026-09-15 P2 强制复验：`evaluate_forced_reverify` / `run_gate_with_optional_repair`；Delivery 支持 `reverify_from` 与可选 `repair_loop`；hold 后未 improved_to_pass 不得成功。
- 2026-09-15 A1/A2：`repair_feedback/v1` 驱动修复；`baseline_scan` 跨 run 真对比（CI green/red）。
- 2026-09-15 A3–A5：`build_process_quality` 证据分 + ProcessReward fast（去 stub）；`tests/test_failure_regression_contracts.py`；答辩页 `docs/FAILURE_REGRESSION_PITCH.md`；`EVAL_API_VERSION` 对齐 0.2。
- 2026-09-15 SoftwareTask 门禁验收：`15764` / `15974` / `16253` 挂入同一条 `failure_regression_gate`；冻结 `baseline_scan` 下坏补丁 → `hold`、好 Agent → `pass`；复验剧本 hold → `reverify_from` → 仅 `improved_to_pass` 放行。脚本 `examples/eval/run_software_task_failure_regression.py`；CI + `tests/test_software_task_failure_regression.py` 禁止跳过。可写口径：**对齐工作流已在夹具 + 3 条 SoftwareTask 上复现**；不可写生产 SLA / Agent 自优化。总览 `artifacts/failure-regression/software-tasks/acceptance_summary.json`；答辩链见 `docs/FAILURE_REGRESSION_PITCH.md`。

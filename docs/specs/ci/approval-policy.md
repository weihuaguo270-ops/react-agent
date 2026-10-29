# CI 人工审批策略

## 1. 目的

本文定义机器风险评估完成后的人工审批要求。审批是合并前的独立控制层，不修改 CI、Harness 或 Evaluation 的测试语义。

## 2. 审批矩阵

| 风险等级 | 机器条件 | 最低审批要求 | 默认合并方式 |
|---|---|---|---|
| `low` | CI `pass`，无阻断发现 | 1 名维护者 | 可在审批满足后合并 |
| `medium` | CI `pass`，AI/安全无高危发现 | 相关模块 owner 1 名 | 通过 required checks 后合并 |
| `high` | CI `pass`，安全审核完成 | 模块 owner + 安全审核者各 1 名 | 禁止无人值守自动合并 |
| `critical` | CI `pass`，安全审核明确通过 | 2 名维护者，其中至少 1 名安全或仓库 owner | 默认禁止自动合并，需显式人工合并 |

以下情况不满足审批条件：机器结果为 `fail` 或 `blocked`、存在未处理的高危发现、required check 不是当前 head SHA 的结论，或 PR 处于冲突状态。

## 3. 审批有效性

- 每次新 commit 推送后，所有机器检查和人工审批都必须重新绑定当前 `head_sha`；
- 修改风险相关文件后，原有低风险审批自动失效；
- CODEOWNERS 决定模块 owner，不能由提交者自审；
- fork PR 不授予不可信代码写权限，也不能通过审批策略获取 Secret；
- 审批记录必须保留 reviewer、时间、head SHA、风险等级和依据。

## 4. 例外放行

例外只能用于非安全阻断或已知环境问题，必须记录：原因、影响、审批角色、适用 head SHA、到期时间和补救任务。Secret、Branch Protection、发布凭据和权限提升问题不得使用普通例外放行。

## 5. 与 GitHub Branch Protection 的关系

Branch Protection 至少要求：

1. 当前 head SHA 的唯一 CI 聚合检查；
2. 按风险等级配置的 required review 或 CODEOWNERS 审批；
3. 禁止管理员绕过保护规则的默认路径；
4. 合并前分支状态为无冲突且未过期。

风险聚合器可以生成审批建议和 required reviewer 集合，但最终审批仍由 GitHub 的受保护分支规则和真实维护者完成。

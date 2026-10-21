# 历史软件任务集

## 这次实现了什么

`SoftwareTask` 负责一条任务的执行约束；`SoftwareTaskDataset` 负责多条任务能否组成可比较的回放集。清单校验以下内容：任务字段是否完整、Issue 是否有公开来源和许可证、构建镜像是否固定、`golden/held_out` 是否有独立隐藏测试资产，以及同一仓库簇是否被错误地拆到不同切片。

校验器只读取清单，不联网、不克隆仓库、不启动 Docker。这样可以在获取外部代码前先发现数据泄漏、来源不明或无法复现的问题；真正执行仍由 `SoftwareTaskRunner` 完成。

## 当前产物和状态

清单位于 [`eval/software_task_dataset_manifest.json`](../eval/software_task_dataset_manifest.json)，当前状态为 **`active`**，包含 **3** 条 `dev` 任务（仓库簇均为 `fastapi/fastapi`）：

| task_id | base_commit | allowed_paths | hidden_test_asset |
|---------|-------------|---------------|-------------------|
| `fastapi-15764-apiroute-tags` | `e0f8cad…` | `fastapi/routing.py` | `fastapi-15764/test_route_tags.py` |
| `fastapi-15974-router-cache-race` | `7cb06f3…` | `fastapi/routing.py` | `fastapi-15974/test_included_router_concurrent_rebuild.py` |
| `fastapi-16253-docs-template-xss` | `4903347…` | `fastapi/openapi/docs.py` | `fastapi-16253/test_swagger_ui_escape.py` |

固定运行镜像：`react-agent-review-fastapi-15764:20260912e`。隐藏测试资产位于 `artifacts/software-tasks/hidden-assets/`；公开 review 资产位于 `artifacts/software-tasks/review/fastapi-XXXX/tests/`。

加载器会按 `task_id` 稳定排序，并通过 `content_hash()` 生成可记录的任务集哈希，供 baseline / Agent / reference 对比时确认使用的是同一批任务。

## 使用方式

```python
from react_agent.eval.software_task_dataset import load_software_task_dataset

dataset = load_software_task_dataset("eval/software_task_dataset_manifest.json")
print(dataset.status, dataset.split_counts(), dataset.content_hash())
```

回放执行示例（隔离 Docker Runner）：

```powershell
$env:PYTHONPATH = "src"
python artifacts/software-tasks/scripts/run_fastapi_task_evals.py fastapi-15764-apiroute-tags
python artifacts/software-tasks/scripts/run_fastapi_16253.py
```

## 数据从哪里导入

数据源应是人工审核后的公开记录，通常来自 GitHub REST/GraphQL 导出的 Issue、对应仓库的固定 commit，以及单独保存的公开/隐藏测试。也可以使用已有的 SWE-bench 类公开任务作为候选，但必须重新核对许可证、Issue 状态、基础 commit、测试可运行性和允许修改路径；不能直接把数据集名称当作项目已经完成的证据。

现有 `docs/snapshots/github_portfolio_dataset_*.json` 可以导出为审核队列，但它们只有仓库元数据。运行 `python scripts/export_github_task_candidates.py <snapshot> <review_queue.json>` 后，会为每个候选标注缺少的字段；队列记录不能直接交给 Runner，必须由人工补齐并转换成任务记录。

### 候选筛选标准

候选不是按标题或仓库热度挑选，而是按能否复现、能否验收、能否比较来挑选。每条候选按下面顺序审核：

1. **确认问题真实存在。** 打开公开 Issue 原文，记录 URL、创建时间、当前状态和讨论中的验收描述；关闭后已有修复、重复问题、只有提问没有验收条件的 Issue 退回。
2. **冻结修复前版本。** 从 Issue 关联的 Pull Request、提交记录或发布版本中确定 `base_commit`，用 Git 检出并记录完整提交哈希。不能用当前主分支代替，因为主分支可能已经包含修复。
3. **把“应该改成什么”写成验收条件。** 将 Issue 中的行为要求改写为 `acceptance_criteria`，每条都必须能被测试或人工复核；无法转成可判定条件的候选不进入正式集。
4. **准备公开测试和隐藏测试。** `test_command` 用于检查基础可运行性；`hidden_test_command` 配合工作区外的 `hidden_test_asset` 检查 Issue 没有直接展示的边界。隐藏测试必须独立保存，不能只是公开测试的复制品；Runner 只读挂载它，不把它复制到 Agent 工作区。
5. **限制修改范围。** 根据预期补丁填写 `allowed_paths`，至少精确到目录或文件，不能填整个仓库。Runner 会在执行后比较变更路径，越界即失败。
6. **固定运行环境。** 在 `runtime_image` 中写明 Docker 镜像，在 `build.install` 中写明依赖安装命令；构建失败、依赖无法获得或必须访问未公开服务的候选退回。
7. **确认来源和拆分。** 记录上游许可证、贡献指南、Issue 快照和 `provenance_url`，并为仓库填写唯一 `repository_cluster`。同一仓库簇不能同时出现在 `dev`、`golden` 和 `held_out`，防止测试泄漏。
8. **先门禁、后导入。** 运行 `review_candidate` 检查字段、URL 和提交标识，再运行导入器的完整 Schema、隐藏测试和 split 校验。任何缺失项都保留在审核队列，不允许模型猜值。

### 缺失字段如何补齐

`issue_url` 和 `provenance_url` 从公开 Issue 页面和仓库快照记录；`base_commit` 从 Issue 关联的修复提交之前选择，并用 Git 检出验证；`test_command` 和 `hidden_test_command` 从仓库测试或人工编写的独立补丁中取得，隐藏文件保存到 Agent 工作区之外并在 `hidden_test_asset` 中记录相对路径；`allowed_paths` 根据最终允许修改的文件范围填写；`license_confirmation` 由仓库许可证文件和来源记录确认；`runtime_image` 选择固定版本的 Python/Docker 基础镜像；`repository_cluster` 使用仓库的稳定标识，多个任务共享同一仓库簇但不能跨 split。

补齐过程必须保存原始 Issue、commit、测试文件、镜像构建日志和审核人/日期。人工只能补充原文中能验证的内容，不能根据标题推断测试或验收条件。若任何一项无法独立复核，候选状态保持 `needs_manual_issue_review`，不进入 Runner。

将审核后的任务记录保存为 JSON 数组或 JSONL，每条记录包含单条 `SoftwareTask` 字段以及 `repository_cluster`、`source`、`build` 三组字段，然后运行：

```powershell
$env:PYTHONPATH = "src"
python scripts/import_software_task_dataset.py reviewed_tasks.jsonl eval/software_task_dataset_manifest.json
```

导入阶段只读本地文件并执行完整校验，不自动联网或克隆代码。导入成功后才会把清单标记为 `active`；下载仓库、构建 Docker 镜像和运行公开/隐藏测试仍是后续回放步骤。

## 评测口径

- **参考补丁结果**与 **Agent 补丁结果**必须分文件保存（`*-reference.json` / `*-agent.json`），不得混称为“candidate 通过”。
- 只有三条任务都具备独立 `*-agent.json` 且 `status=succeeded` 时，才可计算 Agent 修复成功率。
- 当前 2026-09-13/14 回放见 [`docs/reports/software_task_execution_20260913.md`](./reports/software_task_execution_20260913.md)。

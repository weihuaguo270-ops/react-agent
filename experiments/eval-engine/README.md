# Eval Engine — 自适应 Process Reward 评估引擎

## 背景

**handwritten-react-agent** 已有轻量 `src/eval/` 模块（关键词匹配 + 静态评分），
适用于功能测试场景。但生产级 Agent 需要更智能的评估能力：

- 不再用固定模板评分，而是**动态生成评分标准**
- 不再只看最终答案，而是**逐步骤 Process Reward 评分**
- 不再单向反馈，而是**自适应 Eval Loop**（低分 → 修正 → 重试 → 再评）

## 核心创新

### 1. 意图自动路由

```
用户输入 → IntentClassifier → "测试工具" → 单次执行，返回用户
                            → "写一份报告" → 进入 Eval Loop
```

无需人工指定模式，系统自动判断。

### 2. 动态评分标准生成（Dynamic Rubric）

传统 Eval：对所有用例用同一份模板打分
本方案：对每步的实际上下文，动态生成针对性的评分标准

```
Step 3（调用了 web_search 搜索 "Python SQL注入"）
→ 动态标准：
  ① 搜索词是否合理？
  ② 搜索结果是否被后续利用？
  ③ 搜索效果不好时，Agent 是否有备选方案？
```

### 3. Process Reward 步骤级评分

受 o1/o3 Process Reward Model 启发——不只看最终答案，对每一步单独评分。

```
Step 1: 搜索 (score: 0.92 ✅)
Step 2: 读结果 (score: 0.85 ✅)
Step 3: 调用 review_tool (score: 0.40 ❌ — 参数错误)
Step 4: 总结 (score: 0.60 ❌ — 基于不完整数据)
         ↑ 错误传播：Step 3 失败 → Step 4 受影响
```

### 4. 自适应 Eval Loop

```
Agent 执行 → 评分 → 全部达标 → 输出结果
                  → 有低分项 → 打包修正指令 → LLM 重试 → 再次评分
                              → 最多 3 次，检测震荡自动停止
```

## 架构

```
experiments/eval-engine/
│
├── core/                          手写核心
│   ├── contract.py                Verifier 契约接口
│   ├── trajectory_parser.py       轨迹 → DAG 步骤结构
│   ├── dynamic_rubric.py          ★ 动态评分标准生成
│   └── process_reward.py          ★ Process Reward 评分 + 错误传播
│
├── intent/                        意图分类
│   └── classifier.py              正则 + LLM 降级判断
│
├── judge/                         Judge 系统
│   ├── executor.py                Judge LLM 调用封装
│   └── calibration.py             Judge 校准
│
├── loop/                          Eval Loop 引擎
│   ├── eval_loop.py               ★ 自适应循环
│   └── fix_packer.py              修正指令打包
│
├── gates/                         回归门禁
│   ├── regression_gate.py         PR/部署前检测
│   └── baseline.py                Baseline 管理
│
├── observability/                 可观测性
│   └── report.py                  报告生成
│
├── dataset/                       测试集管理
│
└── tests/                         测试
    ├── test_core.py               核心模块测试
    └── test_process_reward.py     Process Reward 集成测试
```

## 与 `src/eval/` 的分工

| 场景 | 用谁 |
|---|---|
| 快速测试工具是否正常 | `src/eval/`（关键词匹配，快） |
| 验证新功能是否引入 regression | `src/eval/`（静态指标，稳定） |
| 写报告时自动逐步骤质量评估 | **eval-engine**（语义评分，深） |
| 生成式任务的自适应迭代 | **eval-engine**（Eval Loop） |
| CI/CD 回归门禁 | **eval-engine**（对比 baseline） |

## 使用方式

```python
# 初始化引擎
from loop.eval_loop import EvalLoopEngine

engine = EvalLoopEngine(
    agent_fn=run_agent,      # Agent 执行函数
    judge_fn=call_judge_llm, # Judge LLM 调用函数
)

# 执行（自动判断意图）
result = engine.execute("帮我写一份 AI 行业分析报告")

if result.passed:
    print(result.final_output)
else:
    print(f"质量未达标（总分 {result.report.overall_score}）")
    print(result.error_analysis)
```

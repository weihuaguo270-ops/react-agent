"""integration — 将 eval-engine 嵌入 Agent 实际运行流程

核心文件：
  agent_wrapper.py — 权限拦截 + 自动 Eval 触发

自动触发条件：
  ┌─────────────────────────────────────────────────────┐
  │  Agent 执行完成                                      │
  │       │                                              │
  │       ▼                                              │
  │  IntentClassifier                                    │
  │       │                                              │
  │  ┌────┴──────────────┐                              │
  │  │ functional_test   │ generative_task               │
  │  │ (测试工具/功能)    │ (写报告/分析/代码生成)        │
  │  └────┬──────────────┘                              │
  │       │                      │                       │
  │       ▼                      ▼                       │
  │  直接返回用户         自动触发 Eval Loop              │
  │                        │                             │
  │                   ┌────┴────┐                       │
  │                  全部达标   有低分项                  │
  │                   │         │                        │
  │                   ▼         ▼                        │
  │               返回结果 → 问用户 → 修正 → 重试        │
  └─────────────────────────────────────────────────────┘

使用方式：
  from experiments.eval-engine.integration.agent_wrapper import (
      PermissionWrapper,          # 工具调用权限拦截
      AutoEvalWrapper,            # 自动 Eval 触发
      create_guarded_agent,       # 一站式工厂函数
  )
"""

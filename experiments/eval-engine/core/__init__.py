"""core — 手写核心模块

包含以下模块（均不依赖外部框架）：
  - contract.py:            Verifier 契约接口定义
  - trajectory_parser.py:   轨迹 → DAG 步骤结构
  - dynamic_rubric.py:      动态评分标准生成（核心创新）
  - process_reward.py:      步骤级 Process Reward 评分（核心创新）
  - error_propagation.py:   错误传播追踪 + 根因定位
"""

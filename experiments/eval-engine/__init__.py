"""eval-engine — 自适应 Process Reward Eval 引擎

Agent 执行质量评估系统，核心思路：
  1. 自动分类任务意图（测试类→返回用户 / 生成类→进入 Eval Loop）
  2. 动态生成评分标准（不是固定模板）
  3. Process Reward 步骤级评分
  4. 低分项自动打包为修正指令，驱动 Agent 自愈
"""

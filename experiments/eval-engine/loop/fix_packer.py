"""fix_packer — 将低分项打包为结构化修正指令

供 Eval Loop 在检测到低分步骤时使用。
将 ProcessRewardReport 中的失败步骤转为 LLM 能理解的修正反馈。
"""

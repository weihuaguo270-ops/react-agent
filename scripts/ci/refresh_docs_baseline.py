#!/usr/bin/env python3
"""自动刷新文档基线（如果需要）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from react_agent.apps.docs_troubleshoot.eval_git_docs import refresh_corpus_baseline


def main():
    """主函数。"""
    baseline_path = ROOT / "src/react_agent/apps/docs_troubleshoot/git_docs_corpus_baseline.json"

    # 读取当前基线
    original_baseline = baseline_path.read_text()

    # 刷新基线
    try:
        refresh_corpus_baseline()
        print("✓ Baseline refreshed successfully")
    except Exception as e:
        print(f"✗ Failed to refresh baseline: {e}")
        sys.exit(1)

    # 检查是否有变化
    new_baseline = baseline_path.read_text()

    if original_baseline != new_baseline:
        print("✓ Baseline was updated")
        # 输出变化的文件数
        original = json.loads(original_baseline)
        new = json.loads(new_baseline)
        added = set(new['files'].keys()) - set(original['files'].keys())
        removed = set(original['files'].keys()) - set(new['files'].keys())
        changed = {k for k in set(original['files'].keys()) & set(new['files'].keys())
                   if original['files'][k] != new['files'][k]}

        if added:
            print(f"  Added: {len(added)} files")
        if removed:
            print(f"  Removed: {len(removed)} files")
        if changed:
            print(f"  Changed: {len(changed)} files")
    else:
        print("✓ Baseline unchanged")


if __name__ == '__main__':
    main()

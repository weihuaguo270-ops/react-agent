"""baseline — Baseline 管理

Baseline 是 Agent 质量的"历史参考线"——记录了上一次（或最佳）评估的结果。
每次修改 prompt/tool/model 后，需要：
  1. 跑一次完整评估
  2. 对比 baseline
  3. 如果质量下降超过阈值 → 阻塞合并/触发告警

数据格式：
    baselines/{timestamp}_baseline.json
    {
        "timestamp": "2026-07-10T10:00:00",
        "git_commit": "abc123",         # 可选：记录当时的代码版本
        "summary": {
            "overall_score": 4.2,
            "pass_rate": 0.85,
            "num_cases": 100,
            "failed_cases": 15,
        },
        "by_category": {
            "rag": {"overall_score": 4.0, "num_cases": 20, ...},
            "tool": {"overall_score": 4.8, ...},
        },
        "per_case_scores": [
            {"id": "rag_001", "score": 4.5, "passed": true},
            ...
        ],
    }
"""

from __future__ import annotations
import json
import os
import glob
import time
from typing import Any, Optional


DEFAULT_BASELINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gates",
    "baselines",
)


class BaselineManager:
    """Baseline 管理器

    用法：
        bm = BaselineManager()
        bm.save(current_report)           # 保存当前结果为新 baseline
        diff = bm.compare(current_report)  # 对比最新 baseline
        if diff["regression_detected"]:
            print(f"质量下降: {diff['score_diff']}")
    """

    def __init__(self, baseline_dir: Optional[str] = None):
        self.baseline_dir = baseline_dir or DEFAULT_BASELINE_DIR
        os.makedirs(self.baseline_dir, exist_ok=True)

    def save(self, report: dict) -> str:
        """保存当前评测结果为一个 baseline

        参数:
            report: 评测报告（与 report.py 的 report_to_json 输出兼容）

        返回:
            str: 保存的文件路径
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # 尝试获取 git commit
        git_commit = ""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(self.baseline_dir),
            )
            if result.returncode == 0:
                git_commit = result.stdout.strip()
        except Exception:
            pass

        baseline = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "baseline_id": f"baseline_{timestamp}",
            "git_commit": git_commit,
            "summary": {
                "overall_score": report.get("overall_score", 0),
                "pass_rate": report.get("summary", {}).get("pass_rate", 0),
                "num_cases": report.get("summary", {}).get("num_steps", 0),
                "num_failed": report.get("summary", {}).get("num_failed_steps", 0),
            },
            "by_category": report.get("by_category", {}),
        }

        filename = f"{timestamp}_baseline.json"
        filepath = os.path.join(self.baseline_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        return filepath

    def load_latest(self) -> Optional[dict]:
        """加载最新的 baseline

        返回:
            dict or None（如果没有 baseline）
        """
        baselines = self.list_baselines()
        if not baselines:
            return None
        latest = baselines[0]  # list_baselines 已按时间倒序
        filepath = latest["filepath"]
        try:
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def compare(self, current_report: dict) -> dict[str, Any]:
        """对比当前结果与最新 baseline

        参数:
            current_report: 当前评测结果

        返回:
            {
                "baseline_found": bool,
                "regression_detected": bool,
                "score_diff": float,
                "pass_rate_diff": float,
                "regression_gate_threshold": 0.1,
            }
        """
        baseline = self.load_latest()
        if not baseline:
            return {
                "baseline_found": False,
                "regression_detected": False,
                "message": "没有 baseline，跳过对比",
            }

        old_score = baseline.get("summary", {}).get("overall_score", 0)
        new_score = current_report.get("overall_score", 0)
        score_diff = new_score - old_score

        old_pass = baseline.get("summary", {}).get("pass_rate", 0)
        new_pass = current_report.get("summary", {}).get("pass_rate", 0)
        pass_diff = new_pass - old_pass

        threshold = 0.1
        regression = score_diff < -threshold

        return {
            "baseline_found": True,
            "regression_detected": regression,
            "score_diff": round(score_diff, 3),
            "pass_rate_diff": round(pass_diff, 3),
            "old_score": old_score,
            "new_score": new_score,
            "regression_gate_threshold": threshold,
            "message": (
                f"质量{'下降' if regression else '稳定/提升'}: "
                f"{new_score:.3f} vs {old_score:.3f} "
                f"({'+' if score_diff > 0 else ''}{score_diff:.3f})"
            ),
        }

    def list_baselines(self, limit: int = 20) -> list[dict]:
        """列出所有 baseline

        返回:
            按时间倒序排列的 baseline 摘要列表
        """
        pattern = os.path.join(self.baseline_dir, "*_baseline.json")
        files = sorted(glob.glob(pattern), reverse=True)[:limit]

        result = []
        for f in files:
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                result.append({
                    "baseline_id": data.get("baseline_id", ""),
                    "timestamp": data.get("timestamp", ""),
                    "git_commit": data.get("git_commit", ""),
                    "overall_score": data.get("summary", {}).get("overall_score", 0),
                    "pass_rate": data.get("summary", {}).get("pass_rate", 0),
                    "filepath": f,
                })
            except (json.JSONDecodeError, OSError):
                continue
        return result

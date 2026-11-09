"""Offline demo for the work-assistant规范咨询闭环 (no API Key)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

os.environ["REACT_AGENT_APP"] = "docs_troubleshoot"
os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")

from react_agent.apps.docs_troubleshoot.agent_runner import run_docs_agent
from react_agent.apps.docs_troubleshoot.eval_golden import run_golden_eval
from react_agent.apps.docs_troubleshoot.index import reset_index
from react_agent.harness import Replay
from react_agent.harness.recorder import TRAJECTORY_DIR


def _run_case(label: str, query: str) -> None:
    result = run_docs_agent({"query": query})
    trajectory_path = Path(TRAJECTORY_DIR) / f"traj_{result.trajectory_id}.json"
    actions = [step.get("action") for step in result.agent_steps]
    citations = [item.get("source") for item in result.citations]

    print(f"[{label}] 员工提问: {query}")
    print(f"  检索/校验动作: {actions or ['refusal_without_retrieval']}")
    print(f"  refused={result.refused} policy={result.state.get('policy')}")
    print(f"  citations={citations or []}")
    print(f"  answer={result.answer[:220]}")
    print("  权限边界: 规范咨询为只读路径，无需人工审批；副作用修复步骤仍受 permission_gate / approval 控制。")
    print(f"  trajectory_id={result.trajectory_id} saved={trajectory_path.exists()} path={trajectory_path}")

    if trajectory_path.is_file():
        print("  replay:")
        Replay().play(str(trajectory_path))
    print()


def main():
    reset_index()
    print("=== 企业内部工作助手：规范咨询闭环（offline） ===\n")
    _run_case("引用回答", "缺少 Authorization 返回什么？")
    _run_case("无依据拒答", "我们公司股价明天多少？")

    report = run_golden_eval()
    print(
        f"Golden eval: {report['passed']}/{report['total']} "
        f"(pass_rate={report['pass_rate']})"
    )
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()

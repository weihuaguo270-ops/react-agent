"""public_rag_benchmark — 公开 RAG/Agent 子集（分层：smoke / hard / held_out）

外部可比性协议（冻结子集，非全量榜）：
  - smoke: 协议冒烟（易；禁止单独当能力宣传）
  - hard: 强干扰 + 更严 recall（参考信号）
  - held_out: 设计后冻结，不对它调参

指标：answer match · retrieval recall@k · faithfulness

模式：
  - offline: 指标夹具（CI）
  - rag: 真检索 + 抽取 reader
  - rag_topk1 / rag_no_context / rag_distractors_only: 对照跌落
  - agent: contexts 注入 prompt（需 API Key）
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from react_agent.eval.execution_scorer import wilson_ci
from react_agent.eval.public_benchmark import match_gold, normalize_text

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PUBLIC_RAG = os.path.join(_EVAL_DIR, "public_rag_benchmark_subset.json")


def load_public_rag_benchmark(path: Optional[str] = None) -> dict[str, Any]:
    """加载冻结的 HotpotQA RAG 子集并校验顶层用例结构。"""
    filepath = path or DEFAULT_PUBLIC_RAG
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"public rag benchmark must be object with cases[]: {filepath}")
    return data


def retrieval_recall(
    retrieved_sources: list[str],
    supporting_ids: list[str],
) -> float:
    """按支持事实标识计算检索召回，不评价生成答案质量。"""
    if not supporting_ids:
        return 1.0
    got = {normalize_text(s) for s in retrieved_sources if s}
    need = {normalize_text(s) for s in supporting_ids if s}
    if not need:
        return 1.0
    hit = sum(1 for s in need if s in got)
    return round(hit / len(need), 3)


def faithfulness_grounded(answer: str, retrieved_texts: list[str], gold: str) -> bool:
    """Rule-based RAGAS-style proxy: gold must be grounded in retrieved context."""
    blob = normalize_text(" ".join(retrieved_texts or []))
    if not blob:
        return False
    g = normalize_text(gold)
    a = normalize_text(answer)
    if g and g in blob:
        return True
    toks = [t for t in re.split(r"\W+", g) if len(t) > 2]
    if toks and all(t in blob for t in toks):
        return True
    if a and len(a) >= 3 and a in blob:
        return True
    return False


def build_ephemeral_index(contexts: list[dict[str, Any]]):
    """为单个用例构建临时索引，避免跨用例语料污染。"""
    os.environ.setdefault("REACT_AGENT_RAG_MODE", "keyword")
    from react_agent.rag import RAG

    tmp = tempfile.mkdtemp(prefix="rag_bench_")
    rag = RAG(save_path=os.path.join(tmp, "index.json"))
    rag.clear()
    for ctx in contexts:
        cid = str(ctx.get("id") or ctx.get("title") or "ctx")
        title = str(ctx.get("title") or "")
        text = str(ctx.get("text") or "")
        body = f"# {title}\n\n{text}" if title else text
        rag.ingest_text(body, source=cid)
    return rag


def _case_top_k(case: dict[str, Any], bundle_defaults: dict[str, Any], override: Optional[int]) -> int:
    if override is not None:
        return int(override)
    if case.get("top_k") is not None:
        return int(case["top_k"])
    tier = case.get("tier") or "smoke"
    if tier in ("hard", "held_out"):
        return int(bundle_defaults.get("hard_top_k") or 2)
    return int(bundle_defaults.get("top_k") or 3)


def _case_min_recall(
    case: dict[str, Any], bundle_defaults: dict[str, Any], override: Optional[float]
) -> float:
    if override is not None:
        return float(override)
    if case.get("min_retrieval_recall") is not None:
        return float(case["min_retrieval_recall"])
    tier = case.get("tier") or "smoke"
    if tier in ("hard", "held_out"):
        return float(bundle_defaults.get("hard_min_retrieval_recall") or 1.0)
    return float(bundle_defaults.get("min_retrieval_recall") or 0.5)


def retrieve_for_case(
    case: dict[str, Any],
    *,
    top_k: int = 3,
    context_filter: str = "all",
) -> list[dict[str, Any]]:
    """在用例独立索引中检索，支持无上下文和干扰项对照。"""
    contexts = list(case.get("contexts") or [])
    if context_filter == "distractors_only":
        contexts = [c for c in contexts if not c.get("is_supporting")]
    elif context_filter == "none":
        return []
    if not contexts:
        return []
    rag = build_ephemeral_index(contexts)
    return rag.query(str(case.get("question") or ""), top_k=top_k)


def extractive_rag_answer(
    case: dict[str, Any],
    hits: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Deterministic reader (not LLM):
    - Emit gold only if gold is grounded in *retrieved* text AND at least one
      supporting id is cited among hits when supporting_ids exist.
    - Otherwise refuse. Hard tiers with noisy distractors should often fail.
    """
    gold = str(case.get("gold_answer") or "")
    texts = [str(h.get("content") or "") for h in hits]
    sources = [str(h.get("source") or "") for h in hits]
    supporting = {normalize_text(s) for s in (case.get("supporting_ids") or [])}
    grounded = faithfulness_grounded(gold, texts, gold)
    has_support_hit = (not supporting) or any(
        normalize_text(s) in supporting for s in sources
    )
    if grounded and hits and has_support_hit:
        cite = sources[0]
        for s in sources:
            if normalize_text(s) in supporting:
                cite = s
                break
        return {
            "answer": f"{gold} [source: {cite}]",
            "refused": False,
            "cited": cite,
            "grounded": True,
        }
    return {
        "answer": "insufficient evidence in retrieved context",
        "refused": True,
        "cited": "",
        "grounded": False,
    }


def score_rag_case(
    case: dict[str, Any],
    *,
    hits: list[dict[str, Any]],
    answer: str,
    mode: str,
    min_recall: float = 0.5,
) -> dict[str, Any]:
    """联合答案匹配、检索召回和忠实度代理指标判定通过。"""
    bench = str(case.get("benchmark") or "hotpotqa_rag")
    gold = str(case.get("gold_answer") or "")
    supporting = list(case.get("supporting_ids") or [])
    sources = [str(h.get("source") or "") for h in hits]
    texts = [str(h.get("content") or "") for h in hits]

    ans_ok, ans_reason = match_gold(answer, gold, "hotpotqa")
    recall = retrieval_recall(sources, supporting)
    faithful = faithfulness_grounded(answer if ans_ok else gold, texts, gold)
    passed = bool(ans_ok and recall >= min_recall and faithful)

    fail = []
    if not ans_ok:
        fail.append("answer")
    if recall < min_recall:
        fail.append("retrieval_recall")
    if not faithful:
        fail.append("faithfulness")

    return {
        "id": case.get("id"),
        "benchmark": bench,
        "tier": case.get("tier") or "smoke",
        "tags": list(case.get("tags") or []),
        "difficulty": case.get("difficulty") or "unspecified",
        "mode": mode,
        "passed": passed,
        "answer_ok": ans_ok,
        "answer_reason": ans_reason,
        "retrieval_recall": recall,
        "faithfulness": faithful,
        "min_retrieval_recall": min_recall,
        "retrieved_sources": sources,
        "supporting_ids": supporting,
        "gold_answer": gold,
        "prediction_preview": (answer or "")[:300],
        "fail_reason": ",".join(fail),
        "reason": "ok" if passed else ",".join(fail) or ans_reason,
    }


def score_offline_fixture(case: dict[str, Any], *, min_recall: float) -> dict[str, Any]:
    """用 Gold 构造链路自检结果，不代表真实模型执行。"""
    supporting = list(case.get("supporting_ids") or [])
    hits = []
    for sid in supporting:
        text = next(
            (c.get("text") for c in (case.get("contexts") or []) if c.get("id") == sid),
            "",
        )
        content = str(text)
        if normalize_text(str(case.get("gold_answer") or "")) not in normalize_text(content):
            content = f"{content} {case.get('gold_answer')}"
        hits.append({"source": sid, "content": content})
    answer = f"{case.get('gold_answer')} [source: {supporting[0] if supporting else 'ctx'}]"
    return score_rag_case(
        case, hits=hits, answer=answer, mode="offline", min_recall=min_recall
    )


def run_rag_mode_case(
    case: dict[str, Any],
    *,
    top_k: int,
    min_recall: float,
    mode: str = "rag",
    context_filter: str = "all",
) -> dict[str, Any]:
    """运行真实检索加确定性 reader，隔离检索质量与模型能力。"""
    hits = retrieve_for_case(case, top_k=top_k, context_filter=context_filter)
    out = extractive_rag_answer(case, hits)
    row = score_rag_case(
        case,
        hits=hits,
        answer=out["answer"],
        mode=mode,
        min_recall=min_recall,
    )
    row["refused"] = out.get("refused")
    row["cited"] = out.get("cited")
    row["top_k"] = top_k
    row["context_filter"] = context_filter
    return row


def run_agent_mode_case(
    case: dict[str, Any],
    *,
    min_recall: float,
    agent_runner=None,
) -> dict[str, Any]:
    """运行完整 Agent，并记录终答、引用和工具轨迹证据。"""
    import time

    from react_agent.eval.execution_scorer import _final_answer_text
    from react_agent.eval.runner import run_single_case

    contexts = list(case.get("contexts") or [])
    packed = "\n\n".join(
        f"[{c.get('id')}] {c.get('title')}: {c.get('text')}" for c in contexts
    )
    prompt = (
        "Answer using ONLY the provided contexts. "
        "Cite a context id like [source: ctx_xxx]. "
        "If insufficient, say insufficient evidence.\n\n"
        f"CONTEXTS:\n{packed}\n\nQUESTION:\n{case.get('question')}\n\n"
        "End with FINAL ANSWER."
    )
    runner = agent_runner or run_single_case
    t0 = time.time()
    stdout, trajectory, exit_code, duration = runner(
        prompt,
        timeout=int(case.get("timeout") or 120),
        max_steps=case.get("max_steps") or 8,
    )
    if not duration:
        duration = round(time.time() - t0, 3)
    text = _final_answer_text(stdout or "", trajectory)
    hits = [
        {"source": c.get("id"), "content": c.get("text")}
        for c in contexts
        if c.get("is_supporting")
    ] or [{"source": c.get("id"), "content": c.get("text")} for c in contexts]
    row = score_rag_case(
        case, hits=hits, answer=text, mode="agent", min_recall=min_recall
    )
    row["duration_seconds"] = duration
    row["exit_code"] = exit_code
    return row


def _rate_map(d: dict) -> dict:
    return {
        k: {
            **v,
            "pass_rate": round(100.0 * v["passed"] / v["total"], 1) if v["total"] else 0.0,
        }
        for k, v in sorted(d.items())
    }


def _bucket_results(results: list[dict]) -> tuple[dict, dict, dict]:
    by_bench: dict[str, dict] = defaultdict(lambda: {"passed": 0, "total": 0})
    by_mode: dict[str, dict] = defaultdict(lambda: {"passed": 0, "total": 0})
    by_tier: dict[str, dict] = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        b = str(r.get("benchmark") or "unknown")
        m = str(r.get("mode") or "unknown")
        t = str(r.get("tier") or "smoke")
        for bucket, key in ((by_bench, b), (by_mode, m), (by_tier, t)):
            bucket[key]["total"] += 1
            if r.get("passed"):
                bucket[key]["passed"] += 1
    return _rate_map(by_bench), _rate_map(by_mode), _rate_map(by_tier)


def run_public_rag_benchmark(
    path: Optional[str] = None,
    *,
    modes: Optional[list[str]] = None,
    benchmarks: Optional[list[str]] = None,
    tiers: Optional[list[str]] = None,
    only_ids: Optional[set[str]] = None,
    limit: Optional[int] = None,
    top_k: Optional[int] = None,
    min_recall: Optional[float] = None,
    agent_runner=None,
    include_controls: bool = True,
) -> dict[str, Any]:
    """
    Default modes: offline + rag on all selected tiers, plus control drop-offs on hard.
    """
    wanted = set(modes or ["offline", "rag"])
    bundle = load_public_rag_benchmark(path)
    defaults = bundle.get("defaults") or {}

    cases = list(bundle.get("cases") or [])
    if benchmarks:
        bset = set(benchmarks)
        cases = [c for c in cases if c.get("benchmark") in bset]
    if tiers:
        tset = set(tiers)
        cases = [c for c in cases if (c.get("tier") or "smoke") in tset]
    if only_ids:
        cases = [c for c in cases if str(c.get("id")) in only_ids]
    if limit is not None:
        cases = cases[: int(limit)]

    results: list[dict] = []
    for case in cases:
        ck = _case_top_k(case, defaults, top_k)
        mr = _case_min_recall(case, defaults, min_recall)
        if "offline" in wanted:
            results.append(score_offline_fixture(case, min_recall=mr))
        if "rag" in wanted:
            results.append(
                run_rag_mode_case(case, top_k=ck, min_recall=mr, mode="rag")
            )
        if "rag_topk1" in wanted:
            results.append(
                run_rag_mode_case(
                    case, top_k=1, min_recall=mr, mode="rag_topk1"
                )
            )
        if "rag_no_context" in wanted:
            results.append(
                run_rag_mode_case(
                    case,
                    top_k=ck,
                    min_recall=mr,
                    mode="rag_no_context",
                    context_filter="none",
                )
            )
        if "rag_distractors_only" in wanted:
            results.append(
                run_rag_mode_case(
                    case,
                    top_k=ck,
                    min_recall=mr,
                    mode="rag_distractors_only",
                    context_filter="distractors_only",
                )
            )
        if "agent" in wanted:
            results.append(
                run_agent_mode_case(
                    case, min_recall=mr, agent_runner=agent_runner
                )
            )

    # Automatic controls on hard+held_out when running default rag (drop-off evidence)
    control_results: list[dict] = []
    if include_controls and "rag" in wanted:
        for case in cases:
            if (case.get("tier") or "smoke") not in ("hard", "held_out"):
                continue
            ck = _case_top_k(case, defaults, top_k)
            mr = _case_min_recall(case, defaults, min_recall)
            for mode, filt, tk in (
                ("control_no_context", "none", ck),
                ("control_distractors_only", "distractors_only", ck),
                ("control_topk1", "all", 1),
            ):
                control_results.append(
                    run_rag_mode_case(
                        case,
                        top_k=tk,
                        min_recall=mr,
                        mode=mode,
                        context_filter=filt,
                    )
                )

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    rate = round(100.0 * passed / total, 1) if total else 0.0
    by_bench, by_mode, by_tier = _bucket_results(results)

    metric_sum = {"answer_ok": 0, "faithfulness": 0, "recall": 0.0}
    for r in results:
        if r.get("answer_ok"):
            metric_sum["answer_ok"] += 1
        if r.get("faithfulness"):
            metric_sum["faithfulness"] += 1
        metric_sum["recall"] += float(r.get("retrieval_recall") or 0)
    avg_recall = round(metric_sum["recall"] / total, 3) if total else 0.0

    # Drop-off: hard rag pass_rate vs controls
    def _mode_rate(rows: list[dict], mode: str, tier: Optional[str] = None) -> dict:
        sub = [
            r
            for r in rows
            if r.get("mode") == mode
            and (tier is None or r.get("tier") == tier)
        ]
        t = len(sub)
        p = sum(1 for r in sub if r.get("passed"))
        return {
            "passed": p,
            "total": t,
            "pass_rate": round(100.0 * p / t, 1) if t else 0.0,
        }

    dropoff = {
        "hard_rag": _mode_rate(results, "rag", "hard"),
        "held_out_rag": _mode_rate(results, "rag", "held_out"),
        "smoke_rag": _mode_rate(results, "rag", "smoke"),
        "hard_control_no_context": _mode_rate(
            control_results, "control_no_context", "hard"
        ),
        "hard_control_distractors_only": _mode_rate(
            control_results, "control_distractors_only", "hard"
        ),
        "hard_control_topk1": _mode_rate(control_results, "control_topk1", "hard"),
    }

    smoke_rate = (by_tier.get("smoke") or {}).get("pass_rate", 0)
    hard_rate = (by_tier.get("hard") or {}).get("pass_rate", 0)
    held_rate = (by_tier.get("held_out") or {}).get("pass_rate", 0)

    honesty = dict(bundle.get("honesty") or {})
    honesty["live_reading"] = (
        f"by_tier smoke={smoke_rate}% hard={hard_rate}% held_out={held_rate}%. "
        "Cite hard/held_out (+ drop-off controls), never smoke alone."
    )

    return {
        "report_id": f"public_rag_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": os.path.basename(path or DEFAULT_PUBLIC_RAG),
        "bundle_name": bundle.get("name"),
        "bundle_version": bundle.get("version"),
        "protocol": bundle.get("protocol"),
        "inspired_by": bundle.get("inspired_by"),
        "honesty": honesty,
        "modes": sorted(wanted),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": rate,
            "pass_rate_wilson_95": wilson_ci(passed, total),
            "answer_ok_rate": round(100.0 * metric_sum["answer_ok"] / total, 1)
            if total
            else 0.0,
            "faithfulness_rate": round(
                100.0 * metric_sum["faithfulness"] / total, 1
            )
            if total
            else 0.0,
            "avg_retrieval_recall": avg_recall,
            "honesty": (
                "分层子集：smoke=协议冒烟（勿单独宣传）；"
                "hard/held_out=参考信号；controls=跌落对照。非全量榜。"
            ),
        },
        "by_benchmark": by_bench,
        "by_mode": by_mode,
        "by_tier": by_tier,
        "dropoff_controls": dropoff,
        "license_notes": bundle.get("license_notes"),
        "results": results,
        "control_results": control_results,
    }


def report_to_markdown(report: dict, *, title: Optional[str] = None) -> str:
    """渲染分模式 RAG 指标，并保留证据等级说明。"""
    s = report.get("summary") or {}
    title = title or f"公开 RAG/Agent benchmark（{report.get('report_id', '')}）"
    wilson = s.get("pass_rate_wilson_95") or {}
    lines = [
        f"# {title}",
        "",
        f"- **report_id:** `{report.get('report_id', '')}`",
        f"- **protocol:** `{report.get('protocol', '')}`",
        f"- **bundle:** `{report.get('bundle_name', '')}` v`{report.get('bundle_version', '')}`",
        f"- **dataset:** `{report.get('dataset', '')}`",
        f"- **modes:** {', '.join(f'`{m}`' for m in (report.get('modes') or []))}",
        f"- **总通过率:** {s.get('passed', 0)}/{s.get('total', 0)}（{s.get('pass_rate', 0)}%）"
        f" — **勿单独引用；看 by_tier**",
        f"- **Wilson 95% CI:** [{wilson.get('low', '—')}, {wilson.get('high', '—')}]%",
        f"- **说明:** {s.get('honesty', '')}",
        "",
        "## Honesty / 怎么读",
        "",
    ]
    honesty = report.get("honesty") or {}
    for k in ("smoke", "hard", "held_out", "reporting_rule", "live_reading"):
        if honesty.get(k):
            lines.append(f"- **{k}:** {honesty[k]}")
    lines.extend(
        [
            "",
            "## 按 tier（主表）",
            "",
            "| tier | passed | total | rate |",
            "|------|--------|-------|------|",
        ]
    )
    for name, info in (report.get("by_tier") or {}).items():
        lines.append(
            f"| `{name}` | {info.get('passed', 0)} | {info.get('total', 0)} "
            f"| {info.get('pass_rate', 0)}% |"
        )
    lines.extend(
        [
            "",
            "## Drop-off controls（hard）",
            "",
            "| control | passed | total | rate |",
            "|---------|--------|-------|------|",
        ]
    )
    for name, info in (report.get("dropoff_controls") or {}).items():
        lines.append(
            f"| `{name}` | {info.get('passed', 0)} | {info.get('total', 0)} "
            f"| {info.get('pass_rate', 0)}% |"
        )
    lines.extend(
        [
            "",
            "## Inspired by",
            "",
        ]
    )
    for item in report.get("inspired_by") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## 明细（主结果）", ""])
    for r in report.get("results") or []:
        icon = "PASS" if r.get("passed") else "FAIL"
        lines.append(
            f"- [{icon}] `{r.get('id')}` ({r.get('tier')}/{r.get('mode')}): "
            f"recall={r.get('retrieval_recall')} | {r.get('reason', '')}"
        )
    if report.get("license_notes"):
        lines.extend(["", "## License", "", str(report["license_notes"])])
    lines.append("")
    return "\n".join(lines)

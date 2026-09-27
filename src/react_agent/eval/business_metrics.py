"""Shared business evaluation metrics used by delivery adapters."""
from __future__ import annotations
from collections.abc import Iterable, Mapping
from typing import Any

def safe_rate(numerator, denominator):
    return 0.0 if denominator <= 0 else round(max(0.0, min(1.0, float(numerator) / float(denominator))), 3)

def _percentile(values, quantile):
    ordered = sorted(values)
    return round(ordered[max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * quantile))))], 3)

def business_scorecard(rows: Iterable[Mapping[str, Any]], *, passed_key="passed", human_handoff_key=None, duration_key=None):
    rows = list(rows); total = len(rows); passed = sum(bool(row.get(passed_key)) for row in rows)
    out = {"task_success_rate": safe_rate(passed, total), "failure_rate": safe_rate(total - passed, total), "sample_size": total}
    if human_handoff_key:
        count = sum(bool(row.get(human_handoff_key)) for row in rows)
        out.update(human_handoff_rate=safe_rate(count, total), human_handoff_count=count)
    if duration_key:
        durations = [float(row[duration_key]) for row in rows if row.get(duration_key) is not None]
        if durations: out.update(duration_avg_ms=round(sum(durations) / len(durations), 3), duration_p95_ms=_percentile(durations, .95))
    return out

def compare_scorecards(baseline, candidate, *, hard_metrics=("task_success_rate",)):
    deltas = {k: round(float(candidate[k]) - float(baseline[k]), 3) for k in set(baseline) & set(candidate) if isinstance(baseline[k], (int,float)) and isinstance(candidate[k], (int,float))}
    regressions = [k for k, v in deltas.items() if k in hard_metrics and v < 0]
    return {"deltas": deltas, "hard_metric_regressions": regressions, "decision": "hold" if regressions else "pass"}

from __future__ import annotations

import json

from scripts.ci.selector_backtest import replay


def test_replay_uses_fixed_paths_and_keeps_unmeasured_labels(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({
        "schema_version": "ci-selector-sample/v1",
        "sample_id": "sample",
        "source_sha": "a" * 40,
        "samples": [{"pr": 1, "head_sha": "b" * 40, "changed_paths": ["src/react_agent/foo.py", "unknown/file.xyz"]}],
    }), encoding="utf-8")

    report = replay(sample, "sample")

    assert report["sample_size"] == 1
    assert report["metrics"]["unmapped_files"] == 1
    assert report["metrics"]["false_positive_rules"] is None
    assert report["metrics"]["missed_expected_rules"] is None
    assert report["conclusion"] == "blocked"

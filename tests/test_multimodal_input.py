from pathlib import Path

import pytest

from react_agent.multimodal import (
    MultimodalError,
    attach_evidence,
    build_multimodal_input,
    inspect_artifact,
)
from react_agent.apps.docs_troubleshoot.evidence import parse_multimodal_evidence
from react_agent.skills import run_skill


def test_text_artifact_is_normalized_and_extracts_text(tmp_path: Path):
    path = tmp_path / "policy.md"
    path.write_text("# Refund\n30 days", encoding="utf-8")
    artifact = inspect_artifact(path, artifact_id="policy-1")
    assert artifact.media_type == "document"
    assert artifact.extraction_status == "success"
    assert "30 days" in artifact.extracted_text
    assert len(artifact.sha256) == 64


def test_image_metadata_and_ocr_adapter_status(tmp_path: Path):
    image = pytest.importorskip("PIL.Image")
    path = tmp_path / "receipt.png"
    image.new("RGB", (32, 16), "white").save(path)
    artifact = inspect_artifact(path)
    assert artifact.media_type == "image"
    assert (artifact.width, artifact.height) == (32, 16)
    assert artifact.extraction_status == "unsupported"
    extracted = inspect_artifact(path, text_extractor=lambda _: "total: 10")
    assert extracted.extraction_status == "success"
    assert extracted.extracted_text == "total: 10"


def test_input_envelope_reports_partial_failure_and_evidence(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("hello", encoding="utf-8")
    envelope = build_multimodal_input("summarize", [path, tmp_path / "missing.png"])
    assert envelope["status"] == "partial"
    assert envelope["failures"][0]["code"] == "missing_file"
    artifact = inspect_artifact(path)
    ref = attach_evidence(artifact, start_char=0, end_char=5, version="v1")
    assert ref.to_dict()["artifact_id"] == artifact.id


def test_size_limit_is_a_user_correctable_error(tmp_path: Path):
    path = tmp_path / "large.bin"
    path.write_bytes(b"0123456789")
    with pytest.raises(MultimodalError, match="exceeds") as exc:
        inspect_artifact(path, max_bytes=4)
    assert exc.value.code == "file_too_large"


def test_docs_support_converts_artifact_to_evidence_with_truthful_status(tmp_path: Path):
    path = tmp_path / "incident.md"
    path.write_text("upstream timeout trace_id=abc123", encoding="utf-8")
    result = parse_multimodal_evidence(
        [{"path": str(path), "id": "incident-1"}, str(tmp_path / "missing.png")]
    )
    assert result["status"] == "partial"
    assert result["count"] == 1
    item = result["items"][0]
    assert item["type"] == "multimodal_artifact"
    assert item["extraction_status"] == "success"
    assert item["evidence_ref"]["artifact_id"] == "incident-1"
    assert result["failures"][0]["code"] == "missing_file"


def test_docs_skill_exposes_multimodal_summary_without_claiming_vlm(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REACT_AGENT_RAG_MODE", "keyword")
    path = tmp_path / "incident.txt"
    path.write_text("gateway returned 401", encoding="utf-8")
    result = run_skill(
        "docs_troubleshoot",
        {"query": "API 401 怎么排障", "multimodal_artifacts": [str(path)]},
    )
    assert result.ok, result.to_dict()
    assert result.output["multimodal"] == {"status": "ready", "count": 1, "failures": []}

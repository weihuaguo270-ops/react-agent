from pathlib import Path

import pytest

from react_agent.multimodal import (
    MultimodalError,
    attach_evidence,
    build_multimodal_input,
    inspect_artifact,
)


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
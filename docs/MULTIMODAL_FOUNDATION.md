# Multimodal Foundation

`react_agent.multimodal` provides a dependency-light foundation for multimodal Agent tasks. It is intentionally model-neutral: it validates and records inputs before an OCR/VLM adapter or downstream workflow runs.

## Supported foundation

- Normalize image, video, audio, document and unknown files into `MultimodalArtifact`.
- Enforce existence, non-empty content and a configurable byte limit.
- Record MIME type, SHA-256, URI, size and media metadata.
- Decode image dimensions with Pillow when installed; validate video frames with imageio when installed.
- Extract UTF-8 text documents (`.txt`, `.md`, `.json`, `.yaml`, `.yml`).
- Accept an optional `text_extractor(path)` adapter for OCR or document/VLM extraction.
- Build a model-neutral input envelope with `ready`, `partial` and `failed` states.
- Attach claim evidence to an artifact using file, page, bounding-box, table-cell or character-range locators.

## Example

```python
from react_agent.multimodal import attach_evidence, build_multimodal_input, inspect_artifact

payload = build_multimodal_input("检查这张票据", ["receipt.png"])
artifact = inspect_artifact("receipt.png", artifact_id="receipt-1")
ref = attach_evidence(artifact, locator_type="region", bbox=(10, 20, 180, 90), version="v1")
```

`extraction_status="unsupported"` means no OCR/vision adapter was configured. It is not a successful extraction result. The module does not upload files, call a vision model, implement resumable transfers, or perform PII/copyright/prompt-injection classification; those remain application or service-layer responsibilities.
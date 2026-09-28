"""Lightweight multimodal input normalization for the Agent runtime."""
from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_MEDIA_BY_SUFFIX = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "image", ".bmp": "image", ".mp4": "video", ".mov": "video",
    ".webm": "video", ".avi": "video", ".wav": "audio", ".mp3": "audio",
    ".m4a": "audio", ".flac": "audio", ".txt": "document", ".md": "document",
    ".json": "document", ".yaml": "document", ".yml": "document",
    ".pdf": "document", ".docx": "document", ".xlsx": "document",
}
_TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml"}


class MultimodalError(ValueError):
    """A user-correctable multimodal input error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class EvidenceRef:
    """A stable location inside an artifact for a claim or answer field."""

    artifact_id: str
    locator_type: str = "file"
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    cell: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    version: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise MultimodalError("invalid_evidence", "artifact_id must be non-empty")
        if self.page is not None and self.page < 1:
            raise MultimodalError("invalid_evidence", "page must be positive")
        if self.bbox is not None and (len(self.bbox) != 4 or any(v < 0 for v in self.bbox)):
            raise MultimodalError("invalid_evidence", "bbox must contain four non-negative values")
        if self.start_char is not None and self.start_char < 0:
            raise MultimodalError("invalid_evidence", "start_char must be non-negative")
        if self.end_char is not None and self.start_char is not None and self.end_char < self.start_char:
            raise MultimodalError("invalid_evidence", "end_char must not precede start_char")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.bbox is not None:
            value["bbox"] = list(self.bbox)
        return value


@dataclass(frozen=True)
class MultimodalArtifact:
    """Normalized artifact metadata safe to place in an Episode."""

    id: str
    media_type: str
    uri: str
    mime_type: str
    sha256: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    frame_count: int | None = None
    extracted_text: str = ""
    extraction_status: str = "not_requested"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_type(path: Path, mime_type: str) -> str:
    suffix_type = _MEDIA_BY_SUFFIX.get(path.suffix.lower())
    if suffix_type:
        return suffix_type
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type in {"application/pdf", "application/json"}:
        return "document"
    return "other"


def inspect_artifact(
    path: str | Path,
    *,
    artifact_id: str | None = None,
    max_bytes: int = 50 * 1024 * 1024,
    text_extractor: Callable[[Path], str] | None = None,
) -> MultimodalArtifact:
    """Validate a local artifact and return deterministic metadata.

    Image dimensions use Pillow when available. Video/audio decoders are optional;
    unavailable decoders are represented as an explicit metadata status.
    """
    target = Path(path)
    if not target.is_file():
        raise MultimodalError("missing_file", f"artifact does not exist: {target}")
    size = target.stat().st_size
    if size <= 0:
        raise MultimodalError("empty_file", f"artifact is empty: {target}")
    if size > max_bytes:
        raise MultimodalError("file_too_large", f"artifact exceeds {max_bytes} bytes: {target}")

    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    media = _media_type(target, mime)
    metadata: dict[str, Any] = {"file_name": target.name}
    width = height = duration_ms = frame_count = None
    extracted_text = ""
    extraction_status = "not_requested"

    if media == "image":
        try:
            from PIL import Image
            with Image.open(target) as image:
                image.verify()
            with Image.open(target) as image:
                width, height = image.width, image.height
                metadata["format"] = image.format or ""
        except ImportError:
            metadata["decoder"] = "pillow_unavailable"
        except Exception as exc:
            raise MultimodalError("decode_error", f"image cannot be decoded: {exc}") from exc
        if text_extractor is None:
            extraction_status = "unsupported"
            metadata["extraction_reason"] = "no OCR/vision adapter configured"
        else:
            try:
                extracted_text = str(text_extractor(target))
                extraction_status = "success"
            except Exception as exc:
                extraction_status = "failed"
                metadata["extraction_error"] = type(exc).__name__
    elif media == "document" and target.suffix.lower() in _TEXT_SUFFIXES:
        extracted_text = target.read_text(encoding="utf-8", errors="replace")
        extraction_status = "success"
    elif media == "video":
        try:
            import imageio.v3 as iio
            frames = iio.imread(target, index=None)
            if getattr(frames, "ndim", 0) != 4 or frames.shape[0] < 2:
                raise MultimodalError("decode_error", "video must contain at least two frames")
            frame_count = int(frames.shape[0])
            height, width = int(frames.shape[1]), int(frames.shape[2])
            metadata["decoder"] = "imageio"
        except ImportError:
            extraction_status = "unsupported"
            metadata["decoder"] = "imageio_unavailable"
        except MultimodalError:
            raise
        except Exception as exc:
            raise MultimodalError("decode_error", f"video cannot be decoded: {exc}") from exc
    else:
        metadata["decoder"] = "metadata_only"

    return MultimodalArtifact(
        id=artifact_id or target.stem,
        media_type=media,
        uri=target.resolve().as_uri(),
        mime_type=mime,
        sha256=_sha256(target),
        size_bytes=size,
        width=width,
        height=height,
        duration_ms=duration_ms,
        frame_count=frame_count,
        extracted_text=extracted_text,
        extraction_status=extraction_status,
        metadata=metadata,
    )


def build_multimodal_input(
    text: str,
    artifacts: Sequence[str | Path],
    *,
    max_bytes: int = 50 * 1024 * 1024,
    text_extractor: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    """Build a model-neutral input envelope with truthful per-artifact status."""
    normalized: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, path in enumerate(artifacts, start=1):
        try:
            artifact = inspect_artifact(
                path, artifact_id=f"artifact-{index}", max_bytes=max_bytes, text_extractor=text_extractor
            )
            normalized.append(artifact.to_dict())
        except MultimodalError as exc:
            failures.append({"path": str(path), "code": exc.code, "message": exc.message})
    status = "failed" if failures and not normalized else "partial" if failures else "ready"
    return {
        "text": text,
        "artifacts": normalized,
        "failures": failures,
        "status": status,
        "completion_criteria": ["all required artifacts are valid", "claims cite an artifact evidence ref"],
    }


def attach_evidence(
    artifact: MultimodalArtifact,
    *,
    locator_type: str = "file",
    page: int | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    cell: str | None = None,
    start_char: int | None = None,
    end_char: int | None = None,
    version: str = "",
) -> EvidenceRef:
    """Create a stable evidence reference for a claim or answer field."""
    return EvidenceRef(
        artifact_id=artifact.id,
        locator_type=locator_type,
        page=page,
        bbox=bbox,
        cell=cell,
        start_char=start_char,
        end_char=end_char,
        version=version,
    )
"""Optional Milvus vector-store adapter used by :mod:`react_agent.rag`."""
from __future__ import annotations

import hashlib
import os
from typing import Any


class MilvusStore:
    """Thin lazy adapter around ``pymilvus.MilvusClient``.

    Importing this module does not import pymilvus.  A connection is opened
    only when the RAG backend is explicitly configured as ``milvus``.
    """

    def __init__(
        self,
        *,
        uri: str | None = None,
        token: str | None = None,
        collection: str | None = None,
        dimension: int | None = None,
        index_type: str | None = None,
        hnsw_m: int | None = None,
        hnsw_ef_construction: int | None = None,
        hnsw_ef_search: int | None = None,
        client: Any = None,
    ):
        self.uri = uri or os.environ.get("REACT_AGENT_MILVUS_URI", "http://localhost:19530")
        self.token = token or os.environ.get("REACT_AGENT_MILVUS_TOKEN", "")
        self.collection = collection or os.environ.get(
            "REACT_AGENT_MILVUS_COLLECTION", "react_agent_rag"
        )
        self.dimension = int(dimension or os.environ.get("REACT_AGENT_MILVUS_DIMENSION", "512"))
        self.index_type = (index_type or os.environ.get("REACT_AGENT_MILVUS_INDEX_TYPE", "HNSW")).upper()
        if self.index_type != "HNSW":
            raise ValueError("Milvus vector index_type must be HNSW for explicit ANN control")
        self.hnsw_m = int(hnsw_m or os.environ.get("REACT_AGENT_MILVUS_HNSW_M", "16"))
        self.hnsw_ef_construction = int(
            hnsw_ef_construction or os.environ.get("REACT_AGENT_MILVUS_HNSW_EF_CONSTRUCTION", "200")
        )
        self.hnsw_ef_search = int(
            hnsw_ef_search or os.environ.get("REACT_AGENT_MILVUS_HNSW_EF_SEARCH", "64")
        )
        self._client = client
        self._ready = False

    @property
    def client(self):
        if self._client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise ImportError(
                    'Milvus RAG 需要: pip install -e ".[rag]"'
                ) from exc
            kwargs = {"uri": self.uri}
            if self.token:
                kwargs["token"] = self.token
            self._client = MilvusClient(**kwargs)
        self._ensure_collection()
        return self._client

    def _ensure_collection(self):
        if self._ready:
            return
        client = self._client
        if client.has_collection(collection_name=self.collection):
            self._ready = True
            return
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name="pk", datatype=_data_type("INT64"), is_primary=True
        )
        schema.add_field(
            field_name="vector", datatype=_data_type("FLOAT_VECTOR"), dim=self.dimension
        )
        schema.add_field(field_name="content", datatype=_data_type("VARCHAR"), max_length=65535)
        schema.add_field(field_name="source", datatype=_data_type("VARCHAR"), max_length=2048)
        schema.add_field(field_name="chunk_hash", datatype=_data_type("VARCHAR"), max_length=64)
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type=self.index_type,
            metric_type="COSINE",
            params={"M": self.hnsw_m, "efConstruction": self.hnsw_ef_construction},
        )
        client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        self._ready = True

    def upsert(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        client = self.client
        # Insert is idempotent because pk is derived from source + content.
        client.upsert(collection_name=self.collection, data=records)

    def search(self, vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        rows = self.client.search(
            collection_name=self.collection,
            data=[vector],
            limit=top_k,
            output_fields=["content", "source", "chunk_hash"],
            search_params={"metric_type": "COSINE", "params": {"ef": max(self.hnsw_ef_search, top_k)}},
        )
        hits = rows[0] if rows else []
        results = []
        for hit in hits:
            entity = hit.get("entity", hit)
            results.append({
                "content": entity.get("content", ""),
                "source": entity.get("source", ""),
                "score": float(hit.get("distance", hit.get("score", 0.0))),
            })
        return results

    def clear(self) -> None:
        client = self.client
        try:
            client.delete(collection_name=self.collection, filter="pk >= 0")
        except TypeError:
            # Older pymilvus clients accept a primary-key expression only via
            # query/delete APIs with a generated id list.
            rows = client.query(
                collection_name=self.collection,
                filter="",
                output_fields=["pk"],
                limit=16384,
            )
            ids = [row["pk"] for row in rows]
            if ids:
                client.delete(collection_name=self.collection, ids=ids)

    def flush(self) -> None:
        """Flush pending writes once after a batch (Milvus rate-limits flush)."""
        self._flush(self.client, self.collection)

    @staticmethod
    def _flush(client, collection: str) -> None:
        """Make writes visible to subsequent query/search calls when supported."""
        flush = getattr(client, "flush", None)
        if flush is not None:
            flush(collection_name=collection)

    def list_sources(self, limit: int = 16384) -> list[str]:
        # Milvus limits offset + limit to 16384 for a query window.
        limit = max(1, min(int(limit), 16384))
        try:
            rows = self.client.query(
                collection_name=self.collection,
                filter="",
                output_fields=["source"],
                limit=limit,
            )
        except Exception:
            return []
        return sorted({str(row.get("source", "")) for row in rows if row.get("source")})

    @staticmethod
    def record_id(source: str, content: str) -> int:
        digest = hashlib.sha256(f"{source}\n{content}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big", signed=False) & ((1 << 63) - 1)


def _data_type(name: str):
    from pymilvus import DataType

    return getattr(DataType, name)


__all__ = ["MilvusStore"]

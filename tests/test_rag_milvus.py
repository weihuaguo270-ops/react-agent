"""Offline contract tests for the optional Milvus RAG backend."""
from __future__ import annotations

from react_agent.rag import RAG
from react_agent.milvus_store import MilvusStore


class FakeStore:
    def __init__(self):
        self.records = []
        self.cleared = False

    @staticmethod
    def record_id(source, content):
        return abs(hash((source, content)))

    def upsert(self, records):
        self.records.extend(records)

    def search(self, vector, top_k=5):
        return [
            {"content": r["content"], "source": r["source"], "score": 0.9}
            for r in self.records[:top_k]
        ]

    def clear(self):
        self.records.clear()
        self.cleared = True

    def list_sources(self):
        return sorted({r["source"] for r in self.records})


def test_milvus_backend_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("REACT_AGENT_RAG_BACKEND", "milvus")
    store = FakeStore()
    rag = RAG(save_path=str(tmp_path / "unused.json"), milvus_store=store)
    monkeypatch.setattr(rag, "_encode", lambda text: [0.1, 0.2])

    assert rag.ingest_text("Milvus stores enterprise knowledge.", "guide.md")
    assert store.records[0]["source"] == "guide.md"
    hits = rag.query("enterprise knowledge", top_k=1)
    assert hits == [{"content": "Milvus stores enterprise knowledge.", "source": "guide.md", "score": 0.9}]
    assert rag.list_sources() == ["guide.md"]
    rag.clear()
    assert store.cleared and store.records == []


def test_backend_rejects_unknown_value():
    try:
        RAG(backend="vector-db")
    except ValueError as exc:
        assert "local" in str(exc) and "milvus" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown backend must fail fast")


class FakeMilvusClient:
    def __init__(self):
        self.data = []
        self.deleted_filter = None

    def has_collection(self, **kwargs):
        return True

    def upsert(self, **kwargs):
        self.data = kwargs["data"]

    def search(self, **kwargs):
        return [[{
            "entity": {"content": "found", "source": "manual.md", "chunk_hash": "x"},
            "distance": 0.88,
        }]]

    def delete(self, **kwargs):
        self.deleted_filter = kwargs["filter"]
        self.data = []

    def query(self, **kwargs):
        return [{"source": "manual.md"}, {"source": "guide.md"}, {"source": "manual.md"}]


def test_milvus_store_client_contract():
    client = FakeMilvusClient()
    store = MilvusStore(collection="test_rag", client=client)
    store.upsert([{"pk": 1, "vector": [0.1], "content": "one", "source": "one.md", "chunk_hash": "a"}])
    assert client.data[0]["pk"] == 1
    assert store.search([0.1]) == [{"content": "found", "source": "manual.md", "score": 0.88}]
    assert store.list_sources() == ["guide.md", "manual.md"]
    store.clear()
    assert client.deleted_filter == "pk >= 0"


def test_hnsw_is_explicit_and_configurable(monkeypatch):
    monkeypatch.setenv("REACT_AGENT_MILVUS_HNSW_M", "24")
    monkeypatch.setenv("REACT_AGENT_MILVUS_HNSW_EF_CONSTRUCTION", "160")
    monkeypatch.setenv("REACT_AGENT_MILVUS_HNSW_EF_SEARCH", "96")
    store = MilvusStore(client=FakeMilvusClient())
    assert store.index_type == "HNSW"
    assert (store.hnsw_m, store.hnsw_ef_construction, store.hnsw_ef_search) == (24, 160, 96)

    try:
        MilvusStore(index_type="AUTOINDEX", client=FakeMilvusClient())
    except ValueError as exc:
        assert "HNSW" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("implicit AUTOINDEX must not be accepted")

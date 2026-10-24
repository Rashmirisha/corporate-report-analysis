import pytest

pytest.importorskip("chromadb")

from app.retrieval.chroma_retriever import ChromaRetriever, FakeEmbedder  # noqa: E402


def _chunk(cid, company, page, text, doc="report.pdf"):
    return {
        "chunk_id": cid,
        "company": company,
        "document_name": doc,
        "page": page,
        "text": text,
        "sha256": "abc123",
    }


@pytest.fixture
def retriever(tmp_path):
    r = ChromaRetriever(persist_dir=str(tmp_path / "chroma"), embedder=FakeEmbedder())
    r.index_chunks("A", [
        _chunk("A-1", "A", 10, "Total revenue from operations increased strongly"),
        _chunk("A-2", "A", 25, "Employees across plants and canteen facilities"),
        _chunk("A-3", "A", 60, "Risk of rising steel prices reducing profit"),
    ])
    r.index_chunks("B", [
        _chunk("B-1", "B", 5, "Tractor sales revenue grew in rural markets", "other.pdf"),
        _chunk("B-2", "B", 33, "Risk of monsoon failure affecting demand", "other.pdf"),
    ])
    return r


def test_returns_relevant_chunk_with_evidence(retriever):
    hit = retriever.search("A", "total revenue operations", k=1)[0]
    assert hit["chunk_id"] == "A-1"
    assert hit["page"] == 10
    assert hit["document_name"] == "report.pdf"
    assert hit["sha256"] == "abc123"
    assert hit["company"] == "A"


def test_company_isolation(retriever):
    for query in ["revenue", "risk", "tractor", "steel"]:
        assert all(h["chunk_id"].startswith("A-") for h in retriever.search("A", query, k=10))
        assert all(h["chunk_id"].startswith("B-") for h in retriever.search("B", query, k=10))


def test_indexing_is_idempotent(retriever):
    assert retriever.count("A") == 3
    again = retriever.index_chunks("A", [_chunk("A-1", "A", 10, "Total revenue from operations increased strongly")])
    assert again == 0
    assert retriever.count("A") == 3


def test_chunk_from_other_company_is_rejected(retriever):
    with pytest.raises(ValueError):
        retriever.index_chunks("A", [_chunk("B-9", "B", 1, "wrong company")])


def test_invalid_company_is_rejected(retriever):
    with pytest.raises(ValueError):
        retriever.search("C", "revenue")


def test_empty_query_and_empty_collection(tmp_path):
    r = ChromaRetriever(persist_dir=str(tmp_path / "empty"), embedder=FakeEmbedder())
    assert r.search("A", "revenue") == []
    r.index_chunks("A", [_chunk("A-1", "A", 1, "revenue")])
    assert r.search("A", "   ") == []
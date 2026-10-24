"""ChromaDB semantic retriever (standalone draft).

- One Chroma collection per company, so Company A and B never mix.
- Evidence is preserved: chunk id, page, document name, kind and sha256
  are stored as metadata and returned with every hit.
- Embeddings are local (Ollama nomic-embed-text). No paid API.
- This module does NOT touch the existing TF-IDF retriever.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Protocol

VALID_COMPANIES = ("A", "B")


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Local embeddings via Ollama. Needs: ollama pull nomic-embed-text"""

    def __init__(self, model: str = "nomic-embed-text") -> None:
        self.model = model

    def _embed(self, text: str) -> list[float]:
        import ollama  # lazy import: tests and TF-IDF mode don't need it

        return ollama.embeddings(model=self.model, prompt=text)["embedding"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed("search_document: " + t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed("search_query: " + text)


class FakeEmbedder:
    """Deterministic word-hash embeddings for tests (no Ollama needed)."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        return v

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def _unit(vec: list[float]) -> list[float]:
    """Normalise to length 1 so Chroma's default L2 ranking equals cosine ranking."""
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first available field from a dict or an object."""
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _plain(value: Any) -> str:
    """Turn enums such as Company.A into plain strings."""
    return str(getattr(value, "value", value))


class ChromaRetriever:
    def __init__(self, persist_dir: str = "data/chroma_db", embedder: Embedder | None = None) -> None:
        import chromadb

        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._embedder = embedder or OllamaEmbedder()

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _name(company: str) -> str:
        if company not in VALID_COMPANIES:
            raise ValueError(f"company must be 'A' or 'B', got {company!r}")
        return f"company_{company.lower()}"

    def _collection(self, company: str):
        return self._client.get_or_create_collection(name=self._name(company))

    @staticmethod
    def _to_record(company: str, chunk: Any) -> dict:
        owner = _get(chunk, "company")
        if owner is not None and _plain(owner).upper() != company:
            raise ValueError(f"chunk belongs to company {_plain(owner)}, not {company}")
        chunk_id = _get(chunk, "chunk_id", "id", "table_id")
        text = _get(chunk, "text", "content", "markdown")
        if chunk_id is None or not text:
            raise ValueError("each chunk needs an id and text")
        return {
            "id": str(chunk_id),
            "text": str(text),
            "meta": {
                "company": company,
                "document_name": _plain(_get(chunk, "document_name", "filename", "source", default="")),
                "page": int(_get(chunk, "page", "page_number", default=0)),
                "kind": _plain(_get(chunk, "kind", "type", default="text")),
                "sha256": _plain(_get(chunk, "sha256", "document_sha256", default="")),
            },
        }

    # ---- public API ------------------------------------------------------
    def index_chunks(self, company: str, chunks: list, batch_size: int = 16) -> int:
        """Embed and store chunks. Already-indexed ids are skipped. Returns number added."""
        col = self._collection(company)
        records = {r["id"]: r for r in (self._to_record(company, c) for c in chunks)}
        if not records:
            return 0
        known = set(col.get(ids=list(records))["ids"])
        new = [r for rid, r in records.items() if rid not in known]
        for i in range(0, len(new), batch_size):
            batch = new[i : i + batch_size]
            vectors = self._embedder.embed_documents([r["text"] for r in batch])
            col.add(
                ids=[r["id"] for r in batch],
                documents=[r["text"] for r in batch],
                embeddings=[_unit(v) for v in vectors],
                metadatas=[r["meta"] for r in batch],
            )
        return len(new)

    def search(self, company: str, query: str, k: int = 5) -> list[dict]:
        """Return the k most similar chunks for ONE company, with evidence fields."""
        col = self._collection(company)
        total = col.count()
        if total == 0 or not query.strip():
            return []
        res = col.query(
            query_embeddings=[_unit(self._embedder.embed_query(query))],
            n_results=min(k, total),
            where={"company": company},
        )
        hits = []
        for cid, doc, meta, dist in zip(
            res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            if meta.get("company") != company:  # isolation guard
                continue
            hits.append(
                {
                    "chunk_id": cid,
                    "text": doc,
                    "company": company,
                    "page": meta.get("page"),
                    "document_name": meta.get("document_name"),
                    "kind": meta.get("kind"),
                    "sha256": meta.get("sha256"),
                    "score": round(1 - dist / 2, 4),  # cosine similarity for unit vectors
                }
            )
        return hits

    def count(self, company: str) -> int:
        return self._collection(company).count()

    def clear(self, company: str) -> None:
        try:
            self._client.delete_collection(self._name(company))
        except Exception:
            pass
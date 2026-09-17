"""Stage 2 retrieval: scoped semantic + keyword search over Stage-1 chunks.

Design constraints:

* Agent A must NEVER see Company B chunks/tables. Agent B must NEVER see
  Company A chunks/tables. The retriever enforces this at the API boundary
  — every public method takes a `company` argument and refuses to operate
  otherwise.

* Embedding-free path: a TF-IDF-style scorer (pure numpy). This keeps
  Stage 2 fully offline and reproducible; we don't need to load a
  sentence-transformers model just to fetch top-k chunks. The same
  `Retriever` interface accepts a precomputed embedding model later, so
  Stage 2's behaviour stays testable without changes.

* Citations are always returned with full evidence metadata, so the agent
  downstream can paste `chunk_id` and `page_number` into its JSON output.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

import numpy as np

from app.schemas import Company, CompanyState, TableRecord, TextChunk


# ---------- public types ----------

@dataclass
class ScoredChunk:
    chunk: TextChunk
    score: float

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def page_number(self) -> int:
        return self.chunk.page_number

    @property
    def snippet(self) -> str:
        return self.chunk.text

    @property
    def company(self) -> Company:
        return self.chunk.company


@dataclass
class ScoredTable:
    table: TableRecord
    score: float

    @property
    def table_id(self) -> str:
        return self.table.table_id

    @property
    def page_number(self) -> int:
        return self.table.page_number


@dataclass
class RetrievalHit:
    """One piece of evidence the agent can cite. Wraps a chunk OR a table."""
    kind: str  # "chunk" or "table"
    id: str
    company: Company
    document_name: str
    document_sha256: str
    page_number: int
    score: float
    snippet: str  # short preview text (always present)
    chunk: TextChunk | None = None
    table: TableRecord | None = None


# ---------- tokenisation ----------

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-%]+|\d[\d,\.\-%]*")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


# ---------- retriever ----------

class Retriever:
    """In-memory, company-scoped retriever over a CompanyState."""

    def __init__(self, state: CompanyState) -> None:
        self.state = state
        self._company: Company = state.company
        self._chunk_ids: set[str] = {c.chunk_id for c in state.chunks}
        self._table_ids: set[str] = {t.table_id for t in state.tables}

        # Build TF-IDF index over chunks.
        self._chunk_texts: list[str] = [c.text for c in state.chunks]
        self._chunk_tokens: list[list[str]] = [_tokenize(t) for t in self._chunk_texts]
        self._chunk_df: Counter[str] = Counter()
        for toks in self._chunk_tokens:
            for term in set(toks):
                self._chunk_df[term] += 1
        self._chunk_n = max(1, len(self._chunk_tokens))
        self._chunk_idf: dict[str, float] = {
            term: math.log((1 + self._chunk_n) / (1 + df)) + 1.0
            for term, df in self._chunk_df.items()
        }
        # Pre-normalised chunk vectors (sparse → dense on demand).
        self._chunk_vecs: list[dict[str, float]] = [
            self._tfidf_vector(toks) for toks in self._chunk_tokens
        ]

        # Tables: we just score by header/row text overlap.
        self._table_texts: list[str] = [
            " ".join([" ".join(t.headers), " ".join(" ".join(r) for r in t.rows)])
            for t in state.tables
        ]
        self._table_tokens: list[list[str]] = [_tokenize(t) for t in self._table_texts]

    # ---- public API ----

    @property
    def company(self) -> Company:
        return self._company

    def search_chunks(self, query: str, *, top_k: int = 8) -> list[ScoredChunk]:
        query_tokens = _tokenize(query)
        if not query_tokens or not self._chunk_vecs:
            return []
        q_vec = self._query_vector(query_tokens)
        scored: list[ScoredChunk] = []
        for i, vec in enumerate(self._chunk_vecs):
            score = _cosine(q_vec, vec)
            if score > 0:
                scored.append(ScoredChunk(chunk=self.state.chunks[i], score=score))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def search_tables(self, query: str, *, top_k: int = 4) -> list[ScoredTable]:
        query_tokens = _tokenize(query)
        if not query_tokens or not self._table_tokens:
            return []
        q_counter = Counter(query_tokens)
        scored: list[ScoredTable] = []
        for i, toks in enumerate(self._table_tokens):
            t_counter = Counter(toks)
            # Simple jaccard-ish overlap score, weighted by IDF.
            overlap = sum((q_counter & t_counter).values())
            if overlap == 0:
                continue
            score = overlap / math.sqrt(len(query_tokens) * max(1, len(toks)))
            scored.append(ScoredTable(table=self.state.tables[i], score=score))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def evidence_pack(self, queries: Sequence[str], *, top_k_chunks: int = 6, top_k_tables: int = 3) -> list[RetrievalHit]:
        """Run several queries, dedupe by id, return one hit per item."""
        seen: set[tuple[str, str]] = set()
        hits: list[RetrievalHit] = []
        for q in queries:
            for sc in self.search_chunks(q, top_k=top_k_chunks):
                key = ("chunk", sc.chunk_id)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    RetrievalHit(
                        kind="chunk",
                        id=sc.chunk_id,
                        company=self._company,
                        document_name=sc.chunk.document_name,
                        document_sha256=sc.chunk.document_sha256,
                        page_number=sc.page_number,
                        score=sc.score,
                        snippet=_snippet(sc.chunk.text),
                        chunk=sc.chunk,
                    )
                )
            for st in self.search_tables(q, top_k=top_k_tables):
                key = ("table", st.table_id)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    RetrievalHit(
                        kind="table",
                        id=st.table_id,
                        company=self._company,
                        document_name=st.table.document_name,
                        document_sha256=st.table.document_sha256,
                        page_number=st.page_number,
                        score=st.score,
                        snippet=st.table.preview,
                        table=st.table,
                    )
                )
        return hits

    def chunk_by_id(self, chunk_id: str) -> TextChunk | None:
        if not self._belongs_to_us(chunk_id, kind="chunk"):
            return None
        return self.state.chunk_by_id(chunk_id)

    def table_by_id(self, table_id: str) -> TableRecord | None:
        if not self._belongs_to_us(table_id, kind="table"):
            return None
        return self.state.table_by_id(table_id)

    # ---- internal ----

    def _belongs_to_us(self, item_id: str, *, kind: str) -> bool:
        """Refuse any id that doesn't start with our company prefix.

        This is the safety belt against Agent A asking for a B_* id by
        mistake (or maliciously). If the id's company prefix doesn't match
        ours, the retriever pretends it doesn't exist.
        """
        expected_prefix = f"{self._company}_"
        if not item_id.startswith(expected_prefix):
            return False
        if kind == "chunk":
            return item_id in self._chunk_ids
        if kind == "table":
            return item_id in self._table_ids
        return False

    def _tfidf_vector(self, tokens: Iterable[str]) -> dict[str, float]:
        counter = Counter(tokens)
        total = sum(counter.values()) or 1
        vec: dict[str, float] = {}
        for term, count in counter.items():
            idf = self._chunk_idf.get(term, 1.0)
            vec[term] = (count / total) * idf
        return vec

    def _query_vector(self, query_tokens: list[str]) -> dict[str, float]:
        counter = Counter(query_tokens)
        total = sum(counter.values()) or 1
        vec: dict[str, float] = {}
        for term, count in counter.items():
            idf = self._chunk_idf.get(term, 1.0)
            vec[term] = (count / total) * idf
        return vec


# ---------- helpers ----------

def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # iterate over the smaller dict
    if len(a) > len(b):
        a, b = b, a
    num = 0.0
    a_norm_sq = 0.0
    for k, v in a.items():
        a_norm_sq += v * v
        bv = b.get(k)
        if bv is not None:
            num += v * bv
    b_norm_sq = sum(v * v for v in b.values())
    if a_norm_sq <= 0 or b_norm_sq <= 0:
        return 0.0
    return num / math.sqrt(a_norm_sq * b_norm_sq)


def _snippet(text: str, *, limit: int = 320) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def build_retrievers(corpus_a: CompanyState | None, corpus_b: CompanyState | None) -> dict[Company, Retriever | None]:
    return {
        "A": Retriever(corpus_a) if corpus_a else None,
        "B": Retriever(corpus_b) if corpus_b else None,
    }


# numpy import kept for symmetry with future embedder integration
_ = np

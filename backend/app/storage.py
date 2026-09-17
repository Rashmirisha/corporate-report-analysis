"""In-process corpus store for Stage 1.

Stage 2+ can swap this for a DB or vector index without changing call sites.
"""
from __future__ import annotations

import threading
from typing import Optional

from app.schemas import Company, CompanyState, Corpus


class CorpusStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._corpus = Corpus()

    def set(self, state: CompanyState) -> None:
        with self._lock:
            if state.company == "A":
                self._corpus.state_a = state
            elif state.company == "B":
                self._corpus.state_b = state
            else:
                raise ValueError(f"unknown company {state.company!r}")

    def get(self, company: Company) -> Optional[CompanyState]:
        with self._lock:
            return self._corpus.state_a if company == "A" else self._corpus.state_b

    def corpus(self) -> Corpus:
        with self._lock:
            # Return a shallow copy so callers can't mutate stored state.
            return Corpus.model_validate(self._corpus.model_dump())

    def reset(self) -> None:
        with self._lock:
            self._corpus = Corpus()


# Single global instance for the FastAPI app.
store = CorpusStore()

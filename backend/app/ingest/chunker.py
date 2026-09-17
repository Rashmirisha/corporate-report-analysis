"""Page-aware text chunker.

Design rules:
- Chunks **never** cross page boundaries. Downstream agents cite `page_number`
  per chunk, so a chunk that mixes text from two pages would be impossible to
  cite correctly.
- Chunks are sized to roughly `TARGET_WORDS` words with an `OVERLAP_WORDS`
  word overlap between consecutive chunks on the same page (to preserve
  context across the boundary). Both knobs are bounded by `HARD_MAX_WORDS`
  so a single huge page can't become a single huge chunk.
- Empty pages produce no chunks (chunk IDs are stable because they always
  carry the page number; gaps in numbering are expected and harmless).
"""
from __future__ import annotations

from typing import List, Tuple

from app.ingest.pdf_reader import PageData

TARGET_WORDS = 220
OVERLAP_WORDS = 30
HARD_MAX_WORDS = 380


def _words(text: str) -> List[str]:
    return [w for w in text.split() if w]


def _word_window(words: List[str], start: int, size: int) -> Tuple[int, int]:
    end = min(start + size, len(words))
    return start, end


def chunk_pages(pages: List[PageData]) -> List[dict]:
    """Chunk a list of pdf_reader.PageData into page-bounded chunks.

    Returns a list of dicts (not TextChunk models) so this layer has zero
    dependency on the API schemas. The pipeline converts at the boundary.
    """
    out: List[dict] = []
    for page in pages:
        words = _words(page.text)
        if not words:
            continue
        cursor = 0
        local_idx = 0
        n = len(words)
        while cursor < n:
            # Choose chunk size, capped at HARD_MAX_WORDS to avoid runaways.
            size = min(TARGET_WORDS, max(1, HARD_MAX_WORDS))
            start, end = _word_window(words, cursor, size)
            chunk_words = words[start:end]
            if not chunk_words:
                break
            text = " ".join(chunk_words)
            out.append(
                {
                    "page_number": page.page_number,
                    "section": page.section_hint,
                    "text": text,
                    "char_count": len(text),
                    "word_count": len(chunk_words),
                    "_page_local_index": local_idx,  # used by pipeline for stable ID
                }
            )
            local_idx += 1
            if end >= n:
                break
            # Slide forward, leaving overlap words behind for context.
            cursor = end - min(OVERLAP_WORDS, end - start)
            # Guard against infinite loops if overlap >= size.
            if cursor <= start:
                cursor = end
    return out

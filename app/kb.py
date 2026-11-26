"""Local knowledge-base retriever (condition A baseline).

Condition A agents may only use the static KB (12 Markdown articles) plus
their own reasoning — no Meko. This module loads ``data/kb/*.md`` and does
naive token-overlap retrieval (content words, title boost). It is also the
KB source for :class:`FakeMekoClient`, so both conditions see the same KB.
"""

from __future__ import annotations

import re
from pathlib import Path

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "by", "at", "from", "it", "its",
    "this", "that", "you", "your", "we", "our", "can", "will", "if",
    "how", "what", "when", "not", "no", "do", "does", "did", "as", "but",
    "after", "before", "into", "over", "under", "please", "hi", "hello",
    "thanks", "help", "please", "just", "get", "got", "have", "has",
}


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


class LocalKB:
    """Naive keyword retriever over the Markdown KB articles."""

    def __init__(self, kb_dir: str | Path):
        self.kb_dir = Path(kb_dir)
        self.docs: list[dict] = []
        for path in sorted(self.kb_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = text.splitlines()[0].lstrip("# ").strip() if text else path.stem
            self.docs.append({
                "id": path.stem, "title": title, "path": str(path), "text": text,
                "tokens": tokenize(title + " " + text),
            })

    def search(self, query: str, limit: int = 3) -> list[dict]:
        """Return top-``limit`` docs by token overlap with ``query``."""
        qtokens = tokenize(query)
        scored = []
        for doc in self.docs:
            overlap = len(qtokens & doc["tokens"])
            title_overlap = len(qtokens & tokenize(doc["title"]))
            score = overlap + 2 * title_overlap
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: -x[0])
        out = []
        for score, doc in scored[:limit]:
            excerpt = doc["text"][:600].replace("\n", " ")
            out.append({"id": doc["id"], "title": doc["title"], "score": score,
                        "excerpt": excerpt, "text": doc["text"]})
        return out

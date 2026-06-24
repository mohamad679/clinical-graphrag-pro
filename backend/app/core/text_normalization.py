"""
Shared text normalization for sparse retrieval.

The sparse pipeline intentionally keeps clinically meaningful surface forms:
hyphenated medication/classes, slash-separated units, decimals, plus signs, and
short numeric tokens. It does not apply broad stop-word removal because clinical
phrases often depend on small terms and units.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[.+/#-][a-z0-9]+)*(?:[+#])?", re.IGNORECASE)
HYPHENS = {
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
}


def normalize_sparse_text(text: str) -> str:
    """Normalize text before sparse tokenization."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    for source, replacement in HYPHENS.items():
        normalized = normalized.replace(source, replacement)
    normalized = normalized.lower()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def tokenize_sparse_text(text: str) -> list[str]:
    """Tokenize clinical text for BM25 indexing and sparse querying."""
    normalized = normalize_sparse_text(text)
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(normalized):
        token = match.group(0).strip("._")
        if not token:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        tokens.append(token)
        if any(separator in token for separator in ("-", "/", "+", "#")):
            for part in re.split(r"[-/+#]", token):
                if part and (len(part) > 1 or part.isdigit()):
                    tokens.append(part)
    return tokens


def sparse_text_diagnostics(texts: list[str]) -> dict:
    """Return safe aggregate diagnostics for sparse-index text state."""
    tokenized = [tokenize_sparse_text(text) for text in texts]
    vocabulary = {token for tokens in tokenized for token in tokens}
    duplicate_counts = Counter(" ".join(tokens) for tokens in tokenized if tokens)
    return {
        "document_count": len(texts),
        "token_count": sum(len(tokens) for tokens in tokenized),
        "vocabulary_size": len(vocabulary),
        "empty_document_count": sum(1 for tokens in tokenized if not tokens),
        "duplicate_document_count": sum(count - 1 for count in duplicate_counts.values() if count > 1),
    }

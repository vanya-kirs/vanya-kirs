"""Text deduplication helpers — no AI, no external deps."""
import hashlib
import re


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def text_hash(text: str) -> str:
    """MD5 of normalized text — stable fingerprint for exact reposts."""
    return hashlib.md5(_normalize(text).encode("utf-8")).hexdigest()


def word_set(text: str) -> set[str]:
    """Meaningful words (length > 3) from normalized text."""
    return {w for w in _normalize(text).split() if len(w) > 3}


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity of word sets. Returns 0.0 if both empty."""
    sa, sb = word_set(a), word_set(b)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)

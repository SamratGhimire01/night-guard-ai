# ponytail: word count is a cheap proxy for token count (~0.75 tokens/word for
# English), not exact. Swap for a real tokenizer (tiktoken) if a model's hard
# token limit is ever actually hit.
_CHUNK_SIZE_WORDS = 500
_OVERLAP_WORDS = 50


def chunk_text(
    text: str, *, chunk_size_words: int = _CHUNK_SIZE_WORDS, overlap_words: int = _OVERLAP_WORDS
) -> list[str]:
    """Splits text into overlapping word-count chunks. Empty/whitespace-only
    input returns no chunks."""
    words = text.split()
    if not words:
        return []

    step = chunk_size_words - overlap_words
    chunks = []
    for start in range(0, len(words), step):
        chunk_words = words[start : start + chunk_size_words]
        chunks.append(" ".join(chunk_words))
        if start + chunk_size_words >= len(words):
            break
    return chunks

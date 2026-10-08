"""Local text embeddings: report chunks and search queries become unit vectors on this machine, no external service.

`LocalEmbedder` runs a quantised ONNX sentence-embedding model through fastembed (default BAAI/bge-small-en-v1.5,
384 dimensions, MIT licence; downloaded once to runtime/models/, then offline). `HashingEmbedder` is a deterministic
stand-in for tests: it never touches the network or a model file.
"""

import hashlib
import os
import re
from pathlib import Path
from ..core.errors import ModelError

ROOT = Path(__file__).resolve().parents[3]
SENTENCE = re.compile(r"(?<=[.!?])[\"'”’)]*\s+(?=[A-Z0-9\"“‘(])")


def chunk_text(text, max_words=90, overlap_sentences=1):
    """Sentence windows of at most `max_words`, each sharing `overlap_sentences` with the previous window.

    Returns [{"text", "start", "end"}]; text == source[start:end], so any passage shown is a verbatim quote.
    A single sentence longer than `max_words` becomes its own chunk rather than being cut mid-sentence.
    """
    text = str(text)
    spans, pos = [], 0
    for m in SENTENCE.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    spans = [(a, b) for a, b in spans if text[a:b].strip()]
    chunks, i = [], 0
    while i < len(spans):
        j, words = i, 0
        while j < len(spans) and (j == i or words + len(text[spans[j][0]:spans[j][1]].split()) <= max_words):
            words += len(text[spans[j][0]:spans[j][1]].split())
            j += 1
        start, end = spans[i][0], spans[j - 1][1]
        chunks.append({"text": text[start:end], "start": start, "end": end})
        if j >= len(spans):
            break
        i = max(i + 1, j - overlap_sentences)
    return chunks


def _normalise(matrix):
    import numpy as np

    m = np.asarray(matrix, dtype=np.float32)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    return m / n


class LocalEmbedder:
    def __init__(self, model="BAAI/bge-small-en-v1.5", cache_dir=None):
        self.name = model
        self.cache_dir = Path(cache_dir or os.getenv("FLOODCAT_MODEL_DIR") or ROOT / "runtime" / "models")
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError:
                raise ModelError("embeddings_unavailable", "Local embeddings need the `embed` extra (uv sync --extra embed)") from None
            # The Xet transfer protocol fails on some networks; plain HTTPS resumes reliably.
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
            try:
                self._model = TextEmbedding(self.name, cache_dir=str(self.cache_dir))
            except Exception as exc:  # download or model-file errors
                raise ModelError("embeddings_unavailable", f"Could not load the local embedding model {self.name}: {str(exc)[:160]}") from None
        return self._model

    def embed(self, texts):
        """Unit vectors (float32, one row per text)."""
        texts = list(texts)
        if not texts:
            import numpy as np

            return np.zeros((0, 384), dtype=np.float32)
        return _normalise(list(self._load().embed(texts, batch_size=32)))

    def embed_queries(self, texts):
        # BGE retrieval queries carry an instruction prefix; passages do not.
        prefix = "Represent this sentence for searching relevant passages: " if "bge" in self.name.lower() else ""
        return self.embed([prefix + t for t in texts])


class HashingEmbedder:
    """Deterministic bag-of-words vectors for tests (cosine ≈ word overlap). Not for real use."""

    name = "hashing-test"

    def __init__(self, dim=256):
        self.dim = dim

    def embed(self, texts):
        import numpy as np

        texts = list(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z]+", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1
        return _normalise(out)

    embed_queries = embed

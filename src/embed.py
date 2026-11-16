"""Chunking and embeddings for the semantic diff.

The embedder is injectable so the pipeline's logic can be tested without a
model: `diff_semantic` takes any object with an `encode(list[str]) -> ndarray`
returning L2-normalized row vectors. In production that is `LocalEmbedder`
wrapping sentence-transformers; in the test suite it is a deterministic
lexical stand-in, which keeps every test offline and fast.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np

from .models import PageContent

# all-MiniLM-L6-v2: 384 dims, ~90MB, runs on CPU in well under a second per
# page. The build plan's default, and good enough that the API alternative has
# to earn its cost.
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Chunk sizing. Too small and every chunk is a fragment that matches everything;
# too large and a dropped paragraph is diluted by the surviving text around it
# -- which is exactly the failure this whole stage exists to avoid.
TARGET_WORDS = 80
MAX_WORDS = 160
MIN_CHUNK_WORDS = 8

_PUNCT = re.compile(r"[^\w\s]+")


def _norm(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", text.lower()).split())


@dataclass
class Chunk:
    """A passage of a page, labelled with the section it sits under.

    When the page carries real `Block`s (see models.py), a chunk is exactly
    one block -- one paragraph, one list, one table -- rather than a slice of
    however many words fit a budget. `kind`/`ordered`/`items`/`columns` carry
    that block's shape through matching so the review screen can still render
    it as a list or a table rather than as flattened prose.
    """

    text: str
    section: str        # nearest heading, "" if none
    index: int
    kind: str = "paragraph"          # "paragraph" | "list" | "table" | "quote"
    ordered: bool = False             # list only: <ol> vs <ul>
    items: list[str] = field(default_factory=list)   # list items / table rows
    columns: list[str] = field(default_factory=list)  # table header cells
    heading_path: tuple[str, ...] = ()  # ancestor headings, nearest last

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def preview(self, width: int = 90) -> str:
        flat = " ".join(self.text.split())
        return flat if len(flat) <= width else flat[: width - 3] + "..."


class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return one L2-normalized row vector per input string."""
        ...


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------

def chunk_page(
    page: PageContent,
    *,
    target_words: int = TARGET_WORDS,
    max_words: int = MAX_WORDS,
) -> list[Chunk]:
    """Split a page into the passages matching compares old-to-new.

    When the page has real `Block`s -- every page freshly crawled does -- one
    block is one chunk: a paragraph is one passage, a list is one passage, a
    table is one passage. That is what lets a twenty-paragraph section be
    twenty independently addressable passages instead of a handful of
    word-budget slices that all carried the same heading label.

    Pages with no blocks (results written before blocks existed, or a
    `PageContent` built directly with only `.text`, as most tests do) fall
    back to the original word-budget grouping over flattened text.
    """
    if page.blocks:
        return _chunks_from_blocks(page.blocks)
    return _chunks_from_text(page, target_words=target_words, max_words=max_words)


def _chunks_from_blocks(blocks) -> list[Chunk]:
    out: list[Chunk] = []
    for b in blocks:
        if b.kind == "heading":
            continue          # headings are structure, not a passage to match
        heading_path = tuple(b.heading_path)
        out.append(Chunk(
            text=b.text, section=heading_path[-1] if heading_path else "",
            index=len(out), kind=b.kind, ordered=b.ordered,
            items=list(b.items), columns=list(b.columns),
            heading_path=heading_path,
        ))
    return out


def _chunks_from_text(
    page: PageContent,
    *,
    target_words: int = TARGET_WORDS,
    max_words: int = MAX_WORDS,
) -> list[Chunk]:
    """Group flattened text up to a word budget, starting a new chunk at each
    heading. The legacy path, kept for pages with no structural blocks."""
    heading_keys = {_norm(h.text) for h in page.headings if h.text.strip()}
    # trafilatura separates blocks with a single newline, not a blank line, so
    # splitting on blank lines puts a whole page in one chunk and defeats the
    # per-passage matching entirely.
    paragraphs = [p.strip() for p in page.text.splitlines() if p.strip()]

    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_words = 0
    section = ""

    def flush() -> None:
        nonlocal buffer, buffer_words
        if not buffer:
            return
        text = "\n".join(buffer).strip()
        if text:
            chunks.append(Chunk(text=text, section=section, index=len(chunks)))
        buffer, buffer_words = [], 0

    for para in paragraphs:
        words = len(para.split())
        is_heading = _norm(para) in heading_keys

        if is_heading:
            flush()
            section = para
            # The heading itself rides with the section it introduces rather
            # than standing alone, where a bare title would match almost
            # anything.
            buffer, buffer_words = [para], words
            continue

        if buffer_words and buffer_words + words > max_words:
            flush()
        buffer.append(para)
        buffer_words += words
        if buffer_words >= target_words:
            flush()

    flush()

    # A trailing fragment is folded back into its predecessor: a six-word
    # chunk carries no reliable meaning on its own.
    merged: list[Chunk] = []
    for chunk in chunks:
        if (merged and chunk.word_count < MIN_CHUNK_WORDS
                and merged[-1].section == chunk.section):
            previous = merged[-1]
            merged[-1] = Chunk(
                text=previous.text + "\n" + chunk.text,
                section=previous.section,
                index=previous.index,
            )
        else:
            merged.append(Chunk(chunk.text, chunk.section, len(merged)))
    return merged


# --------------------------------------------------------------------------
# embedders
# --------------------------------------------------------------------------

def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


class LocalEmbedder:
    """sentence-transformers, loaded once and reused.

    The model is loaded lazily: importing this module must stay cheap, since
    the structural stages and the CLI's argument parsing have no use for it.
    """

    _cache: dict[str, object] = {}

    def __init__(self, model_name: str = DEFAULT_MODEL, *, batch_size: int = 32):
        self.model_name = model_name
        self.batch_size = batch_size

    @property
    def model(self):
        if self.model_name not in self._cache:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:      # pragma: no cover - env dependent
                raise RuntimeError(
                    "sentence-transformers is not installed. Uncomment the "
                    "phase 3 block in requirements.txt and reinstall."
                ) from exc
            self._cache[self.model_name] = SentenceTransformer(self.model_name)
        return self._cache[self.model_name]

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


class LexicalEmbedder:
    """A deterministic bag-of-words embedder, for tests and offline runs.

    Hashes tokens into a fixed-width vector, so cosine similarity tracks word
    overlap. It has no idea that "cost" and "tuition" are related -- which is
    the entire reason the real model exists -- but it is enough to exercise
    chunking, alignment and thresholds without loading 2 GB of torch, and it
    makes the test suite's behaviour reproducible.
    """

    def __init__(self, dims: int = 256):
        self.dims = dims

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _norm(text).split():
                # crc32, not hash(): Python randomizes string hashing per
                # process, which would make the same test give different
                # similarities on different runs.
                out[row, zlib.crc32(token.encode("utf-8")) % self.dims] += 1.0
        return l2_normalize(out)


def get_embedder(name: str = "local", **kwargs) -> Embedder:
    if name == "local":
        return LocalEmbedder(**kwargs)
    if name == "lexical":
        return LexicalEmbedder(**kwargs)
    raise ValueError(f"unknown embedder {name!r}")

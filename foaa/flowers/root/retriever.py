from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RetrievedDocument:
    """A piece of knowledge drawn from the soil, with its provenance."""

    id: str
    content: str
    source: str
    score: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Retriever(Protocol):
    """RAG port: *what does this flower need to know now?*

    Implement it over any vector store, search engine, or database. FOAA is not a vector
    database (Constitution, scope); it only asks for the smallest relevant context.
    ``name`` is the source name policies refer to (``rag_sources=["product-docs"]``).
    """

    name: str

    async def retrieve(self, query: str, *, limit: int) -> Sequence[RetrievedDocument]: ...


_WORD = re.compile(r"\w+")


def _terms(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if len(word) > 2}


class InMemoryRetriever:
    """A tiny keyword-overlap retriever for tests, examples, and small static corpora."""

    def __init__(self, name: str, documents: Iterable[RetrievedDocument | str]) -> None:
        self.name = name
        self._documents: list[RetrievedDocument] = []
        for index, document in enumerate(documents):
            if isinstance(document, str):
                document = RetrievedDocument(id=f"{name}-{index}", content=document, source=name)
            self._documents.append(document)

    async def retrieve(self, query: str, *, limit: int) -> Sequence[RetrievedDocument]:
        if limit <= 0:
            return []
        query_terms = _terms(query)
        scored: list[RetrievedDocument] = []
        for document in self._documents:
            overlap = len(query_terms & _terms(document.content))
            if overlap:
                score = overlap / max(len(query_terms), 1)
                scored.append(
                    RetrievedDocument(
                        id=document.id,
                        content=document.content,
                        source=document.source,
                        score=score,
                        metadata=document.metadata,
                    )
                )
        scored.sort(key=lambda doc: doc.score or 0.0, reverse=True)
        return scored[:limit]

"""Privacy-safe document ingestion for legal case evidence."""

from korgan_legal_ai.documents.extractor import (
    DocumentExtractionError,
    ExtractedDocument,
    OpenAIDocumentExtractor,
)

__all__ = [
    "DocumentExtractionError",
    "ExtractedDocument",
    "OpenAIDocumentExtractor",
]

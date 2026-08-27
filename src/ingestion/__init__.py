"""
Offline ingestion path — Document Fetcher, Parser, Chunker, Indexer (Phase 1).
"""

from src.ingestion.chunker import (
    Chunk,
    ChunkReport,
    ChunkResult,
    chunk_document,
    chunk_processed_document,
    chunk_scheme_pages,
)
from src.ingestion.fetcher import FetchReport, FetchResult, fetch_scheme_pages
from src.ingestion.indexer import (
    IndexReport,
    SchemeIndexResult,
    build_index,
    collection_count,
    index_chunks,
    open_collection,
)
from src.ingestion.parser import (
    ParseReport,
    ParseResult,
    ParsedDocument,
    parse_scheme_html,
    parse_scheme_pages,
)

__all__ = [
    "Chunk",
    "ChunkReport",
    "ChunkResult",
    "FetchReport",
    "FetchResult",
    "IndexReport",
    "ParseReport",
    "ParseResult",
    "ParsedDocument",
    "SchemeIndexResult",
    "build_index",
    "chunk_document",
    "chunk_processed_document",
    "chunk_scheme_pages",
    "collection_count",
    "fetch_scheme_pages",
    "index_chunks",
    "open_collection",
    "parse_scheme_html",
    "parse_scheme_pages",
]

"""Public facade for the source-review scripts and their focused regression tests."""

from .lookups import (
    HostRateLimiter,
    crossref_url,
    evaluate_source,
    failed_record,
    fetch,
    successful_record,
)
from .metadata import (
    arxiv_api_url,
    arxiv_metadata,
    arxiv_rights,
    crossref_external,
    html_external,
)
from .schema import (
    SCHEMA_VERSION,
    author_match,
    catalogue_fingerprint,
    catalogue_fields,
    citation_pages,
    classify,
    extract_doi,
    extract_title,
    input_fingerprint,
    metadata_comparisons,
    source_catalogue,
    venue_match,
)
from .snapshot import (
    build_snapshot,
    cached_record_is_compatible,
    reclassify_record,
    write_snapshot,
)

__all__ = [
    "HostRateLimiter",
    "SCHEMA_VERSION",
    "arxiv_api_url",
    "arxiv_metadata",
    "arxiv_rights",
    "author_match",
    "build_snapshot",
    "cached_record_is_compatible",
    "catalogue_fields",
    "catalogue_fingerprint",
    "citation_pages",
    "classify",
    "crossref_external",
    "crossref_url",
    "evaluate_source",
    "extract_doi",
    "extract_title",
    "failed_record",
    "fetch",
    "html_external",
    "input_fingerprint",
    "metadata_comparisons",
    "reclassify_record",
    "source_catalogue",
    "successful_record",
    "venue_match",
    "write_snapshot",
]

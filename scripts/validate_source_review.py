#!/usr/bin/env python3
"""Validate the generated, complete source metadata and rights audit."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, NoReturn, cast
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry.yaml"
REVIEW = ROOT / "docs/provenance/source-review.json"
SCHEMA_VERSION = 3
METADATA_FIELDS = (
    "identifier",
    "title",
    "authors",
    "date",
    "venue",
    "volume_issue",
    "pages",
    "locator",
)
OUTCOMES = {
    "MATCH",
    "NOT_APPLICABLE",
    "POSSIBLE_CONFLICT",
    "MISSING_IN_CATALOGUE",
    "MISSING_IN_SOURCE",
    "UNAVAILABLE",
}
REVIEW_OUTCOMES = OUTCOMES - {"MATCH", "NOT_APPLICABLE"}
RIGHTS_OUTCOMES = {
    "RIGHTS_RECORDED",
    "NO_EXPLICIT_RIGHTS",
    "RIGHTS_UNAVAILABLE",
}
LOOKUP_STATUSES = {"OK", "MISSING_LOCATOR", "HTTP_ERROR", "PARSE_ERROR"}
RECORD_STATUSES = {"AUTOMATED_CLEAR", "NEEDS_HUMAN", "LOOKUP_FAILED"}
PROVIDERS = {"arxiv", "crossref", "html", "none"}
SHA256 = re.compile(r"[0-9a-f]{64}")


def fail(message: str) -> NoReturn:
    print(f"source review error: {message}", file=sys.stderr)
    raise SystemExit(1)


def mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(message)
    return cast("dict[str, Any]", value)


def text(value: object, message: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        fail(message)
    return value


def http_url(value: object, message: str, *, allow_empty: bool = False) -> str:
    value = text(value, message, allow_empty=allow_empty)
    if not value and allow_empty:
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        fail(message)
    return value


def utc_timestamp(value: object, message: str) -> str:
    value = text(value, message)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(message)
    if parsed.tzinfo is None:
        fail(message)
    return value


def fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def work_sources(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalogue = mapping(
        registry.get("source_catalog"), "registry.yaml source_catalog must be an object"
    )
    return {
        source_id: source
        for source_id, source in catalogue.items()
        if isinstance(source, dict) and source.get("role") == "work"
    }


def source_input_fingerprint(source: dict[str, Any]) -> str:
    return fingerprint({"citation": source["citation"], "locator": source.get("locator")})


def expected_status(
    lookup_status: str,
    comparisons: list[dict[str, Any]],
    rights: dict[str, Any],
    related_dois: list[dict[str, Any]],
) -> str:
    if lookup_status in {"HTTP_ERROR", "PARSE_ERROR"}:
        return "LOOKUP_FAILED"
    if any(comparison["outcome"] in REVIEW_OUTCOMES for comparison in comparisons):
        return "NEEDS_HUMAN"
    if rights["outcome"] != "RIGHTS_RECORDED":
        return "NEEDS_HUMAN"
    if related_dois:
        return "NEEDS_HUMAN"
    return "AUTOMATED_CLEAR"


def validate_record(source_id: str, source: dict[str, Any], value: object) -> str:
    record = mapping(value, f"{source_id} review record must be an object")
    required = {
        "input_fingerprint",
        "provider",
        "lookup_status",
        "checked_url",
        "checked_on",
        "metadata",
        "rights",
        "related_dois",
        "status",
        "notes",
    }
    if set(record) != required:
        fail(f"{source_id} review record must contain exactly {sorted(required)}")
    input_hash = text(record.get("input_fingerprint"), f"{source_id} input_fingerprint")
    if not SHA256.fullmatch(input_hash):
        fail(f"{source_id} input_fingerprint must be a SHA-256 digest")
    if input_hash != source_input_fingerprint(source):
        fail(f"{source_id} input_fingerprint does not match registry.yaml")
    provider = text(record.get("provider"), f"{source_id} provider")
    if provider not in PROVIDERS:
        fail(f"{source_id} has unknown provider {provider!r}")
    lookup_status = text(record.get("lookup_status"), f"{source_id} lookup_status")
    if lookup_status not in LOOKUP_STATUSES:
        fail(f"{source_id} has unknown lookup_status {lookup_status!r}")
    checked_url = http_url(
        record.get("checked_url"),
        f"{source_id} checked_url must be HTTP(S) or empty for no locator",
        allow_empty=lookup_status == "MISSING_LOCATOR",
    )
    if lookup_status != "MISSING_LOCATOR" and not checked_url:
        fail(f"{source_id} checked_url must not be empty")
    utc_timestamp(record.get("checked_on"), f"{source_id} checked_on must be a UTC timestamp")
    metadata_value = record.get("metadata")
    if not isinstance(metadata_value, list) or len(metadata_value) != len(METADATA_FIELDS):
        fail(f"{source_id} metadata must contain one comparison for every field")
    comparisons: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    for index, raw_comparison in enumerate(metadata_value):
        comparison = mapping(
            raw_comparison, f"{source_id} metadata entry {index} must be an object"
        )
        if set(comparison) != {
            "field",
            "catalogue_value",
            "source_value",
            "outcome",
        }:
            fail(
                f"{source_id} metadata entry {index} must contain exactly "
                "['catalogue_value', 'field', 'outcome', 'source_value']"
            )
        field = text(comparison.get("field"), f"{source_id} metadata entry {index} field")
        if field not in METADATA_FIELDS or field in seen_fields:
            fail(f"{source_id} metadata has invalid or repeated field {field!r}")
        seen_fields.add(field)
        text(
            comparison.get("catalogue_value"),
            f"{source_id} metadata entry {index} catalogue_value",
        )
        text(
            comparison.get("source_value"),
            f"{source_id} metadata entry {index} source_value",
        )
        outcome = text(
            comparison.get("outcome"), f"{source_id} metadata entry {index} outcome"
        )
        if outcome not in OUTCOMES:
            fail(f"{source_id} metadata entry {index} has unknown outcome {outcome!r}")
        comparisons.append(comparison)
    if seen_fields != set(METADATA_FIELDS):
        fail(f"{source_id} metadata does not cover every required field")
    related_dois_value = record.get("related_dois")
    if not isinstance(related_dois_value, list):
        fail(f"{source_id} related_dois must be a list")
    related_dois: list[dict[str, Any]] = []
    seen_dois: set[str] = set()
    for index, value in enumerate(related_dois_value):
        related = mapping(value, f"{source_id} related DOI {index} must be an object")
        if set(related) != {"doi", "url"}:
            fail(f"{source_id} related DOI {index} must contain exactly ['doi', 'url']")
        doi = text(related.get("doi"), f"{source_id} related DOI {index} doi")
        if doi in seen_dois:
            fail(f"{source_id} repeats related DOI {doi!r}")
        seen_dois.add(doi)
        http_url(related.get("url"), f"{source_id} related DOI {index} URL")
        related_dois.append(related)
    rights = mapping(record.get("rights"), f"{source_id} rights must be an object")
    if set(rights) != {"outcome", "details", "url"}:
        fail(
            f"{source_id} rights must contain exactly ['details', 'outcome', 'url']"
        )
    rights_outcome = text(rights.get("outcome"), f"{source_id} rights outcome")
    if rights_outcome not in RIGHTS_OUTCOMES:
        fail(f"{source_id} rights has unknown outcome {rights_outcome!r}")
    text(rights.get("details"), f"{source_id} rights details")
    http_url(
        rights.get("url"),
        f"{source_id} rights URL must be HTTP(S) or empty when unavailable",
        allow_empty=rights_outcome != "RIGHTS_RECORDED",
    )
    text(record.get("notes"), f"{source_id} notes", allow_empty=True)
    status = text(record.get("status"), f"{source_id} status")
    if status not in RECORD_STATUSES:
        fail(f"{source_id} has unknown status {status!r}")
    if status != expected_status(lookup_status, comparisons, rights, related_dois):
        fail(f"{source_id} status does not match its recorded outcomes")
    return status


def main() -> None:
    try:
        registry = mapping(json.loads(REGISTRY.read_text(encoding="utf-8")), "registry.yaml")
        review = mapping(json.loads(REVIEW.read_text(encoding="utf-8")), "source-review.json")
    except (OSError, json.JSONDecodeError) as error:
        fail(str(error))
    required = {"schema_version", "generated_at", "source_fingerprint", "records"}
    if set(review) != required:
        fail(f"source-review.json must contain exactly {sorted(required)}")
    if review.get("schema_version") != SCHEMA_VERSION:
        fail(f"source-review.json must use schema version {SCHEMA_VERSION}")
    utc_timestamp(review.get("generated_at"), "source-review.json generated_at must be a UTC timestamp")
    sources = work_sources(registry)
    source_hash = text(review.get("source_fingerprint"), "source-review.json source_fingerprint")
    if not SHA256.fullmatch(source_hash):
        fail("source-review.json source_fingerprint must be a SHA-256 digest")
    if source_hash != fingerprint(sources):
        fail("source-review.json is stale for the current source catalogue")
    records = mapping(review.get("records"), "source-review.json records must be an object")
    if set(records) != set(sources):
        missing = sorted(set(sources) - set(records))
        extra = sorted(set(records) - set(sources))
        fail(
            "source-review.json must evaluate every work source "
            f"(missing={missing}, extra={extra})"
        )
    counts: dict[str, int] = {}
    for source_id, source in sources.items():
        status = validate_record(source_id, source, records[source_id])
        counts[status] = counts.get(status, 0) + 1
    print(
        "source review ok: "
        + ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
    )


if __name__ == "__main__":
    main()

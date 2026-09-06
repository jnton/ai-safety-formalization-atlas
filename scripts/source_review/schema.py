"""Source-catalogue fields, comparison rules, and shared audit constants."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html import unescape
import json
import re
from typing import Any
import unicodedata


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
MATCH = "MATCH"
NOT_APPLICABLE = "NOT_APPLICABLE"
REVIEW_OUTCOMES = {
    "POSSIBLE_CONFLICT",
    "MISSING_IN_CATALOGUE",
    "MISSING_IN_SOURCE",
    "UNAVAILABLE",
}
RIGHTS_RECORDED = "RIGHTS_RECORDED"
NO_EXPLICIT_RIGHTS = "NO_EXPLICIT_RIGHTS"
RIGHTS_UNAVAILABLE = "RIGHTS_UNAVAILABLE"

DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)(10\.\d{4,9}/[-._;()/:<>a-z0-9]+)",
    re.IGNORECASE,
)
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#]+)", re.IGNORECASE)
SMART_TITLE_RE = re.compile(r"“([^”]+)”")
PLAIN_TITLE_RE = re.compile(r'"([^\"]+)"')
YEAR_RE = re.compile(r"\b(?:1[6-9]\d{2}|20\d{2})\b")
VOLUME_RE = re.compile(r"\bvol\.\s*([^,.;]+)", re.IGNORECASE)
ISSUE_RE = re.compile(r"\bno\.\s*([^,.;]+)", re.IGNORECASE)
PAGES_RE = re.compile(r"\bpp?\.\s*([^,.;]+)", re.IGNORECASE)
VENUE_STOP_WORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def display(value: object) -> str:
    if value is None:
        return "—"
    value = str(value).strip()
    return value or "—"


def normalize(value: object) -> str:
    value = unicodedata.normalize("NFKD", display(value)).casefold()
    value = "".join(
        character for character in value if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def strip_html(value: object) -> str:
    return re.sub(r"<[^>]+>", "", unescape(display(value))).strip()


def source_catalogue(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        source_id: source
        for source_id, source in registry["source_catalog"].items()
        if source.get("role") == "work"
    }


def stable_fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def catalogue_fingerprint(sources: dict[str, dict[str, Any]]) -> str:
    return stable_fingerprint(sources)


def input_fingerprint(source: dict[str, Any]) -> str:
    return stable_fingerprint(
        {"citation": source["citation"], "locator": source.get("locator")}
    )


def clean_doi(value: str) -> str:
    return value.strip().rstrip(".,;").lower()


def extract_doi(value: str) -> str | None:
    match = DOI_RE.search(value)
    return clean_doi(match.group(1)) if match else None


def extract_arxiv_id(value: str) -> str | None:
    match = ARXIV_RE.search(value)
    if not match:
        return None
    return match.group(1).removesuffix(".pdf").rstrip("/")


def arxiv_base_id(arxiv_id: str) -> str:
    """Ignore a revision only when matching the identifier returned by arXiv."""
    return re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)


def source_arxiv_id(source: dict[str, Any]) -> str | None:
    """Return an arXiv ID only when arXiv is the source being checked."""
    return extract_arxiv_id(source.get("locator", ""))


def extract_title(citation: str) -> str:
    match = SMART_TITLE_RE.search(citation) or PLAIN_TITLE_RE.search(citation)
    return match.group(1).strip() if match else ""


def citation_prefix(citation: str, title: str) -> str:
    if not title:
        return ""
    marker = f"“{title}”" if f"“{title}”" in citation else f'"{title}"'
    return citation.split(marker, 1)[0].strip(" ,")


def citation_venue(citation: str, title: str) -> str:
    if not title:
        return ""
    marker = f"“{title}”" if f"“{title}”" in citation else f'"{title}"'
    tail = citation.split(marker, 1)[-1].lstrip(" ,")
    if not tail:
        return ""
    return tail.split(", vol.", 1)[0].split(", no.", 1)[0].strip(" ,.")


def citation_volume_issue(citation: str) -> str:
    volume = VOLUME_RE.search(citation)
    issue = ISSUE_RE.search(citation)
    values = []
    if volume:
        values.append(f"vol. {volume.group(1).strip()}")
    if issue:
        values.append(f"no. {issue.group(1).strip()}")
    return ", ".join(values)


def citation_pages(citation: str) -> str:
    match = PAGES_RE.search(citation)
    if not match:
        return ""
    pages = match.group(1).strip()
    # An author initial such as "P. Pajunen" is not a page range. Every
    # catalogue page notation used here contains a number.
    return pages if any(character.isdigit() for character in pages) else ""


def catalogue_fields(source: dict[str, Any]) -> dict[str, str]:
    citation = source["citation"]
    locator = source.get("locator", "")
    locator_arxiv_id = extract_arxiv_id(locator)
    title = extract_title(citation)
    doi = extract_doi(locator) or extract_doi(citation)
    arxiv_id = locator_arxiv_id or extract_arxiv_id(citation)
    if locator_arxiv_id or (arxiv_id and not doi):
        identifier = f"arxiv:{arxiv_id}"
    else:
        identifier = f"doi:{doi}" if doi else ""
    years = YEAR_RE.findall(citation)
    venue = citation_venue(citation, title)
    # An arXiv identifier is already compared as the record identifier. The
    # abstract page does not separately expose it as a venue.
    if arxiv_id and normalize(venue).startswith("arxiv"):
        venue = ""
    return {
        "identifier": identifier,
        "title": title,
        "authors": citation_prefix(citation, title),
        "date": years[0] if years else "",
        "venue": venue,
        "volume_issue": citation_volume_issue(citation),
        "pages": citation_pages(citation),
        "locator": locator,
    }


def text_match(catalogue_value: str, source_value: str) -> str:
    if not catalogue_value and not source_value:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not source_value:
        return "MISSING_IN_SOURCE"
    catalogue_normal = normalize(catalogue_value)
    source_normal = normalize(source_value)
    if catalogue_normal == source_normal:
        return MATCH
    if catalogue_normal in source_normal or source_normal in catalogue_normal:
        return MATCH
    return "POSSIBLE_CONFLICT"


def author_match(catalogue_value: str, authors: list[str]) -> str:
    if not catalogue_value and not authors:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not authors:
        return "MISSING_IN_SOURCE"
    catalogue_tokens = set(normalize(catalogue_value).split())

    # Both "Given Family" and "Family, Given" are normal bibliographic
    # encodings. A surname-level overlap is enough for this screen; it avoids
    # treating a harmless display-order change as a citation discrepancy.
    def author_is_represented(author: str) -> bool:
        tokens = normalize(author).split()
        return any(len(token) >= 2 and token in catalogue_tokens for token in tokens)

    if all(author_is_represented(author) for author in authors):
        return MATCH
    return "POSSIBLE_CONFLICT"


def date_match(citation: str, catalogue_value: str, source_value: str) -> str:
    if not catalogue_value and not source_value:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not source_value:
        return "MISSING_IN_SOURCE"
    source_years = YEAR_RE.findall(source_value)
    if source_years and source_years[0] in citation:
        return MATCH
    return "POSSIBLE_CONFLICT"


def venue_match(catalogue_value: str, source_value: str) -> str:
    outcome = text_match(catalogue_value, source_value)
    if outcome != "POSSIBLE_CONFLICT":
        return outcome
    catalogue_tokens = [
        token
        for token in normalize(catalogue_value).split()
        if token not in VENUE_STOP_WORDS
    ]
    source_tokens = [
        token for token in normalize(source_value).split() if token not in VENUE_STOP_WORDS
    ]
    if len(catalogue_tokens) >= 2:
        position = 0
        for catalogue_token in catalogue_tokens:
            while position < len(source_tokens) and not source_tokens[position].startswith(
                catalogue_token
            ):
                position += 1
            if position == len(source_tokens):
                break
            position += 1
        else:
            return MATCH
    catalogue_terms = set(catalogue_tokens)
    source_terms = set(source_tokens)
    meaningful = catalogue_terms & source_terms - {"the", "of", "in", "and", "for"}
    return MATCH if len(meaningful) >= 2 else "POSSIBLE_CONFLICT"


def metadata_comparisons(
    source: dict[str, Any], external: dict[str, Any], lookup_ok: bool, final_url: str
) -> list[dict[str, str]]:
    catalogue = catalogue_fields(source)
    external_authors = external.get("authors", [])
    source_values = {
        "identifier": display(external.get("identifier")),
        "title": display(external.get("title")),
        "authors": "; ".join(external_authors) if external_authors else "—",
        "date": display(external.get("date")),
        "venue": display(external.get("venue")),
        "volume_issue": display(external.get("volume_issue")),
        "pages": display(external.get("pages")),
        "locator": display(final_url),
    }
    outcomes = {
        "identifier": text_match(catalogue["identifier"], external.get("identifier", "")),
        "title": text_match(catalogue["title"], external.get("title", "")),
        "authors": author_match(catalogue["authors"], external_authors),
        "date": date_match(source["citation"], catalogue["date"], external.get("date", "")),
        "venue": venue_match(catalogue["venue"], external.get("venue", "")),
        "volume_issue": text_match(
            catalogue["volume_issue"], external.get("volume_issue", "")
        ),
        "pages": text_match(catalogue["pages"], external.get("pages", "")),
        "locator": MATCH if lookup_ok and catalogue["locator"] else "MISSING_IN_CATALOGUE",
    }
    return [
        {
            "field": field,
            "catalogue_value": display(catalogue[field]),
            "source_value": source_values[field],
            "outcome": outcomes[field],
        }
        for field in METADATA_FIELDS
    ]


def unavailable_comparisons(source: dict[str, Any], outcome: str) -> list[dict[str, str]]:
    catalogue = catalogue_fields(source)
    return [
        {
            "field": field,
            "catalogue_value": display(catalogue[field]),
            "source_value": "—",
            "outcome": outcome if catalogue[field] else NOT_APPLICABLE,
        }
        for field in METADATA_FIELDS
    ]


def classify(
    lookup_status: str,
    comparisons: list[dict[str, str]],
    rights: dict[str, str],
    related_dois: list[dict[str, str]] | None = None,
) -> str:
    if lookup_status in {"HTTP_ERROR", "PARSE_ERROR"}:
        return "LOOKUP_FAILED"
    if any(comparison["outcome"] in REVIEW_OUTCOMES for comparison in comparisons):
        return "NEEDS_HUMAN"
    if rights["outcome"] != RIGHTS_RECORDED:
        return "NEEDS_HUMAN"
    if related_dois:
        return "NEEDS_HUMAN"
    return "AUTOMATED_CLEAR"

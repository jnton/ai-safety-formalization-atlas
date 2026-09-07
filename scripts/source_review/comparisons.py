"""Bibliographic comparison, field matching rules, and record classification."""

from __future__ import annotations

import re
from typing import Any

from .schema import (
    MATCH,
    METADATA_FIELDS,
    MISSING_IN_CATALOGUE,
    MISSING_IN_SOURCE,
    NO_AUTOMATED_FOLLOWUP,
    NOT_APPLICABLE,
    POSSIBLE_CONFLICT,
    REVIEW_OUTCOMES,
    RIGHTS_RECORDED,
    VENUE_STOP_WORDS,
    YEAR_RE,
    arxiv_base_id,
    catalogue_fields,
    clean_doi,
    display,
    extract_arxiv_id,
    extract_doi,
    normalize,
)


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


def identifier_match(catalogue_value: str, source_value: str) -> str:
    if not catalogue_value and not source_value:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not source_value:
        return "MISSING_IN_SOURCE"

    cat_val = catalogue_value.strip()
    src_val = source_value.strip()

    # Canonical DOI comparison
    cat_doi = extract_doi(cat_val) or (clean_doi(cat_val[4:]) if cat_val.lower().startswith("doi:") else None)
    src_doi = extract_doi(src_val) or (clean_doi(src_val[4:]) if src_val.lower().startswith("doi:") else None)
    if cat_doi and src_doi:
        return MATCH if cat_doi == src_doi else "POSSIBLE_CONFLICT"

    # Canonical arXiv comparison
    cat_arx = extract_arxiv_id(cat_val) or (cat_val[6:].strip() if cat_val.lower().startswith("arxiv:") else None)
    src_arx = extract_arxiv_id(src_val) or (src_val[6:].strip() if src_val.lower().startswith("arxiv:") else None)
    if cat_arx and src_arx:
        cat_base = arxiv_base_id(cat_arx).lower()
        src_base = arxiv_base_id(src_arx).lower()
        return MATCH if cat_base == src_base else "POSSIBLE_CONFLICT"

    # Exact normalized equality fallback (no generic substring matching)
    return MATCH if normalize(cat_val) == normalize(src_val) else "POSSIBLE_CONFLICT"


def author_match(catalogue_value: str, authors: list[str]) -> str:
    if not catalogue_value and not authors:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not authors:
        return "MISSING_IN_SOURCE"

    def author_is_represented(author: str, target_tokens: set[str]) -> bool:
        tokens = normalize(author).split()
        return any(len(token) >= 2 and token in target_tokens for token in tokens)

    et_al_match = re.search(r"\bet\s+al\b", catalogue_value, flags=re.IGNORECASE)
    if et_al_match:
        leading_text = catalogue_value[: et_al_match.start()].strip(" ,")
        leading_parts = [
            p.strip()
            for p in re.split(r",|\band\b", leading_text)
            if p.strip()
        ]
        if not leading_parts:
            leading_tokens = set(normalize(leading_text).split())
            if not author_is_represented(authors[0], leading_tokens):
                return "POSSIBLE_CONFLICT"
            return MATCH

        for part in leading_parts:
            part_tokens = set(normalize(part).split())
            if not any(author_is_represented(author, part_tokens) for author in authors):
                return "POSSIBLE_CONFLICT"

        first_tokens = set(normalize(leading_parts[0]).split())
        leading_scope = authors[: len(leading_parts)]
        if not any(author_is_represented(author, first_tokens) for author in leading_scope):
            return "POSSIBLE_CONFLICT"
        return MATCH

    catalogue_tokens = set(normalize(catalogue_value).split())
    if all(author_is_represented(author, catalogue_tokens) for author in authors):
        return MATCH
    return "POSSIBLE_CONFLICT"


def date_match(catalogue_value: str, source_value: str, citation: str | None = None) -> str:
    if not catalogue_value and not source_value:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not source_value:
        return "MISSING_IN_SOURCE"
    catalogue_years = YEAR_RE.findall(catalogue_value)
    source_years = YEAR_RE.findall(source_value)
    if catalogue_years and source_years:
        return MATCH if catalogue_years[0] == source_years[0] else "POSSIBLE_CONFLICT"
    return MATCH if normalize(catalogue_value) == normalize(source_value) else "POSSIBLE_CONFLICT"


def volume_issue_match(catalogue_value: str, source_value: str) -> str:
    if not catalogue_value and not source_value:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not source_value:
        return "MISSING_IN_SOURCE"

    def extract_vol_iss(val: str) -> tuple[str | None, str | None]:
        vol_m = re.search(r"\b(?:vol\.?|volume)\s*([0-9a-z\-]+)", val, re.IGNORECASE)
        iss_m = re.search(r"\b(?:no\.?|issue|number)\s*([0-9a-z\-]+)", val, re.IGNORECASE)
        vol = vol_m.group(1).lower() if vol_m else None
        iss = iss_m.group(1).lower() if iss_m else None
        return vol, iss

    cat_v, cat_i = extract_vol_iss(catalogue_value)
    src_v, src_i = extract_vol_iss(source_value)

    if cat_v or cat_i or src_v or src_i:
        if cat_v and src_v and cat_v != src_v:
            return "POSSIBLE_CONFLICT"
        if cat_i and src_i and cat_i != src_i:
            return "POSSIBLE_CONFLICT"
        if (cat_v and src_v and cat_v == src_v) or (cat_i and src_i and cat_i == src_i):
            return MATCH
        if (cat_v and not src_v) or (src_v and not cat_v) or (cat_i and not src_i) or (src_i and not cat_i):
            return "POSSIBLE_CONFLICT"

    return MATCH if normalize(catalogue_value) == normalize(source_value) else "POSSIBLE_CONFLICT"


def pages_match(catalogue_value: str, source_value: str) -> str:
    if not catalogue_value and not source_value:
        return NOT_APPLICABLE
    if not catalogue_value:
        return "MISSING_IN_CATALOGUE"
    if not source_value:
        return "MISSING_IN_SOURCE"

    def clean_pages(val: str) -> list[str]:
        normalized = re.sub(r"[–—]", "-", val)
        return re.findall(r"\d+", normalized)

    cat_pages = clean_pages(catalogue_value)
    src_pages = clean_pages(source_value)
    if not cat_pages and not src_pages:
        return MATCH if normalize(catalogue_value) == normalize(source_value) else "POSSIBLE_CONFLICT"
    if not cat_pages:
        return "MISSING_IN_CATALOGUE"
    if not src_pages:
        return "MISSING_IN_SOURCE"

    if len(cat_pages) >= 2 and len(src_pages) >= 2:
        cat_start, cat_end = cat_pages[0], cat_pages[1]
        src_start, src_end = src_pages[0], src_pages[1]
        if cat_start == src_start and (cat_end == src_end or cat_end.endswith(src_end) or src_end.endswith(cat_end)):
            return MATCH
        return "POSSIBLE_CONFLICT"

    if len(cat_pages) == 1 and len(src_pages) == 1:
        if cat_pages[0] == src_pages[0]:
            return MATCH
        return "POSSIBLE_CONFLICT"

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
        "identifier": identifier_match(
            catalogue["identifier"], external.get("identifier", "")
        ),
        "title": text_match(catalogue["title"], external.get("title", "")),
        "authors": author_match(catalogue["authors"], external_authors),
        "date": date_match(
            catalogue["date"], external.get("date", ""), source.get("citation")
        ),
        "venue": venue_match(catalogue["venue"], external.get("venue", "")),
        "volume_issue": volume_issue_match(
            catalogue["volume_issue"], external.get("volume_issue", "")
        ),
        "pages": pages_match(catalogue["pages"], external.get("pages", "")),
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
    return NO_AUTOMATED_FOLLOWUP

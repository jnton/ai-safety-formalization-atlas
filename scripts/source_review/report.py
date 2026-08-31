"""Render the human-facing source metadata and rights review page."""

from __future__ import annotations

from urllib.parse import quote


def _md_cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _short_citation(citation: str, limit: int = 120) -> str:
    citation = " ".join(citation.split())
    if len(citation) <= limit:
        return citation
    return citation[: limit - 1] + "…"


def _work_sources(registry: dict) -> list[tuple[str, dict]]:
    """Statement-bearing sources that receive an automatic audit outcome."""
    return sorted(
        (source_id, source)
        for source_id, source in registry["source_catalog"].items()
        if source.get("role") == "work"
    )


def _source_locator_link(source: dict) -> str:
    locator = source.get("locator")
    if not locator:
        return "—"
    # Legacy DOI locators can contain characters such as `<` and `>` which are
    # valid once percent-encoded but would otherwise terminate a Markdown link.
    return f"[open](<{quote(locator, safe=':/?&=#%')}>)"


def _work_source_row(source_id: str, source: dict, extra: str) -> str:
    return (
        f"| `{source_id}` | {_md_cell(_short_citation(source['citation']))} | "
        f"{_source_locator_link(source)} | {extra} |"
    )


def _checked_record_link(record: dict) -> str:
    checked_url = record.get("checked_url")
    if not checked_url:
        return "—"
    label = {
        "arxiv": "arXiv API record",
        "crossref": "Crossref record",
        "html": "source page",
    }.get(record["provider"], "queried record")
    return f"[{label}]({checked_url})"


def _lookup_source_label(record: dict) -> str:
    return {"arxiv": "arXiv API", "crossref": "Crossref", "html": "Source page"}.get(
        record.get("provider"), "—"
    )


def _metadata_finding_rows(
    work_sources: list[tuple[str, dict]], records: dict, outcomes: set[str]
) -> list[str]:
    """Show one named class of machine comparison, with both values visible."""
    field_order = {
        "identifier": 0,
        "title": 1,
        "authors": 2,
        "date": 3,
        "venue": 4,
        "volume_issue": 5,
        "pages": 6,
        "locator": 7,
    }
    rows: list[tuple[int, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if not record or record["lookup_status"] != "OK":
            continue
        checked_record = _checked_record_link(record)
        for comparison in record["metadata"]:
            if comparison["outcome"] not in outcomes:
                continue
            rows.append(
                (
                    field_order[comparison["field"]],
                    source_id,
                    f"| `{source_id}` | {_source_locator_link(source)} | "
                    f"`{comparison['field']}` | "
                    f"{_md_cell(comparison['catalogue_value'])} | "
                    f"{_md_cell(comparison['source_value'])} | "
                    f"{_lookup_source_label(record)} | {checked_record} |",
                )
            )
    return [row for _, _, row in sorted(rows)]


def _metadata_source_ids(
    work_sources: list[tuple[str, dict]], records: dict, outcomes: set[str]
) -> set[str]:
    return {
        source_id
        for source_id, _ in work_sources
        if (record := records.get(source_id))
        and record["lookup_status"] == "OK"
        and any(comparison["outcome"] in outcomes for comparison in record["metadata"])
    }


def _rights_presentation(rights: dict) -> tuple[int, str, str]:
    """Translate rights metadata without turning terms pages into licenses."""
    url = rights["url"].casefold()
    details = rights["details"].casefold()
    if "creativecommons.org/licenses/by/4.0" in url:
        return (
            0,
            "CC BY 4.0 license",
            "Direct license for the version of record; reuse is allowed subject to attribution.",
        )
    if "arxiv.org/licenses/nonexclusive-distrib/" in url:
        return (
            1,
            "arXiv non-exclusive distribution license",
            "The author grants arXiv a non-exclusive license to distribute the preprint; it is not a general public reuse license.",
        )
    if "arxiv.org/licenses/assumed-1991-2003" in url:
        return (
            1,
            "arXiv assumed distribution license (1991–2003)",
            "arXiv records this as a distribution license for the preprint; it is not a general public reuse license.",
        )
    if (
        "text-and-data-mining" in url
        or "/tdm" in url
        or "tdm_license" in url
        or "(tdm)" in details
    ):
        return (
            2,
            "Text-and-data-mining terms",
            "Crossref marks this link for text and data mining; it is not identified as a general reuse license.",
        )
    if "acm.org/publications/policies/copyright_policy" in url:
        return (
            1,
            "ACM copyright policy",
            "Crossref marks this link for the version of record; no article-specific license name was deposited.",
        )
    if "ieeexplore.ieee.org" in url:
        return (
            1,
            "IEEE license information",
            "Crossref marks this link for the version of record; the applicable terms need reading at the linked page.",
        )
    if "onlinelibrary.wiley.com/termsandconditions" in url:
        return (
            1,
            "Wiley terms and conditions",
            "Crossref marks this link for the version of record; no article-specific license name was deposited.",
        )
    if "link.aps.org/licenses/aps-default-license" in url:
        return (
            1,
            "APS default license",
            "Crossref marks this link for the version of record; its scope needs reading at the linked page.",
        )
    if "publishingsupport.iopscience.iop.org/iop-standard" in url:
        return (
            1,
            "IOP standard license",
            "Crossref marks this link for the version of record; its scope needs reading at the linked page.",
        )
    if "cambridge.org/core/terms" in url:
        return (
            3,
            "Cambridge Core terms",
            "No specific license name or version scope was deposited with Crossref.",
        )
    if "(vor)" in details:
        return (
            1,
            "Publisher terms for the version of record",
            "Crossref marks this link for the version of record; no article-specific license name was deposited.",
        )
    if "crossref rights metadata" in details:
        return (
            3,
            "Publisher rights or terms page",
            "Crossref supplied a rights link but did not name a license or its version scope.",
        )
    return (
        4,
        "Rights or license statement on the source page",
        f"The source page reports: {_md_cell(rights['details'])}",
    )


def _rights_evidence(record: dict) -> str:
    """Keep both the rights URL and queried record available to a reviewer."""
    rights_url = record["rights"]["url"]
    checked_url = record.get("checked_url")
    if rights_url == checked_url:
        return _checked_record_link(record)
    return (
        f"[{_lookup_source_label(record)} rights link]({rights_url}) · "
        f"{_checked_record_link(record)}"
    )


def _rights_recorded_rows(
    work_sources: list[tuple[str, dict]], records: dict
) -> list[str]:
    rows: list[tuple[int, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if (
            not record
            or record["lookup_status"] != "OK"
            or record["rights"]["outcome"] != "RIGHTS_RECORDED"
        ):
            continue
        rights = record["rights"]
        order, result, scope = _rights_presentation(rights)
        rows.append(
            (
                order,
                source_id,
                f"| `{source_id}` | {_source_locator_link(source)} | {result} | "
                f"{_md_cell(scope)} | {_rights_evidence(record)} |",
            )
        )
    return [row for _, _, row in sorted(rows)]


def _no_rights_rows(
    work_sources: list[tuple[str, dict]], records: dict
) -> list[str]:
    rows: list[tuple[str, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if (
            not record
            or record["lookup_status"] != "OK"
            or record["rights"]["outcome"] != "NO_EXPLICIT_RIGHTS"
        ):
            continue
        rows.append(
            (
                _lookup_source_label(record),
                source_id,
                f"| `{source_id}` | {_source_locator_link(source)} | "
                f"{_lookup_source_label(record)} | {_checked_record_link(record)} |",
            )
        )
    return [row for _, _, row in sorted(rows)]


def _related_doi_rows(
    work_sources: list[tuple[str, dict]], records: dict
) -> list[str]:
    """Surface an arXiv DOI without replacing the cited preprint identifier."""
    rows: list[tuple[str, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if not record or record.get("lookup_status") != "OK":
            continue
        for related in record.get("related_dois", []):
            doi = related["doi"]
            rows.append(
                (
                    source_id,
                    doi,
                    f"| `{source_id}` | {_source_locator_link(source)} | "
                    f"[doi:{_md_cell(doi)}]({related['url']}) | "
                    "arXiv reports this DOI as associated with the preprint. Check whether "
                    "the atlas intentionally cites the preprint rather than a published version. | "
                    f"{_checked_record_link(record)} |",
                )
            )
    return [row for _, _, row in sorted(rows)]


def _lookup_rows(work_sources: list[tuple[str, dict]], records: dict) -> list[str]:
    status_order = {"MISSING_LOCATOR": 0, "HTTP_ERROR": 1, "PARSE_ERROR": 2}
    rows: list[tuple[int, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if not record or record["lookup_status"] == "OK":
            continue
        rows.append(
            (
                status_order.get(record["lookup_status"], 99),
                source_id,
                _work_source_row(
                    source_id,
                    source,
                    f"`{record['lookup_status']}` · {_md_cell(record['notes'])}",
                ),
            )
        )
    return [row for _, _, row in sorted(rows)]


def render_source_review(registry: dict, review: dict) -> str:
    """Render a complete source screen sorted by the follow-up it suggests."""
    work_sources = _work_sources(registry)
    records = review["records"]
    providers = {
        record.get("provider")
        for record in records.values()
        if isinstance(record, dict)
    }
    lookup_methods = []
    if "crossref" in providers:
        lookup_methods.append("Crossref for DOI records")
    if "arxiv" in providers:
        lookup_methods.append("arXiv's API plus its abstract page for arXiv records")
    if "html" in providers:
        lookup_methods.append("the linked public HTML record otherwise")
    if len(lookup_methods) == 1:
        lookup_summary = lookup_methods[0]
    elif len(lookup_methods) == 2:
        lookup_summary = " and ".join(lookup_methods)
    elif lookup_methods:
        lookup_summary = "; ".join(lookup_methods[:-1]) + "; and " + lookup_methods[-1]
    else:
        lookup_summary = "no retrievable public record"

    differences = {"POSSIBLE_CONFLICT"}
    catalogue_gaps = {"MISSING_IN_CATALOGUE"}
    source_omissions = {"MISSING_IN_SOURCE"}
    difference_rows = _metadata_finding_rows(work_sources, records, differences)
    catalogue_gap_rows = _metadata_finding_rows(work_sources, records, catalogue_gaps)
    source_omission_rows = _metadata_finding_rows(work_sources, records, source_omissions)
    difference_sources = _metadata_source_ids(work_sources, records, differences)
    catalogue_gap_sources = _metadata_source_ids(work_sources, records, catalogue_gaps)
    source_omission_sources = _metadata_source_ids(work_sources, records, source_omissions)
    rights_recorded_rows = _rights_recorded_rows(work_sources, records)
    no_rights_rows = _no_rights_rows(work_sources, records)
    related_doi_rows = _related_doi_rows(work_sources, records)
    lookup_rows = _lookup_rows(work_sources, records)
    related_doi_sources = {
        source_id
        for source_id, _ in work_sources
        if (record := records.get(source_id))
        and record.get("lookup_status") == "OK"
        and record.get("related_dois")
    }
    rights_recorded_sources = {
        source_id
        for source_id, _ in work_sources
        if (record := records.get(source_id))
        and record["lookup_status"] == "OK"
        and record["rights"]["outcome"] == "RIGHTS_RECORDED"
    }
    no_rights_sources = {
        source_id
        for source_id, _ in work_sources
        if (record := records.get(source_id))
        and record["lookup_status"] == "OK"
        and record["rights"]["outcome"] != "RIGHTS_RECORDED"
    }
    clear_rows = [
        (
            f"| `{source_id}` | {_source_locator_link(source)} | "
            f"{_lookup_source_label(record)} | "
            "All comparable citation fields agree | "
            f"[{_md_cell(record['rights']['details'])}]({record['rights']['url']}) | "
            f"{_checked_record_link(record)} |"
        )
        for source_id, source in work_sources
        if (record := records.get(source_id, {})).get("status") == "AUTOMATED_CLEAR"
    ]
    lines = [
        "<!-- Generated by scripts/generate_registry_views.py; do not edit directly. -->",
        "# Source metadata and rights review",
        "",
        "Every catalogue entry whose role is `work` was evaluated by the rate-limited",
        "refresh recorded in",
        "[`source-review.json`](../../provenance/source-review.json). This snapshot uses "
        f"{lookup_summary}; it makes no legal determination about reuse.",
        "",
        f"Snapshot generated **{review['generated_at']}** · **{len(work_sources)}** works "
        "evaluated. Unchanged records are reused only while their own check date is within "
        "the refresh cache window.",
        "",
        "**Cited material** is the locator currently recorded by the atlas. **Lookup record** "
        "is the public record used for the automatic comparison, so both versions are one click "
        "away in every review table. Compared atlas and retrieved values are adjacent.",
        "",
        "## At a glance",
        "",
        "| Check | Result | Sources | Meaning |",
        "|---|---|---:|---|",
        f"| Metadata | Potential difference | {len(difference_sources)} | Compare the two values below. |",
        f"| Version | arXiv-associated DOI | {len(related_doi_sources)} | Confirm whether the cited preprint is intentional. |",
        f"| Metadata | Atlas citation incomplete | {len(catalogue_gap_sources)} | The queried record exposes a value the atlas citation does not. |",
        f"| Metadata | Source field not exposed | {len(source_omission_sources)} | The queried record does not provide a comparable value. |",
        f"| Rights / license | Rights or license signal found | {len(rights_recorded_sources)} | The public record exposed a license, publisher terms, or TDM link; it is not a reuse decision. |",
        f"| Rights / license | No machine-readable signal | {len(no_rights_sources)} | Neither the queried metadata record nor page exposed an explicit signal. |",
        f"| Retrieval | Locator or lookup gap | {len(lookup_rows)} | No metadata or rights result could be obtained. |",
        f"| Automated comparison | No automated follow-up | {len(clear_rows)} | All comparable citation values agree and a rights-related link was found; this is not permission to reuse. |",
        "",
        "## Potential metadata differences",
        "",
        "| Source | Cited material | Field | Atlas citation value | Retrieved-record value | Lookup source | Lookup record |",
        "|---|---|---|---|---|---|---|",
        *(difference_rows or ["| — | — | — | No potential metadata differences. | — | — | — |"]),
        "",
        "## Possible published versions of cited preprints",
        "",
        "An arXiv-associated DOI does not contradict the preprint identifier. It can point to a",
        "published version, so a person should decide whether the atlas deliberately cites the",
        "preprint or should cite that version instead.",
        "",
        "| Source | Cited material | DOI reported by arXiv | Human check | Lookup record |",
        "|---|---|---|---|---|",
        *(
            related_doi_rows
            or [
                "| — | — | — | arXiv did not report an associated DOI for a retrieved preprint. | — |"
            ]
        ),
        "",
        "## Values missing from the atlas citation",
        "",
        "| Source | Cited material | Field | Atlas citation value | Retrieved-record value | Lookup source | Lookup record |",
        "|---|---|---|---|---|---|---|",
        *(catalogue_gap_rows or ["| — | — | — | No additional values were exposed. | — | — | — |"]),
        "",
        "## Fields not exposed by the retrieved record",
        "",
        "| Source | Cited material | Field | Atlas citation value | Retrieved-record value | Lookup source | Lookup record |",
        "|---|---|---|---|---|---|---|",
        *(
            source_omission_rows
            or [
                "| — | — | — | Every retrieved record exposed its comparable fields. | — | — | — |"
            ]
        ),
        "",
        "## Rights and license metadata",
        "",
        "The table translates each public-record signal into a review label. A named license "
        "is named; a link to publisher terms or a text-and-data-mining policy is not relabelled "
        "as a general reuse license. Crossref's `vor` tag means version of record and `tdm` means "
        "text and data mining: they describe scope, not a license name.",
        "",
        "### Rights, licenses, and terms identified",
        "",
        "| Source | Cited material | Rights / license result | What the record establishes | Evidence |",
        "|---|---|---|---|---|",
        *(rights_recorded_rows or ["| — | — | — | No rights or license signals were found. | — |"]),
        "",
        "### No machine-readable rights or license signal",
        "",
        "This does **not** mean that a work has no rights or license; it means the queried",
        " metadata record or standardized page metadata did not expose one.",
        "",
        "| Source | Cited material | Lookup source | Lookup record |",
        "|---|---|---|---|",
        *(
            no_rights_rows
            or ["| — | — | — | Every retrieved record exposed a rights-related link. |"]
        ),
        "",
        f"The **{len(lookup_rows)}** sources whose records could not be retrieved or have no "
        "locator appear in [Retrieval and locator gaps](#retrieval-and-locator-gaps).",
        "",
        "## Retrieval and locator gaps",
        "",
        "| Source | Citation | Cited material | Finding |",
        "|---|---|---|---|",
        *(
            lookup_rows
            or ["| — | — | Every work record was retrieved and parsed. | — |"]
        ),
        "",
        "## Records with no automated follow-up",
        "",
        "These are the records for which the screen found neither a difference in a",
        "comparable citation field nor an absent rights-related link or associated DOI. This",
        "does **not** mean that the citation is approved or that reuse is permitted: a person",
        "still needs to interpret the link and can verify fields the public record does not expose.",
        "",
        "| Source | Cited material | Lookup source | Citation comparison | Rights-related link | Lookup record |",
        "|---|---|---|---|---|---|",
        *(
            clear_rows
            or [
                "| — | — | — | No record has both matching comparable citation values and a rights-related link. | — | — |"
            ]
        ),
        "",
        "## How to use this report",
        "",
        "Start with potential differences and possible published versions, then decide whether",
        "an exposed value should be added to the atlas citation. A missing source value often",
        "reflects the source's metadata format, not a defect. Inspect every rights-related link",
        "in context; the screen neither grants nor denies reuse permission. Re-run the refresh",
        "after correcting source data; it keeps complete coverage rather than using a manually",
        "maintained queue.",
        "",
    ]
    return "\n".join(lines)

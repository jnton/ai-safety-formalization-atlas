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


def _source_catalog_link(source_id: str, anchor_id: str = "") -> str:
    anchor = f'<a id="{anchor_id}"></a>' if anchor_id else ""
    return f"{anchor}[`{source_id}`](source-catalog.md#{source_id})"


def _work_source_row(
    source_id: str, source: dict, extra: str, anchor_id: str = ""
) -> str:
    return (
        f"| {_source_catalog_link(source_id, anchor_id)} | {_md_cell(_short_citation(source['citation']))} | "
        f"{_source_locator_link(source)} | {extra} |"
    )


def _checked_record_link(record: dict) -> str:
    checked_url = record.get("checked_url")
    if not checked_url:
        return "—"
    label = {
        "arxiv": "arXiv API",
        "crossref": "Crossref",
        "html": "Source page",
    }.get(record.get("provider", ""), "Queried record")
    return f"[{label}]({checked_url})"


def _arxiv_methods_links(record: dict, source: dict) -> str:
    links: list[str] = []
    if record.get("checked_url"):
        links.append(f"[arXiv API]({record['checked_url']})")
    locator = source.get("locator", "")
    if locator and "arxiv.org" in locator:
        links.append(f"[Abstract page](<{quote(locator, safe=':/?&=#%')}>)")
    return " · ".join(links) if links else _checked_record_link(record)


def _disposition_cell(
    source_id: str,
    finding_id: str,
    dispositions: dict | None,
) -> tuple[int, str]:
    """Return (sort_order, cell_markdown) where 0=pending (sorts first), 1=reviewed."""
    if not dispositions:
        return (0, "⏳ Pending review")
    source_disps = dispositions.get("dispositions", {}).get(source_id, {})
    disp = source_disps.get(finding_id)
    if disp and disp.get("status") == "REVIEWED_NO_CHANGE":
        reason = _md_cell(disp.get("reason", ""))
        reviewer = _md_cell(disp.get("reviewed_by", ""))
        date = _md_cell(disp.get("reviewed_on", ""))
        return (1, f"✅ **Reviewed (no change)**: *{reason}* (@{reviewer}, {date})")
    return (0, "⏳ Pending review")



def _metadata_finding_rows(
    work_sources: list[tuple[str, dict]],
    records: dict,
    outcomes: set[str],
    dispositions: dict | None = None,
    anchor_prefix: str = "",
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
    rows: list[tuple[int, int, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if not record or record["lookup_status"] != "OK":
            continue
        checked_record = _checked_record_link(record)
        for comparison in record["metadata"]:
            if comparison["outcome"] not in outcomes:
                continue
            fld = comparison["field"]
            anchor_id = f"{anchor_prefix}{source_id}-{fld}" if anchor_prefix else ""
            disp_order, disp_text = _disposition_cell(
                source_id, f"metadata:{fld}", dispositions
            )
            rows.append(
                (
                    disp_order,
                    field_order[fld],
                    source_id,
                    f"| {_source_catalog_link(source_id, anchor_id)} | {_source_locator_link(source)} | "
                    f"`{fld}` | "
                    f"{_md_cell(comparison['catalogue_value'])} | "
                    f"{_md_cell(comparison['source_value'])} | {checked_record} | {disp_text} |",
                )
            )
    return [row for _, _, _, row in sorted(rows)]


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

    if "(vor)" in details:
        scope = "vor"
    elif "(am)" in details:
        scope = "am"
    elif "(tdm)" in details or any(k in url for k in ("text-and-data-mining", "/tdm", "tdm_license")):
        scope = "tdm"
    elif "crossref rights metadata" in details:
        scope = "unspecified"
    else:
        scope = None

    if "creativecommons.org/licenses/by/4.0" in url or "cc by 4.0" in details:
        name = "CC BY 4.0 license"
        if "arxiv" in url or "arxiv" in details:
            return (
                0,
                name,
                "Per-paper CC BY 4.0 license link exposed on the arXiv abstract page.",
            )
        if scope == "vor":
            return (
                0,
                name,
                "Crossref surfaces a CC BY 4.0 license link for the version of record (vor).",
            )
        if scope == "am":
            return (
                0,
                name,
                "Crossref surfaces a CC BY 4.0 license link for the accepted manuscript (am).",
            )
        if scope == "tdm":
            return (
                2,
                name,
                "Crossref surfaces a CC BY 4.0 license link with text-and-data-mining (tdm) scope.",
            )
        if scope == "unspecified":
            return (
                0,
                name,
                "Crossref surfaces a CC BY 4.0 license link with unspecified version scope.",
            )
        return (0, name, f"The source page reports: {_md_cell(rights['details'])}")

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

    if scope == "tdm":
        return (
            2,
            "Text-and-data-mining terms",
            "Crossref marks this link for text and data mining (tdm); it is not identified as a general reuse license.",
        )

    policy_names = [
        ("acm.org/publications/policies/copyright_policy", "ACM copyright policy"),
        ("ieeexplore.ieee.org", "IEEE license information"),
        ("onlinelibrary.wiley.com/termsandconditions", "Wiley terms and conditions"),
        ("link.aps.org/licenses/aps-default-license", "APS default license"),
        ("publishingsupport.iopscience.iop.org/iop-standard", "IOP standard license"),
        ("cambridge.org/core/terms", "Cambridge Core terms"),
    ]
    for pattern, policy_name in policy_names:
        if pattern in url:
            if scope == "vor":
                return (
                    1,
                    policy_name,
                    "Crossref surfaces this link for the version of record (vor); check terms at the linked page.",
                )
            if scope == "am":
                return (
                    1,
                    policy_name,
                    "Crossref surfaces this link for the accepted manuscript (am); check terms at the linked page.",
                )
            return (
                3,
                policy_name,
                "Crossref surfaces this link with unspecified version scope; check terms at the linked page.",
            )

    if scope == "vor":
        return (
            1,
            "Publisher terms for the version of record",
            "Crossref marks this link for the version of record (vor); check terms at the linked page.",
        )
    if scope == "am":
        return (
            1,
            "Publisher terms for the accepted manuscript",
            "Crossref marks this link for the accepted manuscript (am); check terms at the linked page.",
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
        scope_text = _md_cell(scope)
        if rights.get("url"):
            scope_text += f" ([terms]({rights['url']}))"
        if record.get("provider") == "arxiv":
            checked_record = _arxiv_methods_links(record, source)
        else:
            checked_record = _checked_record_link(record)
        rows.append(
            (
                order,
                source_id,
                f"| {_source_catalog_link(source_id)} | {_source_locator_link(source)} | {result} | "
                f"{scope_text} | {checked_record} |",
            )
        )
    return [row for _, _, row in sorted(rows)]


def _no_rights_rows(
    work_sources: list[tuple[str, dict]],
    records: dict,
    dispositions: dict | None = None,
) -> list[str]:
    rows: list[tuple[int, str, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if (
            not record
            or record["lookup_status"] != "OK"
            or record["rights"]["outcome"] != "NO_EXPLICIT_RIGHTS"
        ):
            continue
        if record.get("provider") == "arxiv":
            checked_record = _arxiv_methods_links(record, source)
        else:
            checked_record = _checked_record_link(record)
        disp_order, disp_text = _disposition_cell(source_id, "rights", dispositions)
        rows.append(
            (
                disp_order,
                record.get("provider", ""),
                source_id,
                f"| {_source_catalog_link(source_id, f'rights-{source_id}')} | {_source_locator_link(source)} | "
                f"{checked_record} | {disp_text} |",
            )
        )
    return [row for _, _, _, row in sorted(rows)]


def _related_doi_rows(
    work_sources: list[tuple[str, dict]],
    records: dict,
    dispositions: dict | None = None,
) -> list[str]:
    """Surface an arXiv DOI without replacing the cited preprint identifier."""
    rows: list[tuple[int, str, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if not record or record.get("lookup_status") != "OK":
            continue
        for related in record.get("related_dois", []):
            doi = related["doi"]
            crossref_url = f"https://api.crossref.org/v1/works/{quote(doi, safe='')}"
            lookup_methods = f"{_checked_record_link(record)} · [Crossref]({crossref_url})"
            disp_order, disp_text = _disposition_cell(
                source_id, f"related_doi:{doi.lower()}", dispositions
            )
            rows.append(
                (
                    disp_order,
                    source_id,
                    doi,
                    f"| {_source_catalog_link(source_id, f'version-{source_id}')} | {_source_locator_link(source)} | "
                    f"[doi:{_md_cell(doi)}]({related['url']}) | "
                    f"{lookup_methods} | {disp_text} |",
                )
            )
    return [row for _, _, _, row in sorted(rows)]


def _lookup_rows(
    work_sources: list[tuple[str, dict]],
    records: dict,
    dispositions: dict | None = None,
) -> list[str]:
    status_order = {"MISSING_LOCATOR": 0, "HTTP_ERROR": 1, "PARSE_ERROR": 2}
    rows: list[tuple[int, int, str, str]] = []
    for source_id, source in work_sources:
        record = records.get(source_id)
        if not record or record["lookup_status"] == "OK":
            continue
        extra_note = _md_cell(record["notes"])
        if "Crossref returned HTTP 404; checked the source locator instead" in record.get("notes", ""):
            locator = source.get("locator", "")
            doi = ""
            for comp in record.get("metadata", []):
                if comp.get("field") == "identifier" and comp.get("catalogue_value", "").startswith("doi:"):
                    doi = comp["catalogue_value"][4:]
                    break
            links = []
            if doi:
                crossref_url = f"https://api.crossref.org/v1/works/{quote(doi, safe='')}"
                links.append(f"[Crossref]({crossref_url})")
            if locator:
                links.append(f"[Source page](<{quote(locator, safe=':/?&=#%')}>)")
            if links:
                extra_note += f" ({' · '.join(links)})"
        disp_order, disp_text = _disposition_cell(source_id, "lookup", dispositions)
        rows.append(
            (
                disp_order,
                status_order.get(record["lookup_status"], 99),
                source_id,
                _work_source_row(
                    source_id,
                    source,
                    f"`{record['lookup_status']}` · {extra_note} | {disp_text}",
                    anchor_id=f"gap-{source_id}",
                ),
            )
        )
    return [row for _, _, _, row in sorted(rows)]


def render_source_review(
    registry: dict, review: dict, dispositions: dict | None = None
) -> str:
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
    difference_rows = _metadata_finding_rows(
        work_sources, records, differences, dispositions=dispositions, anchor_prefix="diff-"
    )
    catalogue_gap_rows = _metadata_finding_rows(
        work_sources, records, catalogue_gaps, dispositions=dispositions, anchor_prefix="missing-cat-"
    )
    source_omission_rows = _metadata_finding_rows(
        work_sources, records, source_omissions, dispositions=dispositions, anchor_prefix="missing-src-"
    )
    rights_recorded_rows = _rights_recorded_rows(work_sources, records)
    no_rights_rows = _no_rights_rows(work_sources, records, dispositions=dispositions)
    related_doi_rows = _related_doi_rows(work_sources, records, dispositions=dispositions)
    lookup_rows = _lookup_rows(work_sources, records, dispositions=dispositions)

    def _counts(rows: list[str]) -> tuple[int, int, int]:
        total = len(rows)
        pending = sum(1 for r in rows if "⏳ Pending review" in r)
        reviewed = total - pending
        return total, pending, reviewed

    doi_tot, doi_pend, doi_rev = _counts(related_doi_rows)
    lookup_tot, lookup_pend, lookup_rev = _counts(lookup_rows)
    diff_tot, diff_pend, diff_rev = _counts(difference_rows)
    gap_tot, gap_pend, gap_rev = _counts(catalogue_gap_rows)
    no_rights_tot, no_rights_pend, no_rights_rev = _counts(no_rights_rows)
    omiss_tot, omiss_pend, omiss_rev = _counts(source_omission_rows)

    clear_rows = [
        (
            f"| {_source_catalog_link(source_id, f'clear-{source_id}')} | {_source_locator_link(source)} | "
            f"{_arxiv_methods_links(record, source) if record.get('provider') == 'arxiv' else _checked_record_link(record)} |"
        )
        for source_id, source in work_sources
        if (record := records.get(source_id, {})).get("status") in {"NO_AUTOMATED_FOLLOWUP", "AUTOMATED_CLEAR"}
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
        "| Check | Result | Total | Pending review | Reviewed (no change) | Meaning |",
        "|---|---|---:|---:|---:|---|",
        f"| Version | arXiv-associated DOI | {doi_tot} | {doi_pend} | {doi_rev} | Confirm whether the cited preprint is intentional. |",
        f"| Retrieval | Locator or lookup gap | {lookup_tot} | {lookup_pend} | {lookup_rev} | No metadata or rights result could be obtained. |",
        f"| Metadata | Potential difference | {diff_tot} | {diff_pend} | {diff_rev} | Compare the two values below. |",
        f"| Metadata | Atlas citation value not extracted | {gap_tot} | {gap_pend} | {gap_rev} | The queried record exposes a value not extracted from the atlas citation. |",
        f"| Rights / license | Rights or license signal found | {len(rights_recorded_rows)} | — | — | The public record exposed a license, publisher terms, or TDM link; it is not a reuse decision. |",
        f"| Rights / license | No machine-readable signal | {no_rights_tot} | {no_rights_pend} | {no_rights_rev} | Neither the queried metadata record nor page exposed an explicit signal. |",
        f"| Metadata | Source field not exposed | {omiss_tot} | {omiss_pend} | {omiss_rev} | The queried record does not provide a comparable value. |",
        f"| Automated comparison | No automated follow-up | {len(clear_rows)} | — | — | All comparable citation values agree and a rights-related link was found; this is not permission to reuse. |",
        "",
        "## Legend: Data retrieval methods",
        "",
        "The automated audit evaluates each catalogued work using one of three public retrieval methods based on its locator:",
        "",
        "- **Crossref API (`provider: crossref`)**: Used for sources with a DOI (`https://doi.org/...`). Queries the Crossref REST API for publisher metadata (title, authors, venue, volume, issue, pages, publication date) and registered license terms (`vor`, `am`, `tdm`, Creative Commons).",
        "- **arXiv API & Abstract Page (`provider: arxiv`)**: Used for sources citing arXiv preprints (`https://arxiv.org/abs/...`). Queries the official arXiv Export API for bibliographic metadata and associated journal DOIs, and inspects the abstract landing page for distribution licenses.",
        "- **Direct HTML & Document Headings (`provider: html`)**: Used for web URLs (institutional archives, book pages, GitHub documents). Fetches the public web page and extracts Dublin Core/Highwire metadata tags, `<article><h1>` document headings, and page titles, scanning for declared rights.",
        "- **Unretrieved / Missing Locator (`MISSING_LOCATOR`)**: Sources without a recorded locator in `registry.yaml` cannot be queried automatically.",
        "",
        "In all review tables, **Cited material** links to the locator currently recorded in the Atlas, while **Lookup record** links directly to the public API query or web page used for comparison.",
        "",
        "## Possible published versions of cited preprints",
        "",
        "An arXiv-associated DOI does not contradict the preprint identifier. It can point to a",
        "published version, so a person should decide whether the atlas deliberately cites the",
        "preprint or should cite that version instead.",
        "",
        "| Source | Cited material | DOI reported by arXiv | Lookup record | Human disposition |",
        "|---|---|---|---|---|",
        *(
            related_doi_rows
            or [
                "| — | — | — | arXiv did not report an associated DOI for a retrieved preprint. | — |"
            ]
        ),
        "",
        "## Retrieval and locator gaps",
        "",
        "| Source | Citation | Cited material | Finding | Human disposition |",
        "|---|---|---|---|---|",
        *(
            lookup_rows
            or ["| — | — | Every work record was retrieved and parsed. | — | — |"]
        ),
        "",
        "## Potential metadata differences",
        "",
        "| Source | Cited material | Field | Atlas citation value | Retrieved-record value | Lookup record | Human disposition |",
        "|---|---|---|---|---|---|---|",
        *(difference_rows or ["| — | — | — | No potential metadata differences. | — | — | — |"]),
        "",
        "## Values missing from the atlas citation",
        "",
        "| Source | Cited material | Field | Atlas citation value | Retrieved-record value | Lookup record | Human disposition |",
        "|---|---|---|---|---|---|---|",
        *(catalogue_gap_rows or ["| — | — | — | No additional values were exposed. | — | — | — |"]),
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
        "| Source | Cited material | Rights / license result | What the record establishes | Lookup record |",
        "|---|---|---|---|---|",
        *(rights_recorded_rows or ["| — | — | — | — | No rights or license signals were found. |"]),
        "",
        "### No machine-readable rights or license signal",
        "",
        "This does **not** mean that a work has no rights or license; it means the queried",
        " metadata record or standardized page metadata did not expose one.",
        "",
        "| Source | Cited material | Lookup record | Human disposition |",
        "|---|---|---|---|",
        *(
            no_rights_rows
            or ["| — | — | Every retrieved record exposed a rights-related link. | — |"]
        ),
        "",
        f"The **{len(lookup_rows)}** sources whose records could not be retrieved or have no "
        "locator appear in [Retrieval and locator gaps](#retrieval-and-locator-gaps).",
        "",
        "## Fields not exposed by the retrieved record",
        "",
        "| Source | Cited material | Field | Atlas citation value | Retrieved-record value | Lookup record | Human disposition |",
        "|---|---|---|---|---|---|---|",
        *(
            source_omission_rows
            or [
                "| — | — | — | Every retrieved record exposed its comparable fields. | — | — | — |"
            ]
        ),
        "",
        "## Records with no automated follow-up",
        "",
        "These are the records for which the screen found neither a difference in a",
        "comparable citation field nor an absent rights-related link or associated DOI. This",
        "does **not** mean that the citation is approved or that reuse is permitted: a person",
        "still needs to interpret the link and can verify fields the public record does not expose.",
        "",
        "| Source | Cited material | Lookup record |",
        "|---|---|---|",
        *(
            clear_rows
            or [
                "| — | — | No record has both matching comparable citation values and a rights-related link. |"
            ]
        ),
        "",
        "## How to use this report",
        "",
        "Start with possible published versions and retrieval gaps, then compare potential differences and decide whether",
        "an exposed value should be added to the atlas citation. Inspect every rights-related link",
        "in context; the screen neither grants nor denies reuse permission. A missing source value often",
        "reflects the source's metadata format, not a defect. Re-run the refresh",
        "after correcting source data; it keeps complete coverage rather than using a manually",
        "maintained queue.",
        "",
    ]
    return "\n".join(lines)

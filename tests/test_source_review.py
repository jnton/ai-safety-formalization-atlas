"""Regression tests for the complete, exception-first source audit."""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
REVIEW = "docs/provenance/source-review.json"


def _refresh_module():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("source_review")


def _registry() -> dict:
    return json.loads((ROOT / "registry.yaml").read_text(encoding="utf-8"))


def _example_source() -> dict:
    """A stable unit-test record, deliberately unrelated to the live catalogue."""
    return {
        "citation": (
            "A. Example, \u201cExample paper,\u201d Example Journal, vol. 8, no. 7, "
            "pp. 1391\u20131420, 2026, doi: 10.1000/example."
        ),
        "locator": "https://doi.org/10.1000/example",
        "role": "work",
    }


def _complete_failed_snapshot() -> dict:
    refresh = _refresh_module()
    sources = refresh.source_catalogue(_registry())
    records = {
        source_id: refresh.failed_record(
            source,
            "html",
            "HTTP_ERROR",
            "https://example.com/checked-record",
            "Synthetic lookup failure used only by this test.",
        )
        for source_id, source in sources.items()
    }
    return {
        "schema_version": refresh.SCHEMA_VERSION,
        "generated_at": "2026-08-31T12:00:00Z",
        "source_fingerprint": refresh.catalogue_fingerprint(sources),
        "records": records,
    }


def _run_validator(tmp_path: Path, review: dict) -> subprocess.CompletedProcess[str]:
    (tmp_path / "docs/provenance").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "registry.yaml", tmp_path / "registry.yaml")
    shutil.copy2(
        ROOT / "scripts/validate_source_review.py",
        tmp_path / "scripts/validate_source_review.py",
    )
    (tmp_path / REVIEW).write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return subprocess.run(
        [sys.executable, "scripts/validate_source_review.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def _crossref_message(title: str) -> dict:
    return {
        "DOI": "10.1000/example",
        "title": [title],
        "author": [{"given": "Ada", "family": "Example"}],
        "published-print": {"date-parts": [[2026, 8]]},
        "container-title": ["Example Journal"],
        "volume": "8",
        "issue": "7",
        "page": "1391-1420",
        "license": [
            {
                "URL": "https://example.com/license",
                "content-version": "vor",
            }
        ],
    }


def test_crossref_comparison_checks_core_metadata_and_rights() -> None:
    refresh = _refresh_module()
    source = _example_source()
    external = refresh.crossref_external(
        _crossref_message("Example paper")
    )
    comparisons = refresh.metadata_comparisons(
        source, external, True, source["locator"]
    )
    outcomes = {comparison["field"]: comparison["outcome"] for comparison in comparisons}

    assert outcomes["identifier"] == "MATCH"
    assert outcomes["title"] == "MATCH"
    assert outcomes["authors"] == "MATCH"
    assert outcomes["pages"] == "MATCH"
    assert external["rights"]["outcome"] == "RIGHTS_RECORDED"


def test_rights_presentation_names_a_license_without_overclaiming_terms() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from source_review import report as source_report

    cc_by = source_report._rights_presentation(
        {
            "details": "Crossref rights metadata (vor)",
            "url": "https://creativecommons.org/licenses/by/4.0/",
        }
    )
    tdm = source_report._rights_presentation(
        {
            "details": "Crossref rights metadata (tdm)",
            "url": "https://www.springer.com/tdm",
        }
    )
    version_of_record = source_report._rights_presentation(
        {
            "details": "Crossref rights metadata (vor)",
            "url": "https://www.acm.org/publications/policies/copyright_policy#Background",
        }
    )
    arxiv_distribution = source_report._rights_presentation(
        {
            "details": "Per-paper license link on the arXiv abstract page.",
            "url": "https://arxiv.org/licenses/nonexclusive-distrib/1.0/",
        }
    )
    assumed_arxiv_distribution = source_report._rights_presentation(
        {
            "details": "Per-paper license link on the arXiv abstract page.",
            "url": "https://arxiv.org/licenses/assumed-1991-2003/",
        }
    )

    assert cc_by[1] == "CC BY 4.0 license"
    assert "attribution" in cc_by[2]
    assert tdm[1] == "Text-and-data-mining terms"
    assert "not identified as a general reuse license" in tdm[2]
    assert version_of_record[1] == "ACM copyright policy"
    assert "no article-specific license name" in version_of_record[2]
    assert arxiv_distribution[1] == "arXiv non-exclusive distribution license"
    assert "not a general public reuse license" in arxiv_distribution[2]
    assert (
        assumed_arxiv_distribution[1]
        == "arXiv assumed distribution license (1991–2003)"
    )
    assert "not a general public reuse license" in assumed_arxiv_distribution[2]
    assert "%3C" in source_report._source_locator_link(
        {
            "locator": (
                "https://doi.org/10.1002/(SICI)1097-0312(199608)"
                "50:2<234::AID-CPA4>3.0.CO;2-8"
            )
        }
    )


def test_html_parser_uses_standard_citation_and_license_tags() -> None:
    refresh = _refresh_module()
    external = refresh.html_external(
        b"""<html><head>
        <meta name='citation_title' content='Example title'>
        <meta name='citation_author' content='Ada Lovelace'>
        <meta name='citation_publication_date' content='2026-08-31'>
        <meta name='citation_doi' content='10.1000/example'>
        <link rel='license' href='https://example.com/license'>
        </head><body></body></html>""",
        "https://example.com/paper",
    )

    assert external["title"] == "Example title"
    assert external["authors"] == ["Ada Lovelace"]
    assert external["identifier"] == "doi:10.1000/example"
    assert external["rights"]["outcome"] == "RIGHTS_RECORDED"


def test_doi_and_author_comparison_handle_ordinary_legacy_formats() -> None:
    refresh = _refresh_module()

    assert refresh.extract_doi(
        "doi: 10.1000/(SICI)1234-5678(199707)5:3<305::AID-EXAMPLE>3.0.CO;2-4"
    ) == "10.1000/(sici)1234-5678(199707)5:3<305::aid-example>3.0.co;2-4"
    assert (
        refresh.author_match(
            "S. Example and J. Sample", ["Example, Sam", "Sample, Jordan"]
        )
        == "MATCH"
    )
    assert (
        refresh.venue_match(
            "Proc. Example Math. Soc.",
            "Proceedings of the Example Mathematical Society",
        )
        == "MATCH"
    )
    assert refresh.citation_pages("P. Example, \u201cExample\u201d") == ""
    assert refresh.citation_pages("Example, pp. 44-48") == "44-48"


def test_reclassification_reuses_saved_values_without_requerying() -> None:
    refresh = _refresh_module()
    source = {
        "citation": "A. Example, \u201cExample paper,\u201d arXiv:1234.5678, 2026.",
        "locator": "https://arxiv.org/abs/1234.5678",
        "role": "work",
    }
    external = {
        "identifier": "arxiv:1234.5678",
        "title": "Example paper",
        "authors": ["Example, A."],
        "date": "2026-01-01",
        "venue": "",
        "volume_issue": "",
        "pages": "",
        "rights": {
            "outcome": "RIGHTS_RECORDED",
            "details": "Synthetic test license.",
            "url": "https://example.com/license",
        },
    }
    record = refresh.successful_record(
        source,
        "arxiv",
        refresh.arxiv_api_url("1234.5678"),
        "https://arxiv.org/abs/1234.5678",
        external,
    )
    for comparison in record["metadata"]:
        if comparison["field"] == "venue":
            comparison.update(
                {
                    "catalogue_value": "arXiv:1234.5678",
                    "outcome": "MISSING_IN_SOURCE",
                }
            )

    reclassified = refresh.reclassify_record(source, record)
    outcomes = {
        comparison["field"]: comparison["outcome"]
        for comparison in reclassified["metadata"]
    }

    assert outcomes["venue"] == "NOT_APPLICABLE"
    locator = next(
        comparison
        for comparison in reclassified["metadata"]
        if comparison["field"] == "locator"
    )
    assert locator["source_value"] == source["locator"]
    assert reclassified["checked_on"] == record["checked_on"]


def test_crossref_not_found_falls_back_to_the_public_locator(monkeypatch) -> None:
    refresh = _refresh_module()
    source = {
        "citation": "A. Example, \u201cExample paper,\u201d 2026, doi: 10.1000/example.",
        "locator": "https://doi.org/10.1000/example",
        "role": "work",
    }
    calls: list[str] = []

    def fake_fetch(url, *_args):
        calls.append(url)
        if "api.crossref.org" in url:
            return None, url, "HTTP 404"
        return (
            b"<html><head><meta name='citation_title' content='Example paper'>"
            b"<meta name='citation_author' content='Example, A.'></head></html>",
            "https://example.com/paper",
            "",
        )

    monkeypatch.setattr(refresh.lookups, "fetch", fake_fetch)
    args = SimpleNamespace(
        mailto=None,
        user_agent="test",
        timeout=1.0,
        max_bytes=1024,
        retries=0,
    )
    record = refresh.evaluate_source(source, args, refresh.HostRateLimiter(0, 0, 0))

    assert len(calls) == 2
    assert record["provider"] == "html"
    assert record["lookup_status"] == "OK"
    assert record["checked_url"] == "https://example.com/paper"
    assert "Crossref returned HTTP 404" in record["notes"]


def test_arxiv_lookup_preserves_the_preprint_identifier_and_license(monkeypatch) -> None:
    refresh = _refresh_module()
    source = {
        "citation": (
            "A. Example, “Example preprint,” arXiv:1234.5678, 2026, "
            "doi: 10.1000/published-version."
        ),
        "locator": "https://arxiv.org/abs/1234.5678",
        "role": "work",
    }
    calls: list[str] = []

    def fake_fetch(url, *_args):
        calls.append(url)
        if "export.arxiv.org" in url:
            return (
                b"""<feed xmlns='http://www.w3.org/2005/Atom'
                xmlns:arxiv='http://arxiv.org/schemas/atom'><entry>
                <id>http://arxiv.org/abs/1234.5678v2</id>
                <published>2026-08-31T12:00:00Z</published>
                <title>Example preprint</title>
                <author><name>Ada Example</name></author>
                <arxiv:journal_ref>Example Journal 8 (2026)</arxiv:journal_ref>
                <arxiv:doi>10.1000/published-version</arxiv:doi>
                </entry></feed>""",
                url,
                "",
            )
        return (
            b"<html><body><a href='/licenses/nonexclusive-distrib/1.0/'>"
            b"view license</a></body></html>",
            source["locator"],
            "",
        )

    monkeypatch.setattr(refresh.lookups, "fetch", fake_fetch)
    args = SimpleNamespace(
        mailto=None,
        user_agent="test",
        timeout=1.0,
        max_bytes=1024,
        retries=0,
    )
    record = refresh.evaluate_source(source, args, refresh.HostRateLimiter(0, 0, 0))
    outcomes = {comparison["field"]: comparison["outcome"] for comparison in record["metadata"]}

    assert calls == [refresh.arxiv_api_url("1234.5678"), source["locator"]]
    assert record["provider"] == "arxiv"
    assert record["checked_url"] == refresh.arxiv_api_url("1234.5678")
    assert outcomes["identifier"] == "MATCH"
    assert record["rights"] == {
        "outcome": "RIGHTS_RECORDED",
        "details": "Per-paper license link on the arXiv abstract page.",
        "url": "https://arxiv.org/licenses/nonexclusive-distrib/1.0/",
    }
    assert record["related_dois"] == [
        {
            "doi": "10.1000/published-version",
            "url": "https://doi.org/10.1000/published-version",
        }
    ]
    assert record["status"] == "NEEDS_HUMAN"


def test_arxiv_lookup_invalidates_legacy_html_cache() -> None:
    refresh = _refresh_module()
    source = {
        "citation": "A. Example, “Example preprint,” arXiv:1234.5678, 2026.",
        "locator": "https://arxiv.org/abs/1234.5678",
        "role": "work",
    }

    assert not refresh.cached_record_is_compatible(
        source, {"provider": "html", "notes": "", "related_dois": []}
    )
    assert refresh.cached_record_is_compatible(
        source,
        {
            "provider": "html",
            "notes": "arXiv API lookup failed (HTTP 503); checked the source locator instead.",
            "related_dois": [],
        },
    )
    assert refresh.cached_record_is_compatible(
        source, {"provider": "arxiv", "notes": "", "related_dois": []}
    )


def test_complete_snapshot_is_accepted_and_a_missing_source_is_not(tmp_path: Path) -> None:
    snapshot = _complete_failed_snapshot()
    accepted = _run_validator(tmp_path / "accepted", snapshot)
    assert accepted.returncode == 0, accepted.stderr + accepted.stdout

    arxiv_provider = copy.deepcopy(snapshot)
    next(iter(arxiv_provider["records"].values()))["provider"] = "arxiv"
    accepted_arxiv = _run_validator(tmp_path / "accepted-arxiv", arxiv_provider)
    assert accepted_arxiv.returncode == 0, accepted_arxiv.stderr + accepted_arxiv.stdout

    incomplete = copy.deepcopy(snapshot)
    incomplete["records"].pop(next(iter(incomplete["records"])))
    rejected = _run_validator(tmp_path / "incomplete", incomplete)
    output = rejected.stderr + rejected.stdout
    assert rejected.returncode != 0, output
    assert "must evaluate every work source" in output


def test_review_board_shows_machine_findings_not_a_manual_unreviewed_queue() -> None:
    refresh = _refresh_module()
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_registry_views as views

    registry = _registry()
    snapshot = _complete_failed_snapshot()
    source_id, source = next(
        (source_id, source)
        for source_id, source in sorted(refresh.source_catalogue(registry).items())
        if refresh.extract_title(source["citation"])
    )
    external = refresh.crossref_external(_crossref_message("Different title"))
    comparisons = refresh.metadata_comparisons(
        source, external, True, source.get("locator", "")
    )
    rights = external["rights"]
    related_dois = [
        {
            "doi": "10.1000/example",
            "url": "https://doi.org/10.1000/example",
        }
    ]
    snapshot["records"][source_id] = {
        "input_fingerprint": refresh.input_fingerprint(source),
        "provider": "crossref",
        "lookup_status": "OK",
        "checked_url": refresh.crossref_url("10.1000/example", None),
        "checked_on": "2026-08-31T12:00:00Z",
        "metadata": comparisons,
        "rights": rights,
        "related_dois": related_dois,
        "status": refresh.classify("OK", comparisons, rights, related_dois),
        "notes": "",
    }
    report = views.render_source_review(registry, snapshot)

    assert f"**{len(refresh.source_catalogue(registry))}** works evaluated" in report
    assert "## Rights and license metadata" in report
    assert "### Rights, licenses, and terms identified" in report
    assert "| Source | Cited material | Rights / license result | What the record establishes | Evidence |" in report
    assert "## Potential metadata differences" in report
    assert (
        "| Source | Cited material | Field | Atlas citation value | "
        "Retrieved-record value | Lookup source | Lookup record |"
    ) in report
    assert "| [open](<" in report
    assert f"| `{source_id}` |" in report
    assert "| `title` |" in report
    assert "## Possible published versions of cited preprints" in report
    assert "doi:10.1000/example" in report
    assert "Publisher terms for the version of record" in report
    assert "Different title" in report
    assert "Not yet reviewed" not in report
    assert "Evidence says" not in report
    assert "Checked value" not in report
    assert "Crossref rights metadata" not in report

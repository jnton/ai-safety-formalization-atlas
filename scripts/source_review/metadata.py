"""Small parsers for Crossref, public HTML pages, and arXiv Atom records."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urlencode, urljoin
from xml.etree import ElementTree

from .schema import (
    NO_EXPLICIT_RIGHTS,
    RIGHTS_RECORDED,
    arxiv_base_id,
    clean_doi,
    display,
    extract_arxiv_id,
    extract_doi,
    strip_html,
)


def date_from_parts(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return ""
    numbers = [str(part) for part in parts[0][:3] if isinstance(part, int)]
    return "-".join(numbers)


def first_text(value: object) -> str:
    if isinstance(value, list):
        return strip_html(value[0]) if value else ""
    return strip_html(value)


def crossref_external(message: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for author in message.get("author", []):
        if not isinstance(author, dict):
            continue
        name = " ".join(
            value
            for value in (author.get("given", ""), author.get("family", ""))
            if isinstance(value, str) and value.strip()
        )
        if not name and isinstance(author.get("name"), str):
            name = author["name"]
        if name:
            authors.append(name)
    date = ""
    for key in ("published-print", "published-online", "issued", "created"):
        date = date_from_parts(message.get(key))
        if date:
            break
    licenses = [
        license_ for license_ in message.get("license", []) if isinstance(license_, dict)
    ]
    if licenses and isinstance(licenses[0].get("URL"), str):
        license_ = licenses[0]
        details = "Crossref rights metadata"
        if isinstance(license_.get("content-version"), str):
            details += f" ({license_['content-version']})"
        rights = {
            "outcome": RIGHTS_RECORDED,
            "details": details,
            "url": license_["URL"],
        }
    else:
        rights = {
            "outcome": NO_EXPLICIT_RIGHTS,
            "details": "Crossref returned no explicit license or rights metadata.",
            "url": "",
        }
    doi = message.get("DOI") if isinstance(message.get("DOI"), str) else ""
    return {
        "identifier": f"doi:{clean_doi(doi)}" if doi else "",
        "title": first_text(message.get("title")),
        "authors": authors,
        "date": date,
        "venue": first_text(message.get("container-title")),
        "volume_issue": ", ".join(
            f"{label} {message[key]}"
            for key, label in (("volume", "vol."), ("issue", "no."))
            if isinstance(message.get(key), str) and message[key].strip()
        ),
        "pages": display(message.get("page")) if message.get("page") else "",
        "rights": rights,
    }


class MetadataHTMLParser(HTMLParser):
    """A deliberately narrow extractor for widely used citation and rights tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.licenses: list[str] = []
        self.license_anchors: list[tuple[str, str]] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "meta":
            key = (values.get("name") or values.get("property") or "").casefold()
            content = values.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, []).append(content)
        elif tag.casefold() == "link":
            rel = values.get("rel", "").casefold().split()
            href = values.get("href", "").strip()
            if "license" in rel and href:
                self.licenses.append(href)
        elif tag.casefold() == "a":
            href = values.get("href", "").strip()
            if href:
                self._anchor_href = href
                self._anchor_parts = []
        elif tag.casefold() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._anchor_href:
            label = " ".join(part.strip() for part in self._anchor_parts if part.strip())
            if "license" in label.casefold() or "/licenses/" in self._anchor_href.casefold():
                self.license_anchors.append((label, self._anchor_href))
            self._anchor_href = None
            self._anchor_parts = []
        elif tag.casefold() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._anchor_href:
            self._anchor_parts.append(data)

    def first(self, *keys: str) -> str:
        for key in keys:
            values = self.meta.get(key.casefold(), [])
            if values:
                return strip_html(values[0])
        return ""

    def all(self, *keys: str) -> list[str]:
        values: list[str] = []
        for key in keys:
            values.extend(
                strip_html(value) for value in self.meta.get(key.casefold(), [])
            )
        return list(dict.fromkeys(value for value in values if value))


def parse_source_html(body: bytes) -> MetadataHTMLParser:
    parser = MetadataHTMLParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def html_rights(parser: MetadataHTMLParser, final_url: str) -> dict[str, str]:
    """Extract an explicit rights signal, including a visible license link."""
    rights_text = parser.first(
        "citation_license", "dc.rights", "dcterms.rights", "rights", "license"
    )
    link_label = ""
    raw_url = ""
    if parser.licenses:
        raw_url = parser.licenses[0]
    elif parser.license_anchors:
        link_label, raw_url = parser.license_anchors[0]
    rights_url = urljoin(final_url, raw_url) if raw_url else ""
    if rights_text or rights_url:
        details = rights_text
        if not details and link_label:
            details = f"Explicit license link on source page ({link_label})."
        if not details:
            details = "Explicit license link in source HTML."
        return {
            "outcome": RIGHTS_RECORDED,
            "details": details,
            "url": rights_url or final_url,
        }
    return {
        "outcome": NO_EXPLICIT_RIGHTS,
        "details": "No explicit rights or license metadata was found in the source HTML.",
        "url": final_url,
    }


def html_external(body: bytes, final_url: str) -> dict[str, Any]:
    parser = parse_source_html(body)
    title = parser.first("citation_title", "dc.title", "dcterms.title", "og:title")
    if not title:
        title = " ".join(part.strip() for part in parser.title_parts if part.strip())
    raw_doi = parser.first("citation_doi", "dc.identifier.doi")
    doi = extract_doi(raw_doi) or clean_doi(raw_doi)
    arxiv_id = extract_arxiv_id(final_url)
    identifier = f"doi:{clean_doi(doi)}" if doi else f"arxiv:{arxiv_id}" if arxiv_id else ""
    first_page = parser.first("citation_firstpage")
    last_page = parser.first("citation_lastpage")
    pages = "–".join(value for value in (first_page, last_page) if value)
    return {
        "identifier": identifier,
        "title": title,
        "authors": parser.all("citation_author", "dc.creator", "dcterms.creator", "author"),
        "date": parser.first(
            "citation_publication_date",
            "citation_date",
            "dc.date",
            "dcterms.issued",
            "article:published_time",
        ),
        "venue": parser.first("citation_journal_title", "citation_conference_title", "dc.source"),
        "volume_issue": ", ".join(
            f"{label} {value}"
            for label, value in (
                ("vol.", parser.first("citation_volume")),
                ("no.", parser.first("citation_issue")),
            )
            if value
        ),
        "pages": pages,
        "rights": html_rights(parser, final_url),
    }


ATOM_NAMESPACE = "{http://www.w3.org/2005/Atom}"
ARXIV_NAMESPACE = "{http://arxiv.org/schemas/atom}"


def arxiv_api_url(arxiv_id: str) -> str:
    return "https://export.arxiv.org/api/query?" + urlencode({"id_list": arxiv_id})


def xml_text(element: ElementTree.Element, path: str) -> str:
    value = element.findtext(path)
    return " ".join(strip_html(value).split()) if isinstance(value, str) else ""


def arxiv_metadata(body: bytes, requested_id: str) -> tuple[dict[str, Any], str]:
    """Parse arXiv Atom metadata while keeping the cited preprint as primary."""
    root = ElementTree.fromstring(body)
    entry = root.find(f"{ATOM_NAMESPACE}entry")
    if entry is None:
        raise ValueError("arXiv API response contains no entry")
    returned_id = extract_arxiv_id(xml_text(entry, f"{ATOM_NAMESPACE}id"))
    if returned_id and arxiv_base_id(returned_id) != arxiv_base_id(requested_id):
        raise ValueError("arXiv API response identifies a different preprint")
    authors = [
        name
        for author in entry.findall(f"{ATOM_NAMESPACE}author")
        if (name := xml_text(author, f"{ATOM_NAMESPACE}name"))
    ]
    journal_ref = xml_text(entry, f"{ARXIV_NAMESPACE}journal_ref")
    associated_doi = clean_doi(xml_text(entry, f"{ARXIV_NAMESPACE}doi"))
    related_dois = []
    if associated_doi:
        related_dois.append(
            {
                "doi": associated_doi,
                "url": "https://doi.org/" + quote(associated_doi, safe="/"),
            }
        )
    return (
        {
            "identifier": f"arxiv:{requested_id}",
            "title": xml_text(entry, f"{ATOM_NAMESPACE}title"),
            "authors": authors,
            "date": xml_text(entry, f"{ATOM_NAMESPACE}published"),
            "venue": journal_ref,
            "volume_issue": "",
            "pages": "",
            "related_dois": related_dois,
        },
        "",
    )


def arxiv_rights(abstract_body: bytes, abstract_url: str) -> dict[str, str]:
    """Read arXiv's visible, per-paper ``view license`` link when it exists."""
    parser = parse_source_html(abstract_body)
    if parser.license_anchors:
        _, raw_url = parser.license_anchors[0]
        return {
            "outcome": RIGHTS_RECORDED,
            "details": "Per-paper license link on the arXiv abstract page.",
            "url": urljoin(abstract_url, raw_url),
        }
    return {
        "outcome": NO_EXPLICIT_RIGHTS,
        "details": "The arXiv abstract page did not expose a per-paper license link.",
        "url": abstract_url,
    }

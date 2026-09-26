from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import html
from pathlib import Path
import re
import time

import requests

from core.config import Settings
from core.utils import normalize_whitespace, read_json, write_json

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30

_JATS_TITLE_RE = re.compile(r"<jats:title[^>]*>.*?</jats:title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


class SourceUnavailableError(RuntimeError):
    """Crossref khong tra ve payload hop le sau khi da retry."""


def strip_markup(value: str) -> str:
    """Bo the JATS/HTML (vd `<jats:p>`), decode HTML entity va chuan hoa khoang trang."""
    without_titles = _JATS_TITLE_RE.sub(" ", value)
    return normalize_whitespace(html.unescape(_TAG_RE.sub(" ", without_titles)))


def _first_text(value: object) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return strip_markup(str(value or ""))


def _date_from_parts(block: dict | None) -> str:
    parts = ((block or {}).get("date-parts") or [[]])[0]
    if not parts or parts[0] is None:
        return ""
    year, month, day = (list(parts) + [1, 1])[:3]
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _published_date(item: dict) -> str:
    for key in ("published", "published-online", "published-print", "issued", "created"):
        date = _date_from_parts(item.get(key))
        if date:
            return date
    return ""


def _updated_date(item: dict, published: str) -> str:
    for key in ("deposited", "created"):
        date_time = (item.get(key) or {}).get("date-time")
        if date_time:
            return str(date_time)[:10]
    return published


def _authors(item: dict) -> list[str]:
    names = []
    for author in item.get("author") or []:
        name = normalize_whitespace(f"{author.get('given', '')} {author.get('family', '')}")
        name = name or normalize_whitespace(str(author.get("name", "")))
        if name:
            names.append(name)
    return names


def _pdf_url(item: dict, fallback: str) -> str:
    for link in item.get("link") or []:
        if "pdf" in str(link.get("content-type", "")).lower() and link.get("URL"):
            return str(link["URL"])
    return fallback


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse payload `/works` cua Crossref thanh list `PaperRecord`.

    Bo record thieu DOI, title, abstract hoac ngay xuat ban vi cac buoc sau
    (embedding, freshness) khong the dung chung. Khu trung lap de o buoc cleaning.
    """
    records: list[PaperRecord] = []
    for item in (payload.get("message") or {}).get("items") or []:
        paper_id = normalize_whitespace(str(item.get("DOI", "")))
        title = _first_text(item.get("title"))
        summary = strip_markup(str(item.get("abstract") or ""))
        published = _published_date(item)
        if not (paper_id and title and summary and published):
            continue

        categories = [strip_markup(str(subject)) for subject in item.get("subject") or []]
        categories = [category for category in categories if category]
        abs_url = str(item.get("URL") or f"https://doi.org/{paper_id}")
        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=summary,
                authors=_authors(item),
                categories=categories,
                primary_category=categories[0] if categories else "",
                published=published,
                updated=_updated_date(item, published),
                abs_url=abs_url,
                pdf_url=_pdf_url(item, abs_url),
                comment=f"Crossref record {paper_id}",
            )
        )
    return records


def _request_crossref(settings: Settings) -> dict:
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
        "sort": "published",
        "order": "desc",
    }
    headers = {"User-Agent": "day10-data-observability-lab/0.1 (VinUni coursework)"}
    last_error = "no attempt made"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                CROSSREF_WORKS_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 200:
                payload = response.json()
                if payload.get("status") == "ok":
                    return payload
                last_error = f"unexpected payload status {payload.get('status')!r}"
            elif response.status_code in RETRY_STATUS_CODES:
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < MAX_ATTEMPTS:
                    time.sleep(min(int(retry_after), 60))
                    continue
            else:
                raise SourceUnavailableError(f"Crossref returned HTTP {response.status_code}")
        if attempt < MAX_ATTEMPTS:
            time.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))
    raise SourceUnavailableError(f"Crossref unavailable after {MAX_ATTEMPTS} attempts ({last_error})")


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Lay raw payload (API hoac snapshot), luu 2 raw artifact va tra ve records.

    - Mac dinh dung snapshot `data/raw/crossref_response.json` neu da co (lineage anchor,
      tai lap duoc, khong ton rate limit).
    - `REFRESH_SOURCE=1` hoac chua co snapshot -> goi Crossref API voi retry/backoff;
      neu API loi (mat mang, 429/503 sau khi retry) va co snapshot thi fallback ve snapshot.
    """
    snapshot_path = settings.paths.raw_api_response
    payload: dict | None = None

    if settings.refresh_source or not snapshot_path.exists():
        try:
            payload = _request_crossref(settings)
            write_json(snapshot_path, payload)
            print(f"[crossref] Fetched live payload from {CROSSREF_WORKS_URL}")
        except SourceUnavailableError as exc:
            if not snapshot_path.exists():
                raise
            print(f"[crossref] {exc}; falling back to local snapshot {snapshot_path.name}")

    if payload is None:
        payload = read_json(snapshot_path)
        print(f"[crossref] Loaded snapshot {snapshot_path.name}")

    records = parse_crossref_payload(payload)
    write_json(settings.paths.raw_records_json, [asdict(record) for record in records])
    return records


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Doc `crossref_records.json` va map lai thanh `PaperRecord`."""
    known_fields = {field.name for field in fields(PaperRecord)}
    return [PaperRecord(**{key: value for key, value in item.items() if key in known_fields}) for item in read_json(path)]

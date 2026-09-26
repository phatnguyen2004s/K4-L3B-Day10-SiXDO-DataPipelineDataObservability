from __future__ import annotations

from dataclasses import asdict, replace
import json

import pytest
import requests

from conftest import PROJECT_DIR
from core.utils import read_json
from ingestion import crossref
from ingestion.crossref import (
    SourceUnavailableError,
    fetch_source_records,
    load_raw_records,
    parse_crossref_payload,
    strip_markup,
)

SNAPSHOT = PROJECT_DIR / "data" / "raw" / "crossref_response.json"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


def test_parse_snapshot_matches_reference_records():
    records = parse_crossref_payload(read_json(SNAPSHOT))
    reference = read_json(PROJECT_DIR / "data" / "raw" / "crossref_records.json")
    assert len(records) == 24
    assert [asdict(record) for record in records] == reference


def test_strip_markup_removes_jats_and_entities():
    raw = "<jats:title>Abstract</jats:title><jats:p>RAG &amp; agents\n   work</jats:p>"
    assert strip_markup(raw) == "RAG & agents work"


def test_parse_drops_invalid_and_handles_fallback_fields():
    payload = {
        "message": {
            "items": [
                {"DOI": "10.1/no-title", "title": [], "abstract": "x", "published": {"date-parts": [[2026, 1, 1]]}},
                {"DOI": "10.1/no-abstract", "title": ["T"], "published": {"date-parts": [[2026, 1, 1]]}},
                {"DOI": "10.1/no-date", "title": ["T"], "abstract": "x"},
                {
                    "DOI": "10.1/ok",
                    "title": ["  A   <i>title</i> "],
                    "abstract": "<jats:p>Body</jats:p>",
                    "issued": {"date-parts": [[2026, 3]]},
                    "deposited": {"date-time": "2026-04-02T00:00:00Z"},
                    "author": [{"name": "OpenAI Team"}, {"given": "", "family": ""}],
                    "subject": ["AI", ""],
                    "link": [{"content-type": "application/pdf", "URL": "https://x/pdf"}],
                },
            ]
        }
    }
    records = parse_crossref_payload(payload)
    assert len(records) == 1
    record = records[0]
    assert record.title == "A title"
    assert record.published == "2026-03-01"
    assert record.updated == "2026-04-02"
    assert record.authors == ["OpenAI Team"]
    assert record.categories == ["AI"]
    assert record.primary_category == "AI"
    assert record.abs_url == "https://doi.org/10.1/ok"
    assert record.pdf_url == "https://x/pdf"


def test_fetch_uses_snapshot_by_default(settings, monkeypatch):
    monkeypatch.setattr(crossref.requests, "get", lambda *a, **k: pytest.fail("API must not be called"))
    records = fetch_source_records(settings)
    assert len(records) == 24
    assert len(read_json(settings.paths.raw_records_json)) == 24


def test_fetch_live_retries_on_429_then_saves_raw(settings, monkeypatch):
    payload = read_json(SNAPSHOT)
    responses = [FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(503), FakeResponse(200, payload)]
    calls = []
    monkeypatch.setattr(crossref.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(crossref.requests, "get", lambda *a, **k: calls.append(k["params"]) or responses.pop(0))
    settings.paths.raw_api_response.unlink()

    records = fetch_source_records(replace(settings, refresh_source=True))

    assert len(calls) == 3
    assert calls[0]["rows"] == settings.max_results
    assert len(records) == 24
    assert read_json(settings.paths.raw_api_response) == payload


def test_fetch_falls_back_to_snapshot_when_api_down(settings, monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(crossref.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(crossref.requests, "get", boom)
    snapshot_before = settings.paths.raw_api_response.read_bytes()

    records = fetch_source_records(replace(settings, refresh_source=True))

    assert len(records) == 24
    assert settings.paths.raw_api_response.read_bytes() == snapshot_before


def test_fetch_raises_without_snapshot_on_client_error(settings, monkeypatch):
    monkeypatch.setattr(crossref.requests, "get", lambda *a, **k: FakeResponse(400))
    settings.paths.raw_api_response.unlink()
    with pytest.raises(SourceUnavailableError, match="HTTP 400"):
        fetch_source_records(settings)


def test_fetch_rejects_unexpected_payload_status(settings, monkeypatch):
    monkeypatch.setattr(crossref.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(crossref.requests, "get", lambda *a, **k: FakeResponse(200, {"status": "failed"}))
    settings.paths.raw_api_response.unlink()
    with pytest.raises(SourceUnavailableError, match="unexpected payload status"):
        fetch_source_records(settings)


def test_load_raw_records_ignores_unknown_fields(tmp_path):
    path = tmp_path / "records.json"
    item = read_json(PROJECT_DIR / "data" / "raw" / "crossref_records.json")[0] | {"extra": 1}
    path.write_text(json.dumps([item]))
    assert load_raw_records(path)[0].paper_id == item["paper_id"]

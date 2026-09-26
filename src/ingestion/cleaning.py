from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from core.utils import compact_join, normalize_whitespace, write_csv, write_json
from ingestion.crossref import PaperRecord, strip_markup

CLEAN_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors",
    "categories",
    "primary_category",
    "published",
    "updated",
    "abs_url",
    "pdf_url",
    "comment",
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "age_days",
    "text_for_embedding",
]


def _clean_list(values: list[str] | None) -> list[str]:
    """Chuan hoa tung phan tu, bo rong va bo trung (giu thu tu)."""
    cleaned: list[str] = []
    for value in values or []:
        item = strip_markup(str(value))
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _parse_date(value: object) -> date | None:
    parsed = pd.to_datetime(str(value or "").strip(), errors="coerce", utc=True)
    return None if pd.isna(parsed) else parsed.date()


def build_text_for_embedding(row: dict | pd.Series) -> str:
    """Ghep 5 phan Title/Authors/Published/Categories/Summary; dung lai khi corruption/repair."""
    return "\n".join(
        [
            f"Title: {row['title']}",
            f"Authors: {row['authors_joined']}",
            f"Published: {row['published']}",
            f"Categories: {row['categories_joined']}",
            f"Summary: {row['summary']}",
        ]
    )


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Clean raw records thanh dataframe san sang de embed.

    - Chuan hoa text (bo the JATS/HTML, khoang trang thua), authors/categories.
    - Parse published/updated ve chuoi ISO `YYYY-MM-DD` (Chroma metadata chi nhan scalar).
    - `age_days = (run_date - published).days`.
    - Loai row thieu paper_id/title/summary/published hop le.
    - Khu trung lap theo `paper_id` (DOI khong phan biet hoa thuong), giu ban `updated` moi nhat.
    """
    run_day = run_date.date()
    rows = []
    for record in records:
        raw = asdict(record) if isinstance(record, PaperRecord) else dict(record)
        published = _parse_date(raw.get("published"))
        updated = _parse_date(raw.get("updated")) or published
        authors = _clean_list(raw.get("authors"))
        categories = _clean_list(raw.get("categories"))
        row = {
            "paper_id": normalize_whitespace(str(raw.get("paper_id") or "")),
            "title": strip_markup(str(raw.get("title") or "")),
            "summary": strip_markup(str(raw.get("summary") or "")),
            "authors": authors,
            "categories": categories,
            "primary_category": strip_markup(str(raw.get("primary_category") or "")) or (categories[0] if categories else ""),
            "published": published.isoformat() if published else "",
            "updated": updated.isoformat() if updated else "",
            "abs_url": normalize_whitespace(str(raw.get("abs_url") or "")),
            "pdf_url": normalize_whitespace(str(raw.get("pdf_url") or "")),
            "comment": normalize_whitespace(str(raw.get("comment") or "")),
            "authors_joined": compact_join(authors),
            "categories_joined": compact_join(categories),
            "age_days": (run_day - published).days if published else None,
        }
        if not (row["paper_id"] and row["title"] and row["summary"] and row["published"]):
            continue
        row["summary_chars"] = len(row["summary"])
        row["text_for_embedding"] = build_text_for_embedding(row)
        rows.append(row)

    df = pd.DataFrame(rows, columns=CLEAN_COLUMNS)
    if df.empty:
        return df

    df["_dedupe_key"] = df["paper_id"].str.lower()
    df = (
        df.sort_values(["updated", "published"], ascending=False, kind="stable")
        .drop_duplicates(subset="_dedupe_key", keep="first")
        .drop(columns="_dedupe_key")
    )
    df["age_days"] = df["age_days"].astype(int)
    df["summary_chars"] = df["summary_chars"].astype(int)
    return df.sort_values(["published", "paper_id"], ascending=[False, True], kind="stable").reset_index(drop=True)


def save_clean_dataframe(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    """Luu clean dataset ra CSV (list duoc noi bang '; ') va JSON records (giu nguyen list)."""
    csv_df = df.copy()
    for column in ("authors", "categories"):
        csv_df[column] = csv_df[column].map(lambda values: "; ".join(values))
    write_csv(csv_df, csv_path)
    write_json(json_path, df.to_dict(orient="records"))

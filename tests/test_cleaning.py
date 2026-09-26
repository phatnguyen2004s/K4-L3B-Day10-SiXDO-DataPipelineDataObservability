from __future__ import annotations

from dataclasses import replace

import pandas as pd

from conftest import RUN_DATE
from ingestion.cleaning import CLEAN_COLUMNS, build_clean_dataframe, save_clean_dataframe


def test_clean_dataframe_schema_and_rows(clean_df):
    assert len(clean_df) == 24
    assert list(clean_df.columns) == CLEAN_COLUMNS
    assert clean_df["paper_id"].is_unique
    assert clean_df["published"].is_monotonic_decreasing


def test_age_days_and_text_for_embedding(clean_df):
    row = clean_df.iloc[0]
    expected_age = (RUN_DATE.date() - pd.Timestamp(row["published"]).date()).days
    assert row["age_days"] == expected_age
    lines = row["text_for_embedding"].split("\n")
    assert [line.split(":")[0] for line in lines] == ["Title", "Authors", "Published", "Categories", "Summary"]
    assert lines[1] == f"Authors: {row['authors_joined']}"
    assert row["summary_chars"] == len(row["summary"])


def test_dedupe_by_paper_id_keeps_latest_update(raw_records):
    first = raw_records[0]
    older = replace(first, paper_id=first.paper_id.upper(), title="Old title", updated="2000-01-01")
    df = build_clean_dataframe([older, *raw_records], RUN_DATE)
    assert len(df) == 24
    assert df.loc[df["paper_id"].str.lower() == first.paper_id.lower(), "title"].item() == first.title


def test_invalid_rows_are_dropped_and_text_normalized(raw_records):
    base = raw_records[0]
    records = [
        replace(base, paper_id="blank-summary", summary="   "),
        replace(base, paper_id="bad-date", published="not-a-date"),
        replace(base, paper_id="messy", title="  <b>Messy</b>   title ", authors=["A  B", "A B", ""], categories=[]),
    ]
    df = build_clean_dataframe(records, RUN_DATE)
    assert df["paper_id"].tolist() == ["messy"]
    row = df.iloc[0]
    assert row["title"] == "Messy title"
    assert row["authors"] == ["A B"]
    assert row["categories_joined"] == ""


def test_empty_input_returns_empty_frame():
    df = build_clean_dataframe([], RUN_DATE)
    assert df.empty
    assert list(df.columns) == CLEAN_COLUMNS


def test_save_clean_dataframe_roundtrip(clean_df, tmp_path):
    csv_path, json_path = tmp_path / "clean.csv", tmp_path / "clean.json"
    save_clean_dataframe(clean_df, csv_path, json_path)
    from_json = pd.read_json(json_path)
    assert len(from_json) == 24
    assert from_json.loc[0, "authors"] == clean_df.loc[0, "authors"]
    assert pd.read_csv(csv_path).loc[0, "authors"] == "; ".join(clean_df.loc[0, "authors"])

from __future__ import annotations

from collections import Counter

import pytest

from core.utils import first_sentence, read_json
from evaluation.testset import build_test_set


def test_build_test_set_distribution_and_ground_truth(clean_df, tmp_path):
    output = tmp_path / "test_set.json"
    test_set = build_test_set(clean_df, output)

    assert len(test_set) == 10
    assert Counter(item["question_type"] for item in test_set) == {"summary": 3, "authors": 3, "date": 2, "categories": 2}
    assert len({item["ground_truth_doc_ids"][0] for item in test_set}) == 10
    assert read_json(output) == test_set

    by_id = clean_df.set_index("paper_id")
    for item in test_set:
        row = by_id.loc[item["ground_truth_doc_ids"][0]]
        assert f"'{row['title']}'" in item["question"]
        expected = {
            "summary": first_sentence(row["summary"]),
            "authors": row["authors_joined"],
            "date": row["published"],
            "categories": row["categories_joined"],
        }[item["question_type"]]
        assert item["ground_truth"] == expected


def test_build_test_set_is_deterministic(clean_df, tmp_path):
    assert build_test_set(clean_df, tmp_path / "a.json") == build_test_set(clean_df.sample(frac=1, random_state=1), tmp_path / "b.json")


def test_titles_with_quotes_are_skipped(clean_df, tmp_path):
    df = clean_df.copy()
    df.loc[0, "title"] = "It's quoted"
    test_set = build_test_set(df, tmp_path / "t.json")
    assert all("It's quoted" not in item["question"] for item in test_set)


def test_requires_enough_documents(clean_df, tmp_path):
    with pytest.raises(ValueError, match="at least 10"):
        build_test_set(clean_df.head(5), tmp_path / "t.json")


def test_raises_when_no_document_can_answer(clean_df, tmp_path):
    df = clean_df.head(10).copy()
    df["categories_joined"] = ""
    with pytest.raises(ValueError, match="categories"):
        build_test_set(df, tmp_path / "t.json")

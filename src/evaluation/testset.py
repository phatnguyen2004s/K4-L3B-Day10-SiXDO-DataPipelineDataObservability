from __future__ import annotations

from typing import Any

import pandas as pd

from core.utils import first_sentence, write_json

TEST_SET_SIZE = 10
QUESTION_TYPES = ("summary", "authors", "date", "categories")

# Cau hoi khop voi cac pattern trong `retrieval.qa._extract_answer`; title nam trong '...'
# de `answer_question` co the exact-lookup.
QUESTION_TEMPLATES = {
    "summary": "What is the summary of the paper '{title}'?",
    "authors": "Who authored the paper '{title}'?",
    "date": "When was the paper '{title}' published?",
    "categories": "What categories does the paper '{title}' belong to?",
}


def _ground_truth(row: pd.Series, question_type: str) -> str:
    if question_type == "summary":
        return first_sentence(str(row["summary"]))
    if question_type == "authors":
        return str(row["authors_joined"])
    if question_type == "date":
        return str(row["published"])
    return str(row["categories_joined"])


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Tao 10 cau hoi ground-truth tu clean dataframe va ghi JSON vao `output_path`.

    - Phan bo deu 4 dang: summary 3, authors 3, date 2, categories 2.
    - Moi cau hoi dung mot paper khac nhau, chon rai deu tren corpus (sap theo paper_id)
      -> deterministic, cung mot test set cho baseline/corrupted/repaired.
    - Bo qua paper co title chua dau nhay don (pha pattern '<title>') hoac thieu field can hoi.
    """
    candidates = df[
        df["title"].astype(str).str.len().gt(0) & ~df["title"].astype(str).str.contains("'", regex=False)
    ].sort_values("paper_id", kind="stable")
    if len(candidates) < TEST_SET_SIZE:
        raise ValueError(f"Need at least {TEST_SET_SIZE} usable documents to build the test set, got {len(candidates)}.")

    step = len(candidates) // TEST_SET_SIZE
    spread = list(range(0, step * TEST_SET_SIZE, step))
    ordered = [candidates.iloc[i] for i in spread] + [
        candidates.iloc[i] for i in range(len(candidates)) if i not in set(spread)
    ]
    plan = [QUESTION_TYPES[i % len(QUESTION_TYPES)] for i in range(TEST_SET_SIZE)]

    used: set[str] = set()
    test_set: list[dict[str, Any]] = []
    for question_type in plan:
        for row in ordered:
            if row["paper_id"] in used or not _ground_truth(row, question_type):
                continue
            used.add(row["paper_id"])
            test_set.append(
                {
                    "id": f"eval_{len(test_set) + 1:03d}",
                    "question_type": question_type,
                    "question": QUESTION_TEMPLATES[question_type].format(title=row["title"]),
                    "ground_truth": _ground_truth(row, question_type),
                    "ground_truth_doc_ids": [row["paper_id"]],
                }
            )
            break
        else:
            raise ValueError(f"No remaining document can answer a '{question_type}' question.")

    write_json(output_path, test_set)
    return test_set

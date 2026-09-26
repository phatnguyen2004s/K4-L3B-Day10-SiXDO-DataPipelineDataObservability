from __future__ import annotations

import math
import random
from typing import Any

import pandas as pd

from core.utils import now_utc, write_json
from ingestion.cleaning import build_text_for_embedding

SEED = 42
DROP_LATEST_RATIO = 0.20
BLANK_SUMMARY_ROWS = 3
NOISE_ROWS = 3
TRUNCATE_TITLE_ROWS = 3
TRUNCATED_TITLE_CHARS = 6
STALE_RATIO = 0.40
STALE_SHIFT_DAYS = 365
DUPLICATE_ROWS = 3
NOISE_TOKENS = ["#@!x9Qz", "~~%%", "lorem_ipsum", "¿¿??", "0xDEADBEEF", "<br/>", "&&&"]


def _snapshot(row: pd.Series, column: str) -> Any:
    value = row[column]
    return value if isinstance(value, (int, float, str)) else str(value)


def _inject_noise(text: str, rng: random.Random) -> str:
    words = text.split()
    noisy: list[str] = []
    for position, word in enumerate(words):
        noisy.append(word)
        if position % 3 == 2:
            noisy.append(rng.choice(NOISE_TOKENS))
    return " ".join([rng.choice(NOISE_TOKENS), *noisy])


def _mutate(df: pd.DataFrame, indices: list[int], column: str, transform) -> list[dict[str, Any]]:
    changes = []
    for index in indices:
        before = _snapshot(df.loc[index], column)
        df.at[index, column] = transform(df.loc[index])
        changes.append({"paper_id": df.at[index, "paper_id"], "before": before, "after": _snapshot(df.loc[index], column)})
    return changes


def corrupt_clean_dataframe(clean_df: pd.DataFrame, log_path) -> pd.DataFrame:
    """Tiem 6 dang loi vao clean dataframe (deterministic, seed=42) va ghi log chi tiet.

    1. Drop latest records: bo 20% bai moi nhat theo `published`.
    2. Blank summary: xoa trang summary.
    3. Inject noise: chen chuoi ky tu rac vao summary.
    4. Truncate title: cat title con < 8 ky tu.
    5. Stale date: lui `published` 365 ngay (cap nhat `age_days`) cho 40% dong con lai.
    6. Duplicate rows: nhan ban dong -> trung `paper_id`.
    Cac dong 2-5 duoc chon rieng biet de moi loi co the truy vet doc lap; cuoi cung rebuild
    `summary_chars` va `text_for_embedding`.
    """
    rng = random.Random(SEED)
    df = clean_df.copy()
    df["published"] = pd.to_datetime(df["published"]).dt.strftime("%Y-%m-%d")
    input_rows = len(df)
    scenarios: list[dict[str, Any]] = []

    # 1. Drop latest records
    drop_count = math.ceil(len(df) * DROP_LATEST_RATIO)
    latest = df.sort_values(["published", "paper_id"], ascending=[False, True], kind="stable").head(drop_count)
    scenarios.append(
        {
            "scenario": "drop_latest_records",
            "params": {"ratio": DROP_LATEST_RATIO},
            "affected_rows": drop_count,
            "changes": [{"paper_id": row.paper_id, "published": row.published} for row in latest.itertuples()],
        }
    )
    df = df.drop(index=latest.index).reset_index(drop=True)

    # 2-5. Chon cac nhom dong rieng biet
    available = list(df.index)
    rng.shuffle(available)
    stale_count = math.ceil(len(df) * STALE_RATIO)
    groups = {}
    for name, size in (
        ("blank", BLANK_SUMMARY_ROWS),
        ("noise", NOISE_ROWS),
        ("truncate", TRUNCATE_TITLE_ROWS),
        ("stale", stale_count),
    ):
        groups[name], available = sorted(available[:size]), available[size:]

    scenarios.append(
        {
            "scenario": "blank_summary",
            "params": {"rows": BLANK_SUMMARY_ROWS},
            "affected_rows": len(groups["blank"]),
            "changes": _mutate(df, groups["blank"], "summary", lambda row: ""),
        }
    )
    scenarios.append(
        {
            "scenario": "inject_noise",
            "params": {"rows": NOISE_ROWS, "every_n_words": 3, "tokens": NOISE_TOKENS},
            "affected_rows": len(groups["noise"]),
            "changes": _mutate(df, groups["noise"], "summary", lambda row: _inject_noise(row["summary"], rng)),
        }
    )
    scenarios.append(
        {
            "scenario": "truncate_title",
            "params": {"rows": TRUNCATE_TITLE_ROWS, "max_chars": TRUNCATED_TITLE_CHARS},
            "affected_rows": len(groups["truncate"]),
            "changes": _mutate(df, groups["truncate"], "title", lambda row: row["title"][:TRUNCATED_TITLE_CHARS]),
        }
    )
    stale_changes = _mutate(
        df,
        groups["stale"],
        "published",
        lambda row: (pd.Timestamp(row["published"]) - pd.Timedelta(days=STALE_SHIFT_DAYS)).strftime("%Y-%m-%d"),
    )
    for index in groups["stale"]:
        df.at[index, "age_days"] = int(df.at[index, "age_days"]) + STALE_SHIFT_DAYS
    scenarios.append(
        {
            "scenario": "stale_date",
            "params": {"ratio": STALE_RATIO, "shift_days": STALE_SHIFT_DAYS},
            "affected_rows": len(groups["stale"]),
            "changes": stale_changes,
        }
    )

    # 6. Duplicate rows
    duplicate_indices = sorted(rng.sample(list(df.index), DUPLICATE_ROWS))
    duplicates = df.loc[duplicate_indices].copy()
    scenarios.append(
        {
            "scenario": "duplicate_rows",
            "params": {"rows": DUPLICATE_ROWS},
            "affected_rows": DUPLICATE_ROWS,
            "changes": [{"paper_id": paper_id} for paper_id in duplicates["paper_id"]],
        }
    )
    df = pd.concat([df, duplicates], ignore_index=True)

    df["summary_chars"] = df["summary"].str.len().astype(int)
    df["text_for_embedding"] = df.apply(build_text_for_embedding, axis=1)

    write_json(
        log_path,
        {
            "generated_at": now_utc().isoformat(),
            "seed": SEED,
            "input_rows": input_rows,
            "output_rows": len(df),
            "scenario_count": len(scenarios),
            "scenarios": scenarios,
        },
    )
    return df

# Phase 1 Report - Baseline Pipeline

_Generated at 2026-09-26T06:47:14.829268+00:00_

## 1. Source & artifacts

| Item | Value |
| --- | --- |
| source_api | Crossref REST API |
| query | agentic retrieval augmented generation large language model |
| filter | from-pub-date:2026-03-30,has-abstract:true |
| run_date | 2026-09-26T06:47:14.383118+00:00 |
| raw_records | 24 |
| clean_rows | 24 |
| duplicates_or_invalid_dropped | 0 |
| embedding_model | sentence-transformers/all-MiniLM-L6-v2 |
| collection | papers-baseline |
| top_k | 4 |
| llm_provider | gemini |
| test_set_size | 10 |

## 2. Baseline evaluation

| Metric | Value |
| --- | --- |
| samples | 10 |
| retrieval_hit_rate | 1.0000 |
| mean_token_f1 | 1.0000 |
| judge_accuracy | 1.0000 |
| mean_judge_score | 5 |
| judge_backend | heuristic_fallback |

- Ragas: {'skipped': 'Set RUN_RAGAS=1 to enable the slower Ragas pass.'}

## 3. Data quality gate (Great Expectations 1.x)

- Overall quality gate: **PASS** (GX: PASS, freshness: PASS)
- Expectations passed: 7/7

| Expectation | Column | Result | Observed | Unexpected |
| --- | --- | --- | --- | --- |
| expect_table_row_count_to_be_between | (table) | PASS | 24 | - |
| expect_column_values_to_not_be_null | paper_id | PASS | - | 0 |
| expect_column_values_to_be_unique | paper_id | PASS | - | 0 |
| expect_column_values_to_not_be_null | title | PASS | - | 0 |
| expect_column_value_lengths_to_be_between | title | PASS | - | 0 |
| expect_column_values_to_not_be_null | text_for_embedding | PASS | - | 0 |
| expect_column_value_lengths_to_be_between | summary | PASS | - | 0 |

## 4. Freshness SLA

| Signal | Value |
| --- | --- |
| Threshold (days) | 180 |
| Max stale ratio | 0.2500 |
| Stale rows | 1/24 |
| Stale ratio | 0.0417 |
| Latest published | 2026-07-22 |
| Oldest published | 2026-03-28 |
| Median age (days) | 111.5000 |
| is_fresh | PASS |

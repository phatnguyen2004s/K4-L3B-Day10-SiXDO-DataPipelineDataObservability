# Corruption Report - Baseline vs Corrupted vs Repaired

_Generated at 2026-09-26T06:47:54.482166+00:00_

Cung mot evaluation set (`data/eval/test_set.json`) cho ca 3 trang thai.
Judge backend: baseline=heuristic_fallback, corrupted=heuristic_fallback, repaired=heuristic_fallback.

## 1. Agent metrics

| Metric | Baseline | Corrupted | Repaired | Delta (corrupted - baseline) | Recovery |
| --- | --- | --- | --- | --- | --- |
| retrieval_hit_rate | 1.0000 | 0.9000 | 1.0000 | -0.1000 | 100% |
| mean_token_f1 | 1.0000 | 0.5000 | 1.0000 | -0.5000 | 100% |
| judge_accuracy | 1.0000 | 0.5000 | 1.0000 | -0.5000 | 100% |
| mean_judge_score | 5.0000 | 3.0000 | 5.0000 | -2.0000 | 100% |

## 2. Data quality & freshness signals

| Signal | Baseline | Corrupted | Repaired |
| --- | --- | --- | --- |
| Row count | 24 | 22 | 24 |
| GX expectations passed | 7/7 | 4/7 | 7/7 |
| GX success | PASS | FAIL | PASS |
| Stale ratio (age > threshold) | 0.0417 | 0.4545 | 0.0417 |
| is_fresh | PASS | FAIL | PASS |
| Quality gate (GX + freshness) | PASS | FAIL | PASS |

### GX expectations by state

| Expectation | Baseline | Corrupted | Repaired |
| --- | --- | --- | --- |
| expect_table_row_count_to_be_between | PASS | PASS | PASS |
| expect_column_values_to_not_be_null(paper_id) | PASS | PASS | PASS |
| expect_column_values_to_be_unique(paper_id) | PASS | FAIL (6 unexpected) | PASS |
| expect_column_values_to_not_be_null(title) | PASS | PASS | PASS |
| expect_column_value_lengths_to_be_between(title) | PASS | FAIL (3 unexpected) | PASS |
| expect_column_values_to_not_be_null(text_for_embedding) | PASS | PASS | PASS |
| expect_column_value_lengths_to_be_between(summary) | PASS | FAIL (4 unexpected) | PASS |

## 3. Corruption scenarios

- Rows: 24 -> 22 (seed=42)
- Chi tiet tung dong bi bien doi: `data/results/corruption_log.json`

| Scenario | Affected rows | Params |
| --- | --- | --- |
| drop_latest_records | 5 | ratio=0.2 |
| blank_summary | 3 | rows=3 |
| inject_noise | 3 | rows=3, every_n_words=3 |
| truncate_title | 3 | rows=3, max_chars=6 |
| stale_date | 8 | ratio=0.4, shift_days=365 |
| duplicate_rows | 3 | rows=3 |

### Impact on the evaluation set

Cau hoi 'failed' = retrieval miss hoac token F1 < 0.5 tren corrupted index. Mot cau hoi co the bi nhieu scenario cung cham.

| Scenario | Rows | Test questions touched | Failed |
| --- | --- | --- | --- |
| drop_latest_records | 5 | eval_004 | eval_004 |
| blank_summary | 3 | eval_001, eval_006 | eval_001 |
| inject_noise | 3 | none | none |
| truncate_title | 3 | eval_002, eval_007, eval_010 | eval_007, eval_010 |
| stale_date | 8 | eval_003, eval_005, eval_008, eval_009 | eval_003 |
| duplicate_rows | 3 | eval_006, eval_009 | none |

## 4. Repair

| Item | Value |
| --- | --- |
| source | data/raw/crossref_records.json |
| source_sha256 | 5531ffec28b176dcb8b54e621becbe89a2dc0c1241a3ced4e7e08b2e8ce96990 |
| source_unchanged | PASS |
| raw_records | 24 |
| repaired_rows | 24 |
| trigger | quality gate failed: ['expect_column_values_to_be_unique(paper_id)', 'expect_column_value_lengths_to_be_between(title)', 'expect_column_value_lengths_to_be_between(summary)'], is_fresh=False |
| matches_baseline_content | PASS |

## 5. Observations (tu dong tu so lieu)

- `retrieval_hit_rate` giam 0.1000 khi corrupted (1.0000 -> 0.9000), repaired dat 1.0000.
- `mean_token_f1` giam 0.5000 khi corrupted (1.0000 -> 0.5000), repaired dat 1.0000.
- `judge_accuracy` giam 0.5000 khi corrupted (1.0000 -> 0.5000), repaired dat 1.0000.
- `mean_judge_score` giam 2.0000 khi corrupted (5.0000 -> 3.0000), repaired dat 5.0000.
- Quality gate tren corrupted: FAIL; expectation fail: expect_column_values_to_be_unique(paper_id), expect_column_value_lengths_to_be_between(title), expect_column_value_lengths_to_be_between(summary); is_fresh=False (stale_ratio=0.4545).
- Quality gate tren repaired: PASS.
- `inject_noise` khong vi pham expectation nao va khong cham cau hoi nao trong test set -> ca quality gate lan metric deu khong thay: silent failure hoan toan (can them check noi dung, vd ty le token la).

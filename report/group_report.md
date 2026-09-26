# Group Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin bài nộp

| Thông tin | Nội dung |
| --- | --- |
| Khóa/Lớp | K4 — L3B |
| Tên nhóm | SiXDO (làm cá nhân, 1 thành viên) |
| Repository | https://github.com/phatnguyen2004s/K4-L3B-Day10-SiXDO-DataPipelineDataObservability |
| Ngày hoàn thành | 2026-09-26 |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- |
| 1 | Nguyễn Tiến Phát | 2A202602387 | Toàn bộ pipeline (làm một mình) | `src/ingestion/*`, `src/observability/*`, `src/evaluation/testset.py`, `src/evaluation/metrics.py` (bổ sung), `src/pipelines/*`, `src/retrieval/index.py` (sửa `persist_path`), `tests/`, toàn bộ artifact trong `data/` |

## 2. Tóm tắt kết quả

Bài làm hoàn thành cả 8 bước của codelab và hai luồng end-to-end chạy với exit code 0: `script/run_phase1.py` và `script/run_corruption_flow.py`. Baseline dùng 24 bài báo từ snapshot Crossref, làm sạch còn 24 dòng (không có dòng trùng hoặc lỗi), index vào ChromaDB `papers-baseline` bằng `all-MiniLM-L6-v2` và đạt `retrieval_hit_rate = 1.0`, `mean_token_f1 = 1.0` trên 10 câu hỏi. Quality gate GX 1.x đạt 7/7 expectation; freshness đạt với 1/24 bài cũ (4,17%).

Bộ corruption gồm 6 kịch bản đưa dữ liệu về 22 dòng. Quality gate bắt được 3/7 expectation vi phạm (trùng `paper_id`, `title` < 8 ký tự, `summary` < 30 ký tự) và freshness vi phạm (45,45% bài cũ). Agent suy giảm: `mean_token_f1` 1.0 → 0.5, `retrieval_hit_rate` 1.0 → 0.9. Kịch bản gây hại rõ nhất là `truncate_title` (2 câu hỏi sai dù retrieval vẫn "hit"), tiếp theo là `drop_latest_records`, `blank_summary` và `stale_date` (mỗi kịch bản 1 câu sai). Repair tự kích hoạt khi gate fail, dựng lại từ `data/raw/crossref_records.json` và phục hồi 100% mọi chỉ số; nội dung repaired khớp baseline.

Giới hạn lớn nhất: `judge_accuracy`/`mean_judge_score` được chấm bằng heuristic theo token F1, không phải LLM. Nguyên nhân là quota free của Gemini chỉ 20 request/ngày (xem mục 11). Ngoài ra `inject_noise` không chạm câu hỏi nào trong test set, nên đây là silent failure mà cả gate lẫn metric đều không phát hiện.

## 3. Kiến trúc và luồng dữ liệu

### Luồng end-to-end

```text
Crossref API (/works) hoặc snapshot data/raw/crossref_response.json
    -> parse_crossref_payload -> data/raw/crossref_records.json          (crossref.py)
    -> build_clean_dataframe -> data/clean/papers_clean.{csv,json}         (cleaning.py)
    -> QUALITY GATE: GX 1.x (7 expectations) + Freshness SLA              (quality.py)
         └─ GX fail -> dừng pipeline, không index
    -> MiniLM embeddings + ChromaDB collection papers-baseline             (retrieval/index.py)
    -> test set 10 câu (data/eval/test_set.json) -> evaluate               (testset.py, metrics.py)
    -> data/results/baseline_metrics.json + data/reports/phase1_report.md  (phase1.py, reporting.py)
    -> corrupt_clean_dataframe (6 scenarios, seed=42) + corruption_log     (corruption.py)
    -> quality gate (FAIL) -> vẫn index papers-corrupted để đo silent failure
    -> evaluate cùng test set -> corrupted_metrics.json
    -> gate fail => AUTO REPAIR: rebuild từ raw snapshot -> papers-repaired
    -> evaluate cùng test set -> repaired_metrics.json
    -> data/reports/corruption_report.md (so sánh 3 trạng thái)          (corruption_flow.py)
```

### Trách nhiệm của từng khối

| Khối | Input | Xử lý chính | Output/artifact | Owner |
| --- | --- | --- | --- | --- |
| Ingestion | Crossref `/works` hoặc snapshot | Retry/backoff 429/5xx, fallback snapshot, parse JATS | `data/raw/crossref_response.json`, `data/raw/crossref_records.json` | Nguyễn Tiến Phát |
| Cleaning | `crossref_records.json` | Chuẩn hóa text/ngày, `age_days`, dedupe `paper_id`, `text_for_embedding` | `data/clean/papers_clean.{csv,json}` | Nguyễn Tiến Phát |
| Embedding/index | Clean dataframe | `all-MiniLM-L6-v2`, ChromaDB cosine, 1 collection/trạng thái | `data/chroma/`, `data/embeddings/*.json` | Nguyễn Tiến Phát |
| Evaluation | Clean dataframe, index | Test set 10 câu, Hit Rate, Token F1, judge | `data/eval/test_set.json`, `data/results/*_metrics.json`, `*_answers.json` | Nguyễn Tiến Phát |
| Observability | Dataframe mỗi trạng thái | GX 1.x Ephemeral Context + Freshness SLA | `data/quality/*_quality_report.json`, `*freshness_report.json`, `data/quality/gx/*_expectation_suite.json` | Nguyễn Tiến Phát |
| Corruption/repair | Clean dataframe, raw records | 6 kịch bản lỗi; repair idempotent từ raw | `data/results/corruption_log.json`, `data/clean/papers_clean_{corrupted,repaired}.*` | Nguyễn Tiến Phát |
| Orchestration | Settings | `run_phase1_pipeline`, `run_corruption_flow_pipeline` | `data/reports/phase1_report.md`, `data/reports/corruption_report.md` | Nguyễn Tiến Phát |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình | Giá trị sử dụng |
| --- | --- |
| `LLM_PROVIDER` | `gemini` |
| `LLM_MODEL` | `gemini-3.8-flash` (`gemini-2.5-flash` trả 404, đã bị ngừng cấp cho người dùng mới) |
| `JUDGE_MODE` | `heuristic` (chấm bằng token F1, không gọi LLM — xem mục 11) |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Số lượng Crossref records | 24 (`max_results=24`) |
| Retrieval `top_k` | 4 |
| Freshness threshold | `age_days > 180`, tối đa 25% bài cũ |
| Random seed | 42 (corruption) |

### Lệnh cài đặt

```bash
uv sync --python 3.12
```

Máy chỉ có Python 3.10/3.14 (ngoài khoảng `>=3.11,<3.14`), nên dùng `uv` để tạo `.venv` Python 3.12.14. Tạo `.env` từ `.env.example` và điền `GOOGLE_API_KEY`.

### Lệnh chạy

```bash
uv run python script/run_phase1.py
uv run python script/run_corruption_flow.py
./script/run_tests.sh
```

### Kết quả tái hiện

| Lệnh | Trạng thái | Thời điểm chạy gần nhất | Bằng chứng |
| --- | --- | --- | --- |
| Baseline pipeline | Thành công (exit 0) | 2026-09-26 13:47 (GMT+7) | `data/reports/phase1_report.md`, `data/results/baseline_metrics.json` |
| Corruption flow | Thành công (exit 0) | 2026-09-26 13:47 (GMT+7) | `data/reports/corruption_report.md`, `data/results/{corrupted,repaired}_metrics.json` |
| Test suite | 52 passed, coverage 94% | 2026-09-26 | `./script/run_tests.sh` |

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Source | Crossref REST API `https://api.crossref.org/works` |
| Query/filter | `query="agentic retrieval augmented generation large language model"`, `filter=from-pub-date:<run_date−180 ngày>,has-abstract:true`, `rows=24`, `sort=published desc` |
| Thời điểm lấy dữ liệu | Dùng snapshot có sẵn của lab (mặc định, `REFRESH_SOURCE` không bật); ngày xuất bản trong snapshot từ 2026-03-28 đến 2026-07-22 |
| Số record nhận được | 24 item → 24 `PaperRecord` hợp lệ |
| Cơ chế retry/backoff | Tối đa 4 lần; retry với HTTP 429/500/502/503/504 và lỗi mạng; ưu tiên `Retry-After` (tối đa 60s), nếu không có thì backoff 2s → 4s → 8s; lỗi 4xx khác dừng ngay; thất bại mà có snapshot thì fallback snapshot |

Mặc định pipeline đọc snapshot (lineage anchor, tái lập được, không tốn rate limit). `REFRESH_SOURCE=1` sẽ gọi API thật và ghi đè snapshot khi thành công.

### Raw và clean schema

| Trường | Kiểu dữ liệu | Bắt buộc? | Ý nghĩa | Xử lý khi thiếu/sai |
| --- | --- | --- | --- | --- |
| `paper_id` | str (DOI) | Có | Khóa định danh | Thiếu → bỏ record; dedupe không phân biệt hoa thường |
| `title` | str | Có | Tiêu đề | Bỏ thẻ HTML, chuẩn hóa khoảng trắng; rỗng → bỏ |
| `summary` | str | Có | Abstract | Bỏ `<jats:*>`, decode entity; rỗng → bỏ |
| `authors` | list[str] | Không | Tác giả | `given family` hoặc `name`; bỏ rỗng/trùng |
| `categories` | list[str] | Không | Subject | Bỏ rỗng/trùng; `primary_category` = phần tử đầu |
| `published` | str `YYYY-MM-DD` | Có | Ngày xuất bản | Lấy `published` → `published-online` → `published-print` → `issued` → `created`; thiếu tháng/ngày → 01; không parse được → bỏ |
| `updated` | str `YYYY-MM-DD` | Không | Ngày cập nhật | `deposited` → `created` → `published` |
| `abs_url`, `pdf_url` | str | Không | Link | `URL` hoặc `https://doi.org/<DOI>`; PDF lấy từ `link` nếu có |
| `authors_joined`, `categories_joined` | str | Có (có thể rỗng) | Metadata cho ChromaDB/QA | Nối bằng `, ` |
| `age_days` | int | Có | Tuổi dữ liệu | `(run_date − published).days` |
| `summary_chars` | int | Có | Độ dài summary | `len(summary)` |
| `text_for_embedding` | str | Có | Văn bản embed | 5 dòng `Title/Authors/Published/Categories/Summary` |

### Quy tắc cleaning

| Quy tắc | Quality dimension liên quan | Số record bị tác động | Cách xác minh |
| --- | --- | ---: | --- |
| Bỏ thẻ JATS/HTML, chuẩn hóa khoảng trắng | Validity | 24 abstract có `<jats:p>` | `tests/test_crossref.py::test_strip_markup_removes_jats_and_entities` |
| Bỏ record thiếu `paper_id`/`title`/`summary`/`published` hợp lệ | Completeness | 0 (baseline) | `duplicates_or_invalid_dropped = 0` trong `phase1_report.md` |
| Dedupe theo `paper_id` (giữ `updated` mới nhất) | Uniqueness | 0 (baseline) | GX `expect_column_values_to_be_unique(paper_id)` PASS |
| Chuẩn hóa ngày về ISO + `age_days` | Timeliness/Validity | 24 | `data/quality/freshness_report.json` |

`text_for_embedding` ghép 5 dòng `Title / Authors / Published / Categories / Summary` để embedding mang cả metadata, nhờ đó câu hỏi về tác giả/ngày/lĩnh vực cũng truy hồi được. Document ID là DOI (`paper_id`); record ID trong ChromaDB là `<paper_id>::<index>`, nên dòng trùng khi corrupt vẫn index được. `age_days` tính theo ngày chạy (UTC).

## 6. Evaluation setup

| Thành phần | Cấu hình thực tế |
| --- | --- |
| Số câu hỏi | 10 |
| Các `question_type` | `summary` (3), `authors` (3), `date` (2), `categories` (2) |
| Ground-truth document ID | DOI của bài được hỏi; ground truth: câu đầu summary / `authors_joined` / `published` / `categories_joined` |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (normalize, cosine) |
| Vector store/collection | ChromaDB `data/chroma`: `papers-baseline`, `papers-corrupted`, `papers-repaired` |
| Retrieval `top_k` | 4 |
| LLM provider/model | `gemini` / `gemini-3.8-flash`; judge: heuristic (`JUDGE_MODE=heuristic`) |
| Test set dùng chung cho ba trạng thái | `data/eval/test_set.json` (sha256 bắt đầu bằng `6eb27296c020bcda`) |

Test set được sinh deterministic (sắp theo `paper_id`, chọn rải đều, mỗi câu một bài khác nhau, bỏ tiêu đề có dấu `'`). Phase 1 chỉ sinh lại khi `REFRESH_TEST_SET=1` hoặc test set trỏ tới doc không còn tồn tại. Corrupted và repaired dùng lại đúng file này, nên chênh lệch metric chỉ đến từ dữ liệu chứ không đến từ câu hỏi.

## 7. Kết quả baseline

### Artifact checklist

| Artifact | Đường dẫn thực tế | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| Raw response/records | `data/raw/` | Có | 24 item / 24 record |
| Cleaned dataset | `data/clean/papers_clean.{csv,json}` | Có | 24 dòng, 16 cột |
| Embedding manifest/index | `data/embeddings/papers_embeddings.json`, `data/chroma/` | Có | `persist_path` tương đối (`data/chroma`) |
| Evaluation set | `data/eval/test_set.json` | Có | 10 câu |
| Baseline metrics | `data/results/baseline_metrics.json` | Có | kèm `baseline_answers.json` |
| Quality/freshness | `data/quality/` | Có | `baseline_quality_report.json`, `freshness_report.json`, `gx/baseline_expectation_suite.json` |
| Baseline report | `data/reports/phase1_report.md` | Có | |

### Baseline metrics

| Metric | Giá trị | Diễn giải |
| --- | ---: | --- |
| `retrieval_hit_rate` | 1.0000 | Cả 10 câu đều có doc đúng trong top-4 |
| `mean_token_f1` | 1.0000 | Câu trả lời trích đúng field ground truth (QA trích xuất từ metadata của kết quả top-1) |
| `judge_accuracy` | 1.0000 | Heuristic: token F1 ≥ 0.5 → đúng |
| `mean_judge_score` | 5 | Heuristic: F1 ≥ 0.95 → 5 điểm |
| Ragas | N/A | Bỏ qua (cần `RUN_RAGAS=1` và LLM; quota free không đủ) |

## 8. Data quality và freshness

### Quality checks

| Check | Quality dimension | Ngưỡng/kỳ vọng | Kết quả baseline | Bằng chứng |
| --- | --- | --- | --- | --- |
| `ExpectTableRowCountToBeBetween` | Completeness | 5–5000 dòng | PASS (24) | `data/quality/baseline_quality_report.json` |
| `ExpectColumnValuesToNotBeNull(paper_id)` | Completeness | 0 null | PASS | như trên |
| `ExpectColumnValuesToNotBeNull(title)` | Completeness | 0 null | PASS | như trên |
| `ExpectColumnValuesToNotBeNull(text_for_embedding)` | Completeness | 0 null | PASS | như trên |
| `ExpectColumnValuesToBeUnique(paper_id)` | Uniqueness | Không trùng | PASS | như trên |
| `ExpectColumnValueLengthsToBeBetween(summary)` | Validity | ≥ 30 ký tự | PASS | như trên |
| `ExpectColumnValueLengthsToBeBetween(title)` (bổ sung) | Validity | ≥ 8 ký tự | PASS | như trên |

### Freshness

| Thuộc tính | Giá trị |
| --- | --- |
| Freshness được đo tại | Clean dataset (cột `age_days`, `published`) |
| Timestamp mới nhất | 2026-07-22 (cũ nhất 2026-03-28) |
| Ngưỡng freshness | `age_days > 180` là bài cũ; `is_fresh=False` nếu tỷ lệ bài cũ > 25% |
| Trạng thái baseline | Fresh |
| Lý do | 1/24 bài cũ (4,17%, bài 2026-03-28 có `age_days = 182`); median 111,5 ngày |

## 9. Corruption scenarios và repair

| Corruption | Cách tạo | Record bị tác động | Quality signal kỳ vọng | Tác động thực tế | Cách repair |
| --- | --- | ---: | --- | --- | --- |
| `drop_latest_records` | Bỏ 20% bài mới nhất theo `published` | 5 | Row count (vẫn trong ngưỡng) | eval_004 retrieval miss → sai | Rebuild từ raw |
| `blank_summary` | `summary = ""` | 3 | `summary` length < 30 | GX FAIL (4 dòng, tính cả bản trùng); eval_001 trả lời rỗng | Rebuild từ raw |
| `inject_noise` | Chèn token rác mỗi 3 từ vào summary | 3 | Không có | Không expectation nào bắt; không chạm câu hỏi test → silent failure | Rebuild từ raw |
| `truncate_title` | Cắt `title` còn 6 ký tự | 3 | `title` length < 8 | GX FAIL (3); eval_007, eval_010 sai | Rebuild từ raw |
| `stale_date` | Lùi `published` 365 ngày, cập nhật `age_days` | 8 | Freshness | `is_fresh=False` (45,45%); eval_003 trả về ngày sai 2025-03-28 | Rebuild từ raw |
| `duplicate_rows` | Nhân đôi 3 dòng | 3 | `paper_id` unique | GX FAIL (6 giá trị trùng); không câu nào sai | Rebuild từ raw |

Corruption log:

- Đường dẫn: `data/results/corruption_log.json`
- Trạng thái: Có
- Nhận xét: log ghi seed, số dòng vào/ra (24 → 22), tham số từng kịch bản và danh sách `paper_id` bị tác động kèm giá trị trước/sau (ngày cũ/mới, title cũ/mới, summary cũ/mới).

Repair không vá từng lỗi trên dataframe hỏng. Hàm `repair_from_raw_snapshot()` chạy lại `load_raw_records` → `build_clean_dataframe` từ `data/raw/crossref_records.json` (fallback `crossref_response.json`) và ghi đè artifact repaired. Nguồn raw chỉ được đọc: SHA-256 trước/sau bằng nhau (`source_unchanged = PASS`). Dấu vân tay nội dung repaired trùng baseline (`matches_baseline_content = PASS`). Chạy repair 2 lần cho cùng kết quả (`tests/test_pipelines_e2e.py::test_repair_is_idempotent`). Repair được kích hoạt tự động khi quality gate trên corrupted fail; `trigger` ghi rõ các expectation vi phạm.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0000 | 0.9000 | 1.0000 | −0.1000 | 100% | Chỉ bắt được bài bị xóa (eval_004) |
| `mean_token_f1` | 1.0000 | 0.5000 | 1.0000 | −0.5000 | 100% | 5/10 câu sai |
| `judge_accuracy` | 1.0000 | 0.5000 | 1.0000 | −0.5000 | 100% | Heuristic theo F1 nên cùng xu hướng |
| `mean_judge_score` | 5 | 3 | 5 | −2 | 100% | Heuristic |
| Quality checks pass/fail | 7/7 PASS | 4/7 FAIL | 7/7 PASS | −3 expectation | 100% | Fail: unique `paper_id`, length `title`, length `summary` |
| Freshness status | Fresh (4,17%) | Stale (45,45%) | Fresh (4,17%) | +41,3 điểm % | 100% | Do `stale_date` |

Tác động theo câu hỏi (trích `corruption_report.md`): `truncate_title` chạm eval_002/007/010 và làm sai eval_007, eval_010; `drop_latest_records` → eval_004; `blank_summary` → eval_001; `stale_date` chạm 4 câu nhưng chỉ làm sai câu hỏi ngày eval_003; `duplicate_rows` và `inject_noise` không làm sai câu nào.

Kết luận có quan hệ nhân quả:

1. `truncate_title` cắt tiêu đề còn 6 ký tự ("Advanc", "Mitiga") → GX `title` length FAIL (3 dòng) → câu hỏi dạng `'<title>'` không còn exact-match. Semantic search xếp top-1 là bài "anh em" cùng chủ đề (bản gốc ↔ bản "Advanced Perspectives on…"). eval_007 và eval_010 vì vậy sai (F1 = 0) dù doc đúng vẫn nằm trong top-4 (`retrieval_hit = True`). eval_002 cũng lấy nhầm top-1 nhưng vẫn đúng vì bài anh em có cùng tác giả. Vì vậy `retrieval_hit_rate` chỉ giảm 0,1 trong khi `mean_token_f1` giảm 0,5: hit rate đánh giá thấp mức hỏng của câu trả lời.
2. Quality gate fail (3 expectation + `is_fresh=False`) → tự động repair từ raw snapshot → GX 7/7, freshness 4,17% → cả 4 metric trở về đúng giá trị baseline (phục hồi 100%). Sự phục hồi này có thể quy về repair vì cùng test set, cùng model, cùng `top_k`, và nội dung repaired trùng baseline.

## 11. Vấn đề tích hợp quan trọng

- **Triệu chứng:** lần chạy đầu `judge_accuracy = 1.0`, `mean_judge_score = 5` nhưng `data/results/agent_demo_answers.json` báo lỗi 404. Mọi `judge.reasoning` đều là "Fallback heuristic judge…", tức LLM judge chưa từng chạy mà metric vẫn trông bình thường.
- **Nguyên nhân:** `gemini-2.5-flash` (mặc định của starter) trả `404 NOT_FOUND` do model đã ngừng cấp cho người dùng mới. `_judge_answer` bắt mọi exception và âm thầm chuyển sang heuristic. Sau khi đổi sang `gemini-3.8-flash`, free tier chỉ cho 20 request/ngày trong khi một lượt đủ 3 trạng thái cần khoảng 32 lần gọi (30 judge + 2 demo) → `429 RESOURCE_EXHAUSTED`, baseline thành "mixed" (9/10 câu LLM chấm) còn corrupted/repaired là heuristic → so sánh không đồng nhất.
- **Cách xử lý:** thêm `judge_backend` (`llm` / `heuristic_fallback` / `mixed`) vào metrics và báo cáo; retry theo `retry in Xs` của API khi gặp 429, có circuit breaker khi hết quota; thêm `JUDGE_MODE=heuristic` và chạy lại cả 3 trạng thái với cùng một judge.
- **Cách xác minh:** `data/results/*_metrics.json` đều có `"judge_backend": "heuristic_fallback"`; `tests/test_config_and_llm.py::test_judge_retries_on_quota_then_trips_breaker`.

Vấn đề phụ: `data/embeddings/*.json` ban đầu lưu `persist_path` tuyệt đối (`/Users/...`) nên không chạy được trên máy khác. Đã đổi sang đường dẫn tương đối `data/chroma` và resolve theo project dir khi load (`test_manifest_uses_relative_persist_path`).

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng | Hướng cải thiện có thể kiểm chứng |
| --- | --- | --- |
| Judge là heuristic theo token F1 | `judge_accuracy` không đo thêm gì ngoài F1 | Dùng key có billing, bỏ `JUDGE_MODE`, kiểm tra `judge_backend = llm` ở cả 3 file metrics |
| Test set chỉ 10 câu, không chạm dòng `inject_noise` | Nhiễu nội dung không lộ ra ở cả gate lẫn metric | Thêm câu hỏi cho mọi doc hoặc test set ≥ 24 câu; thêm expectation nội dung (tỷ lệ token không phải chữ, regex ký tự rác) và kiểm tra corrupted gate bắt thêm `summary` noise |
| QA trích xuất từ metadata top-1 | Metric nhạy với tiêu đề hỏng hơn là với chất lượng generation | Chấm thêm bằng agent LLM (`build_agent`) khi có quota |
| Freshness phụ thuộc ngày chạy | Snapshot sẽ vượt ngưỡng 25% khoảng từ 2026-11-29, baseline khi đó sẽ bị báo stale | Chạy `REFRESH_SOURCE=1` để lấy dữ liệu mới, hoặc cố định `run_date` khi tái lập |
| `retrieval_hit_rate` ở top-4 che giấu lỗi top-1 | Đánh giá thấp mức hỏng (0,1 so với 0,5) | Báo cáo thêm hit@1 / MRR |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Phân công khớp với module, artifact và kết quả thực tế.
- [x] Lệnh tái hiện đã được chạy lại trên phiên bản dùng để nộp.
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file trong `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact truy cập được.
- [x] Mỗi thành viên đã hoàn thành báo cáo vai trò riêng.
- [x] Không có `.env`, API key, token hoặc secret trong source, report, log hay ảnh.

# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Tiến Phát |
| MSSV | 2A202602387 |
| Khóa/Lớp | K4 — L3B |
| Tên nhóm | SiXDO (làm cá nhân) |
| Vai trò chính | Toàn bộ pipeline: ingestion, cleaning, observability, evaluation, corruption/repair, orchestration, test |
| Repository | https://github.com/phatnguyen2004s/K4-L3B-Day10-SiXDO-DataPipelineDataObservability |
| Ngày hoàn thành | 2026-09-26 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Raw ingestion | `src/ingestion/crossref.py`: `parse_crossref_payload`, `fetch_source_records`, `load_raw_records` | Crossref `/works` hoặc snapshot | `data/raw/crossref_response.json`, `crossref_records.json` | Hoàn thành |
| Cleaning | `src/ingestion/cleaning.py`: `build_clean_dataframe`, `build_text_for_embedding`, `save_clean_dataframe` | `list[PaperRecord]`, `run_date` | `data/clean/papers_clean.{csv,json}` | Hoàn thành |
| Quality & freshness | `src/observability/quality.py`: `run_data_quality_checks`, `evaluate_freshness_sla`, `build_freshness_report` | Dataframe | `data/quality/*` | Hoàn thành |
| Evaluation set | `src/evaluation/testset.py`: `build_test_set` | Clean dataframe | `data/eval/test_set.json` | Hoàn thành |
| Corruption & repair | `src/ingestion/corruption.py`, `src/pipelines/corruption_flow.py` | Clean dataframe, raw records | `corruption_log.json`, `corrupted/repaired_metrics.json`, `corruption_report.md` | Hoàn thành |
| Orchestration & report | `src/pipelines/phase1.py`, `src/observability/reporting.py` | Settings | `baseline_metrics.json`, `phase1_report.md` | Hoàn thành |
| Test suite (bonus B3) | `tests/`, `script/run_tests.sh` (one-click test) | Raw snapshot | 52 test, coverage 94% | Hoàn thành |
| LLM judge thật | `src/evaluation/metrics.py` | Gemini API | `judge_backend = llm` | Chưa đạt — hết quota free (xem mục 6) |

Làm một mình nên tôi vừa là owner vừa là người tích hợp. Vì vậy tôi phải chốt contract giữa các khối trước: clean schema 16 cột, `published` là chuỗi ISO (ChromaDB metadata chỉ nhận scalar), document ID là DOI, và cùng một test set cho 3 trạng thái.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Dựng môi trường khi máy thiếu Python 3.11–3.13 và mạng rất chậm | `.venv` | Cài `uv`, tạo `.venv` Python 3.12.14; tự tải các wheel lớn (torch, pyarrow, chromadb…) và model MiniLM bằng `curl` có resume + kiểm tra SHA-256 |
| Sửa code starter | `src/retrieval/index.py`, `src/evaluation/metrics.py` | `persist_path` tương đối; thêm `judge_backend`, retry 429, `JUDGE_MODE` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Parse Crossref, fallback snapshot | `crossref.py` | 24/24 record, giống hệt `crossref_records.json` mẫu | `test_parse_snapshot_matches_reference_records` |
| Quality gate GX 1.x + freshness | `quality.py` | Baseline 7/7 PASS, fresh 4,17%; corrupted 4/7, stale 45,45% | `data/quality/*_quality_report.json` |
| Corruption 6 kịch bản + repair tự động | `corruption.py`, `corruption_flow.py` | 24 → 22 dòng; F1 1.0 → 0.5 → 1.0 | `data/reports/corruption_report.md` |
| Test tự động | `tests/` | 52 passed, coverage 94% | `./script/run_tests.sh` |

Output cụ thể tôi muốn nêu là bảng **"Impact on the evaluation set"** trong `data/reports/corruption_report.md`. Bảng nối từng kịch bản lỗi với các câu hỏi test mà nó chạm tới (qua `ground_truth_doc_ids`) và các câu thực sự bị hỏng. Nhờ bảng này tôi phát hiện `inject_noise` không chạm câu hỏi nào, tức là không có tín hiệu nào báo lỗi này. Tôi đã sửa nhận xét tự động cho đúng số liệu thay vì kết luận chung chung rằng "noise làm giảm metric".

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Hệ RAG sẽ trả lời sai âm thầm (silent failure) khi dữ liệu nguồn bị hỏng: bài mới bị mất, summary rỗng, tiêu đề bị cắt, ngày bị lùi, dòng trùng. Phần của tôi phải (1) chặn dữ liệu hỏng trước khi vào vector store, (2) đo được mức suy giảm khi dữ liệu hỏng lọt vào, và (3) phục hồi an toàn, chứng minh bằng số liệu.

### Cách triển khai

- **Gate trước index:** Phase 1 chạy GX trước `LocalEmbeddingIndex.build`. Nếu GX fail thì raise `QualityGateError` và không index. Freshness fail chỉ cảnh báo, vì freshness phụ thuộc ngày chạy và không nên làm hỏng baseline.
- **Expectation:** 4 expectation bắt buộc (row count 5–5000; not-null `paper_id`/`title`/`text_for_embedding`; unique `paper_id`; `summary` ≥ 30 ký tự). Tôi thêm `title` ≥ 8 ký tự vì kịch bản `truncate_title` cắt title còn dưới 8 ký tự; nếu không có check này gate sẽ bỏ lọt.
- **Corruption:** seed 42, chọn các nhóm dòng rời nhau cho blank/noise/truncate/stale để mỗi lỗi truy vết độc lập. `stale_date` cập nhật cả `age_days` để freshness thấy được. Tỷ lệ 40% được chọn để vượt ngưỡng 25%. Sau khi làm bẩn, tôi rebuild `text_for_embedding` bằng đúng hàm của cleaning.
- **Repair:** không vá dataframe hỏng mà chạy lại cleaning từ raw snapshot bất biến, nên chạy 1 hay nhiều lần đều cho cùng kết quả. Tôi kiểm chứng bằng SHA-256 của file raw trước/sau và dấu vân tay nội dung so với baseline.
- **Tự kích hoạt (bonus B2):** repair chạy khi quality gate của corrupted fail; `trigger` ghi lại các expectation vi phạm.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `data/raw/crossref_records.json` (24 `PaperRecord`), settings từ `core/config.py` |
| Output | Clean dataframe 16 cột; quality report `{success, gx_success, is_fresh, gx.checks[], freshness}`; metrics `{retrieval_hit_rate, mean_token_f1, judge_accuracy, mean_judge_score, judge_backend}` |
| Module phụ thuộc | `core/config.py`, `core/utils.py`, `retrieval/index.py`, `evaluation/metrics.py` |
| Module sử dụng output | `retrieval/index.py` (cần `text_for_embedding`, `authors_joined`, `categories_joined`, `published` dạng str), `retrieval/qa.py`, `observability/reporting.py` |
| Điều kiện lỗi cần xử lý | Crossref 429/5xx/mất mạng; record thiếu field; ngày chỉ có năm/tháng; DOI trùng khác hoa thường; tiêu đề chứa `'` (phá pattern câu hỏi); thiếu baseline khi chạy corruption flow; LLM 404/429 |

### Cách xác minh

```bash
uv run python script/run_phase1.py
uv run python script/run_corruption_flow.py
./script/run_tests.sh
```

- **Kết quả mong đợi:** cả hai script exit 0; bảng 3 trạng thái cho thấy corrupted giảm và repaired về bằng baseline; test pass với coverage ≥ 80%.
- **Kết quả thực tế:** exit 0 cả hai; hit rate 1.0/0.9/1.0, token F1 1.0/0.5/1.0, gate PASS/FAIL/PASS; 52 passed, coverage 94%.
- **Artifact/log:** `data/reports/phase1_report.md`, `data/reports/corruption_report.md`, `data/results/*.json`, `data/quality/*.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** hết quota Gemini free (20 request/ngày), trong khi một lượt chạy đủ 3 trạng thái cần khoảng 32 lần gọi LLM. Kết quả là baseline được LLM chấm 9/10 câu, còn corrupted/repaired chấm bằng heuristic.
- **Các phương án đã cân nhắc:** (a) giữ nguyên kết quả trộn; (b) dùng nhiều API key free khác nhau; (c) ép cả 3 trạng thái dùng cùng judge heuristic (`JUDGE_MODE=heuristic`); (d) dùng key trả phí.
- **Phương án đã chọn:** (c).
- **Lý do:** so sánh 3 trạng thái chỉ có ý nghĩa khi cùng test set, cùng model và cùng cách chấm. (a) làm lệch phép so sánh. (b) vẫn không đủ quota và lại trộn nhiều nguồn chấm. (d) tôi không có. Với (c) tôi đánh đổi độ "thông minh" của judge lấy tính nhất quán, và ghi rõ `judge_backend` trong mọi file metrics và báo cáo để không bị hiểu nhầm là LLM chấm.
- **Bằng chứng quyết định phù hợp:** cả 3 file `data/results/*_metrics.json` có `"judge_backend": "heuristic_fallback"`; `judge_accuracy` thay đổi cùng hướng với `mean_token_f1` (1.0 → 0.5 → 1.0).

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `Error calling model 'gemini-2.5-flash' (NOT_FOUND): 404 NOT_FOUND ... This model models/gemini-2.5-flash is no longer available to new users`; sau khi đổi model: `429 RESOURCE_EXHAUSTED ... Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash`.
- **Lệnh hoặc bước tái hiện:** `python script/run_phase1.py` với `LLM_MODEL=gemini-2.5-flash`, rồi kiểm tra `judge.reasoning` trong `data/results/baseline_answers.json`.
- **Nguyên nhân gốc:** model mặc định của starter đã ngừng cấp cho người dùng mới. `_judge_answer` bắt mọi exception và âm thầm dùng heuristic, nên metric vẫn đẹp (1.0) và che mất lỗi — chính là một silent failure trong khâu đánh giá.
- **Cách xử lý:** đổi `LLM_MODEL` sang `gemini-3.8-flash` (`.env`, `.env.example`, `config.py`). Trong `metrics.py`: thêm `judge_backend`, đưa lý do lỗi vào `reasoning`, retry theo `retry in Xs` khi gặp 429, circuit breaker khi hết quota, và `JUDGE_MODE`.
- **Cách xác minh sau khi sửa:** gọi thử `gemini-3.8-flash` trả "OK"; `test_judge_retries_on_quota_then_trips_breaker` và `test_judge_uses_llm_verdict_when_available` pass; metrics ghi đúng `judge_backend`.
- **Điều học được:** mọi fallback trong pipeline đánh giá phải để lại dấu vết trong output. Nếu không, chính metric sẽ nói dối.

## 7. Hiểu biết về luồng end-to-end

1. **Từ Crossref đến vector index:** `fetch_source_records` lấy payload (API hoặc snapshot) và lưu nguyên bản làm lineage anchor. Payload được parse thành `PaperRecord` và lưu `crossref_records.json`. `build_clean_dataframe` chuẩn hóa, tính `age_days`, dedupe, ghép `text_for_embedding`. Quality gate kiểm tra, pass thì MiniLM embed `text_for_embedding` (normalize, cosine) và ghi vào ChromaDB collection kèm metadata (title, authors, published, categories, summary).
2. **Evaluation set và ground-truth ID:** mỗi câu hỏi gắn DOI của bài được hỏi. `retrieval_hit` đúng khi DOI đó nằm trong top-4 kết quả. Câu trả lời lấy từ metadata của kết quả top-1 và so với ground truth bằng token F1. Vì vậy hit có thể đúng mà câu trả lời vẫn sai nếu top-1 là bài khác (eval_007, eval_010).
3. **Quality checks và freshness:** quality checks kiểm tra tính đúng cấu trúc của từng dòng/cột tại một thời điểm (null, unique, độ dài, số dòng). Freshness là tín hiệu tổng hợp theo thời gian (tỷ lệ bài có `age_days > 180` so với ngưỡng 25%) và phụ thuộc ngày chạy. Dữ liệu có thể pass GX nhưng vẫn stale (kịch bản `stale_date` không vi phạm expectation nào).
4. **Cùng test set:** nếu câu hỏi thay đổi giữa các trạng thái thì chênh lệch metric có thể do câu hỏi dễ/khó hơn chứ không phải do dữ liệu. Giữ nguyên `data/eval/test_set.json` cô lập biến dữ liệu là nguyên nhân duy nhất.
5. **Tiêu chí repair thành công:** `repaired_quality_report.json` có `success = true` (GX 7/7, fresh); 4 metric trong `repaired_metrics.json` bằng baseline; `repair.source_unchanged = true` và `repair.matches_baseline_content = true` trong `corruption_report.md`.

## 8. Phân tích kết quả

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0000 | 0.9000 | 1.0000 | Chỉ phản ánh bài bị xóa; không thấy lỗi top-1 |
| `mean_token_f1` | 1.0000 | 0.5000 | 1.0000 | Tín hiệu nhạy nhất: 5/10 câu sai |
| `judge_accuracy` | 1.0000 | 0.5000 | 1.0000 | Heuristic, bám theo F1 |
| `mean_judge_score` | 5 | 3 | 5 | Heuristic |
| Quality checks | 7/7 | 4/7 | 7/7 | Bắt được trùng, title ngắn, summary ngắn |
| Freshness status | Fresh (4,17%) | Stale (45,45%) | Fresh (4,17%) | Bắt được `stale_date` |

### Kết luận từ số liệu

1. `blank_summary` xóa summary của 3 bài → GX `summary` length FAIL (4 dòng tính cả bản trùng) → eval_001 (hỏi summary) trả về chuỗi rỗng, F1 = 0.
2. Gate fail → repair tự động từ raw → GX 7/7 và fresh trở lại → `mean_token_f1` và `retrieval_hit_rate` về 1.0, phục hồi 100%.

**Corruption ảnh hưởng rõ nhất:** `truncate_title`, với 2 câu sai trên 3 câu bị chạm. Tiêu đề bị cắt làm mất exact-match lookup, và semantic search chọn bài "anh em" cùng chủ đề làm top-1. `stale_date` chạm nhiều câu nhất (4) nhưng chỉ làm sai câu hỏi về ngày (eval_003), vì embedding của các câu hỏi khác hầu như không phụ thuộc ngày.

**Kết quả khác kỳ vọng:** tôi kỳ vọng `inject_noise` làm giảm F1 các câu summary. Thực tế bảng impact cho thấy 3 dòng bị nhiễu không trùng với bài nào trong 10 câu hỏi, nên metric không đổi và GX cũng không bắt (summary vẫn đủ dài, không null). Tôi đã kiểm tra bằng cách đối chiếu `corruption_log.json` với `ground_truth_doc_ids`. Kết luận: đây là silent failure hoàn toàn; cần expectation về nội dung hoặc test set phủ rộng hơn. Ngoài ra `duplicate_rows` không làm sai câu nào dù GX fail, vì bản trùng có cùng nội dung.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. **Data pipeline:** giữ raw bất biến và làm repair idempotent bằng cách chạy lại từ nguồn giúp phục hồi đơn giản và chứng minh được (hash nguồn, dấu vân tay nội dung), thay vì vá từng lỗi.
2. **Data quality/observability:** GX bắt tốt lỗi cấu trúc nhưng không bắt được lỗi nội dung (noise), và freshness là một chiều riêng. Cần thiết kế expectation theo từng kịch bản hỏng có thể xảy ra (tôi thêm check `title` ≥ 8 vì lý do này).
3. **Ảnh hưởng của data đến RAG agent:** metric retrieval (hit@4) có thể che giấu lỗi. Dữ liệu hỏng làm top-1 sai trong khi hit rate chỉ giảm 0,1 còn F1 giảm 0,5. Phải đọc nhiều metric cùng lúc và truy vết đến từng câu hỏi.

### Nếu có thêm thời gian

Tôi sẽ thêm expectation nội dung cho `summary`, ví dụ `ExpectColumnValuesToNotMatchRegex` với các ký tự rác như `#@!`, `0xDEAD`, `&&&`, hoặc ngưỡng tỷ lệ ký tự không phải chữ, và mở rộng test set lên 24 câu (mỗi bài một câu). Cách đo: chạy lại `run_corruption_flow.py` và kiểm tra (1) corrupted gate có thêm expectation `summary` noise bị FAIL, (2) bảng "Impact on the evaluation set" cho `inject_noise` có câu hỏi bị chạm. Tôi cũng sẽ bổ sung hit@1/MRR để đo trực tiếp lỗi top-1.

## 10. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi "đã chạy thành công" cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Tiến Phát
**Ngày xác nhận:** 2026-09-26

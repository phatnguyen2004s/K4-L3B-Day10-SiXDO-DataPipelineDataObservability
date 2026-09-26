# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `SiXDO`
- **Mã Nhóm / Lớp:** `K4-L3B-DAY10`
- **Tên Repository Nộp Bài:** `K4-L3B-Day10-SiXDO-DataPipelineDataObservability` — https://github.com/phatnguyen2004s/K4-L3B-Day10-SiXDO-DataPipelineDataObservability
- **Hình thức:** Làm cá nhân (nhóm 1 thành viên) — một người đảm nhận toàn bộ các khối việc.

---

## # Thành viên

| STT | Họ và tên | MSSV | Email | Vai trò & Phân công công việc | Báo cáo cá nhân |
|---:|---|---|---|---|---|
| 1 | Nguyễn Tiến Phát | 2A202602387 | phatnguyen.2004s@gmail.com | Toàn bộ pipeline: Pipeline Integrator (`core/`, `phase1.py`, `corruption_flow.py`), Data Foundation & Recovery (`crossref.py`, `cleaning.py`, `corruption.py`), RAG & Vector Index (ChromaDB, MiniLM), Observability & Evaluation (`quality.py`, `testset.py`, `metrics.py`, `reporting.py`), test suite | [`report/2A202602387_NguyenTienPhat.md`](../report/2A202602387_NguyenTienPhat.md) |

---

## # Cá nhân

### ## NguyenTienPhat-2A202602387
- **Vai trò:** Làm một mình — Trưởng nhóm, điều phối pipeline và sở hữu mọi module.
- **Công việc chi tiết đã hoàn thành:**
  - **Ingestion (`src/ingestion/crossref.py`):** parse payload Crossref thành `PaperRecord` (bỏ thẻ JATS/HTML, chuẩn hóa ngày, tác giả, subject); gọi API với retry/backoff cho 429/5xx (tôn trọng `Retry-After`), fallback về snapshot `data/raw/crossref_response.json`; lưu 2 raw artifact. Output parse khớp 24/24 bản ghi mẫu.
  - **Cleaning (`src/ingestion/cleaning.py`):** chuẩn hóa text, parse ngày về ISO, tính `age_days`, khử trùng lặp theo `paper_id` (không phân biệt hoa thường, giữ bản `updated` mới nhất), sinh `text_for_embedding` 5 phần; hàm `save_clean_dataframe`.
  - **Observability (`src/observability/quality.py`):** Quality Gate Great Expectations 1.x (Ephemeral Context) với 4 expectation bắt buộc + kiểm tra độ dài `title` ≥ 8; Freshness SLA (`is_fresh=False` nếu > 25% bài có `age_days > 180`).
  - **Evaluation (`src/evaluation/testset.py`, `metrics.py`):** bộ test 10 câu deterministic (summary 3, authors 3, date 2, categories 2); thêm `judge_backend`, retry khi LLM hết quota và `JUDGE_MODE`.
  - **Corruption & Repair (`src/ingestion/corruption.py`, `src/pipelines/corruption_flow.py`):** 6 kịch bản lỗi seed cố định, log chi tiết từng dòng; repair idempotent từ raw snapshot, tự kích hoạt khi quality gate fail; phân tích tác động theo từng kịch bản.
  - **Orchestration & Reporting (`src/pipelines/phase1.py`, `src/observability/reporting.py`):** nối 6 bước Phase 1, quality gate chặn dữ liệu lỗi trước khi index, sinh `phase1_report.md` và `corruption_report.md`.
  - **Test (`tests/`, `script/run_tests.sh` (one-click test)):** 52 test pytest, coverage 94%.
- **Điều học được / Đóng góp chính:**
  - Quality gate chỉ bắt được lỗi cấu trúc (null, unique, độ dài, freshness); lỗi nội dung như chèn nhiễu vẫn lọt qua → cần kết hợp metric của agent và kiểm tra nội dung.
  - Repair phải dựng lại từ nguồn raw bất biến (idempotent) thay vì vá từng lỗi trên dữ liệu hỏng.

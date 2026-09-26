from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import shutil

import pytest

# Khong ton quota LLM: dat truoc khi bat ky module nao goi load_dotenv().
# Chi bat HF offline khi MiniLM da co trong cache (CI lan dau van tai duoc model).
_HF_HOME = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
if (_HF_HOME / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots").exists():
    os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JUDGE_MODE"] = "heuristic"
os.environ["REFRESH_SOURCE"] = ""
os.environ["REFRESH_TEST_SET"] = ""
os.environ.pop("GOOGLE_API_KEY", None)

from core.config import Settings, load_settings  # noqa: E402
from ingestion.cleaning import build_clean_dataframe  # noqa: E402
from ingestion.crossref import load_raw_records  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW_FILES = ("crossref_response.json", "crossref_records.json")
RUN_DATE = datetime(2026, 9, 26, tzinfo=UTC)


def make_project(root: Path) -> Settings:
    """Tao project tam chi chua raw snapshot -> test khong dung vao artifact that."""
    raw_dir = root / "data" / "raw"
    raw_dir.mkdir(parents=True)
    for name in RAW_FILES:
        shutil.copy(PROJECT_DIR / "data" / "raw" / name, raw_dir / name)
    return load_settings(root)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_project(tmp_path / "project")


@pytest.fixture
def raw_records():
    return load_raw_records(PROJECT_DIR / "data" / "raw" / "crossref_records.json")


@pytest.fixture
def clean_df(raw_records):
    return build_clean_dataframe(raw_records, RUN_DATE)

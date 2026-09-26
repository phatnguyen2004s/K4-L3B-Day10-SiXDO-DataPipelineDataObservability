from __future__ import annotations

from core.utils import read_json
from ingestion.corruption import corrupt_clean_dataframe
from observability.quality import build_freshness_report, evaluate_freshness_sla, run_data_quality_checks


def test_baseline_passes_quality_gate(clean_df, settings):
    report = run_data_quality_checks(clean_df, settings, "baseline")
    assert report["success"] is True
    assert report["gx"]["evaluated_expectations"] == 7
    assert report["gx"]["failed_expectations"] == []
    assert settings.paths.baseline_quality_report.exists()
    assert (settings.paths.gx_dir / "baseline_expectation_suite.json").exists()


def test_freshness_sla_threshold(clean_df, settings):
    fresh = evaluate_freshness_sla(clean_df, settings)
    assert fresh["is_fresh"] is True
    assert fresh["stale_rows"] == 1

    stale_df = clean_df.copy()
    stale_df.loc[: len(stale_df) // 2, "age_days"] = 400
    assert evaluate_freshness_sla(stale_df, settings)["is_fresh"] is False
    assert evaluate_freshness_sla(clean_df.head(0), settings)["is_fresh"] is False


def test_build_freshness_report_writes_json(clean_df, settings):
    payload = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    assert read_json(settings.paths.freshness_report)["latest_published"] == payload["latest_published"]


def test_corruption_injects_six_scenarios(clean_df, settings):
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    log = read_json(settings.paths.corruption_log)

    assert len(corrupted) == 22
    assert [item["scenario"] for item in log["scenarios"]] == [
        "drop_latest_records",
        "blank_summary",
        "inject_noise",
        "truncate_title",
        "stale_date",
        "duplicate_rows",
    ]
    dropped = {change["paper_id"] for change in log["scenarios"][0]["changes"]}
    assert dropped == set(clean_df.head(5)["paper_id"])
    assert (corrupted["summary"] == "").sum() >= 3
    assert (corrupted["title"].str.len() < 8).sum() >= 3
    assert corrupted["paper_id"].duplicated().sum() == 3
    assert all(text.startswith(f"Title: {title}") for text, title in zip(corrupted["text_for_embedding"], corrupted["title"]))


def test_corruption_is_deterministic(clean_df, settings, tmp_path):
    first = corrupt_clean_dataframe(clean_df, tmp_path / "a.json")
    second = corrupt_clean_dataframe(clean_df, tmp_path / "b.json")
    assert first.equals(second)


def test_quality_gate_catches_corruption(clean_df, settings):
    corrupted = corrupt_clean_dataframe(clean_df, settings.paths.corruption_log)
    report = run_data_quality_checks(corrupted, settings, "corrupted")
    assert report["success"] is False
    assert report["is_fresh"] is False
    assert set(report["gx"]["failed_expectations"]) == {
        "expect_column_values_to_be_unique(paper_id)",
        "expect_column_value_lengths_to_be_between(title)",
        "expect_column_value_lengths_to_be_between(summary)",
    }

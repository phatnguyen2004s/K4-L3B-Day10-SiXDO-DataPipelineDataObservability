from __future__ import annotations

import os
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import now_utc, write_json

# Tat usage analytics cua GX truoc khi import (khong gui request ra ngoai khi chay lab).
os.environ.setdefault("GX_ANALYTICS_ENABLED", "false")

import great_expectations as gx  # noqa: E402
import great_expectations.expectations as gxe  # noqa: E402

MIN_ROWS = 5
MAX_ROWS = 5000
REQUIRED_COLUMNS = ("paper_id", "title", "text_for_embedding")
MIN_SUMMARY_CHARS = 30
MIN_TITLE_CHARS = 8
MAX_STALE_RATIO = 0.25


def _build_expectations() -> list[gxe.Expectation]:
    expectations: list[gxe.Expectation] = [
        gxe.ExpectTableRowCountToBeBetween(min_value=MIN_ROWS, max_value=MAX_ROWS),
    ]
    expectations += [gxe.ExpectColumnValuesToNotBeNull(column=column) for column in REQUIRED_COLUMNS]
    expectations += [
        gxe.ExpectColumnValuesToBeUnique(column="paper_id"),
        gxe.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=MIN_SUMMARY_CHARS),
        # Bo sung ngoai 4 expectation bat buoc: bat loi title bi cat ngan (< 8 ky tu).
        gxe.ExpectColumnValueLengthsToBeBetween(column="title", min_value=MIN_TITLE_CHARS),
    ]
    return expectations


def _summarize_result(result: Any) -> dict[str, Any]:
    config = result.expectation_config
    details = result.result or {}
    return {
        "expectation": config.type,
        "column": config.kwargs.get("column"),
        "kwargs": {key: value for key, value in config.kwargs.items() if key not in {"batch_id", "column"}},
        "success": bool(result.success),
        "observed_value": details.get("observed_value"),
        "unexpected_count": details.get("unexpected_count"),
        "unexpected_percent": details.get("unexpected_percent"),
        "partial_unexpected_list": [str(value) for value in details.get("partial_unexpected_list", [])[:5]],
    }


def run_gx_validation(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Validate dataframe bang Great Expectations 1.x Ephemeral Context."""
    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": df})

    suite = context.suites.add(gx.ExpectationSuite(name=f"papers_{report_name}_suite"))
    for expectation in _build_expectations():
        suite.add_expectation(expectation)

    validation = batch.validate(suite)
    write_json(settings.paths.gx_dir / f"{report_name}_expectation_suite.json", suite.to_json_dict())

    checks = [_summarize_result(result) for result in validation.results]
    return {
        "success": bool(validation.success),
        "evaluated_expectations": len(checks),
        "successful_expectations": sum(check["success"] for check in checks),
        "failed_expectations": [check["expectation"] + (f"({check['column']})" if check["column"] else "") for check in checks if not check["success"]],
        "checks": checks,
    }


def evaluate_freshness_sla(df: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    """Freshness SLA: `is_fresh=False` neu ty le bai co `age_days > threshold` vuot 25%."""
    threshold = settings.freshness_threshold_days
    total_rows = int(len(df))
    ages = pd.to_numeric(df["age_days"], errors="coerce") if "age_days" in df else pd.Series(dtype=float)
    published = pd.to_datetime(df["published"], errors="coerce") if "published" in df else pd.Series(dtype="datetime64[ns]")

    stale_rows = int((ages > threshold).sum())
    missing_age_rows = int(ages.isna().sum())
    stale_ratio = stale_rows / total_rows if total_rows else 1.0
    return {
        "threshold_days": threshold,
        "max_stale_ratio": MAX_STALE_RATIO,
        "total_rows": total_rows,
        "stale_rows": stale_rows,
        "missing_age_rows": missing_age_rows,
        "stale_ratio": round(stale_ratio, 4),
        "latest_published": published.max().date().isoformat() if published.notna().any() else None,
        "oldest_published": published.min().date().isoformat() if published.notna().any() else None,
        "median_age_days": float(ages.median()) if ages.notna().any() else None,
        "max_age_days": int(ages.max()) if ages.notna().any() else None,
        "is_fresh": bool(total_rows > 0 and stale_ratio <= MAX_STALE_RATIO),
    }


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Quality gate = GX 1.x expectations + Freshness SLA; ghi `data/quality/<report_name>_quality_report.json`."""
    gx_result = run_gx_validation(df, settings, report_name)
    freshness = evaluate_freshness_sla(df, settings)
    report = {
        "report_name": report_name,
        "checked_at": now_utc().isoformat(),
        "row_count": int(len(df)),
        "success": gx_result["success"] and freshness["is_fresh"],
        "gx_success": gx_result["success"],
        "is_fresh": freshness["is_fresh"],
        "gx": gx_result,
        "freshness": freshness,
    }
    write_json(settings.paths.quality_dir / f"{report_name}_quality_report.json", report)
    return report


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Tong hop freshness report va ghi JSON vao `report_path`."""
    payload = {"generated_at": now_utc().isoformat(), **evaluate_freshness_sla(df, settings)}
    write_json(report_path, payload)
    return payload

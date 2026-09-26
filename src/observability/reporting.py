from __future__ import annotations

from typing import Any

from core.utils import now_utc, write_text

CORE_METRICS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score")


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:.4f}"
    if value is None:
        return "-"
    return str(value)


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    lines += ["| " + " | ".join(_fmt(cell) for cell in row) + " |" for row in rows]
    return lines


def _quality_lines(quality: dict[str, Any]) -> list[str]:
    gx_result = quality.get("gx", {})
    lines = [
        f"- Overall quality gate: **{_fmt(quality.get('success'))}** "
        f"(GX: {_fmt(quality.get('gx_success'))}, freshness: {_fmt(quality.get('is_fresh'))})",
        f"- Expectations passed: {gx_result.get('successful_expectations', 0)}/{gx_result.get('evaluated_expectations', 0)}",
        "",
    ]
    rows = [
        [
            check["expectation"],
            check.get("column") or "(table)",
            check["success"],
            check.get("observed_value"),
            check.get("unexpected_count"),
        ]
        for check in gx_result.get("checks", [])
    ]
    return lines + _table(["Expectation", "Column", "Result", "Observed", "Unexpected"], rows)


def _freshness_lines(freshness: dict[str, Any]) -> list[str]:
    rows = [
        ["Threshold (days)", freshness.get("threshold_days")],
        ["Max stale ratio", freshness.get("max_stale_ratio")],
        ["Stale rows", f"{freshness.get('stale_rows')}/{freshness.get('total_rows')}"],
        ["Stale ratio", freshness.get("stale_ratio")],
        ["Latest published", freshness.get("latest_published")],
        ["Oldest published", freshness.get("oldest_published")],
        ["Median age (days)", freshness.get("median_age_days")],
        ["is_fresh", freshness.get("is_fresh")],
    ]
    return _table(["Signal", "Value"], rows)


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Viet markdown report cho baseline phase (source, metrics, quality, freshness)."""
    lines = [
        "# Phase 1 Report - Baseline Pipeline",
        "",
        f"_Generated at {now_utc().isoformat()}_",
        "",
        "## 1. Source & artifacts",
        "",
        *_table(["Item", "Value"], [[key, value] for key, value in source_summary.items()]),
        "",
        "## 2. Baseline evaluation",
        "",
        *_table(["Metric", "Value"], [[name, metrics.get(name)] for name in ("samples", *CORE_METRICS, "judge_backend")]),
        "",
        f"- Ragas: {metrics.get('ragas')}",
        "",
        "## 3. Data quality gate (Great Expectations 1.x)",
        "",
        *_quality_lines(quality),
        "",
        "## 4. Freshness SLA",
        "",
        *_freshness_lines(freshness),
        "",
    ]
    write_text(report_path, "\n".join(lines))


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
    baseline_quality: dict[str, Any] | None = None,
    baseline_freshness: dict[str, Any] | None = None,
    corruption_log: dict[str, Any] | None = None,
    repair_info: dict[str, Any] | None = None,
    scenario_impact: list[dict[str, Any]] | None = None,
) -> None:
    """Viet markdown report so sanh baseline/corrupted/repaired; nhan xet sinh tu so lieu thuc te."""
    stages = {"Baseline": baseline_metrics, "Corrupted": corrupted_metrics, "Repaired": repaired_metrics}

    metric_rows = []
    observations = []
    for name in CORE_METRICS:
        base, corr, rep = (stage.get(name) for stage in stages.values())
        if not all(isinstance(value, int | float) for value in (base, corr, rep)):
            metric_rows.append([name, base, corr, rep, "-", "-"])
            continue
        drop = corr - base
        recovery = "n/a (no drop)" if drop >= 0 else f"{(rep - corr) / (base - corr):.0%}"
        metric_rows.append([name, float(base), float(corr), float(rep), f"{drop:+.4f}", recovery])
        if drop < 0:
            observations.append(f"`{name}` giam {abs(drop):.4f} khi corrupted ({base:.4f} -> {corr:.4f}), repaired dat {rep:.4f}.")
        else:
            observations.append(f"`{name}` khong giam khi corrupted ({base:.4f} -> {corr:.4f}).")

    qualities = [baseline_quality, corrupted_quality, repaired_quality]
    freshnesses = [baseline_freshness, corrupted_freshness, repaired_freshness]

    def _gx_passed(quality: dict[str, Any] | None) -> str:
        if not quality:
            return "-"
        gx_result = quality.get("gx", {})
        return f"{gx_result.get('successful_expectations')}/{gx_result.get('evaluated_expectations')}"

    signal_rows = [
        ["Row count", *[q.get("row_count") if q else None for q in qualities]],
        ["GX expectations passed", *[_gx_passed(q) for q in qualities]],
        ["GX success", *[q.get("gx_success") if q else None for q in qualities]],
        ["Stale ratio (age > threshold)", *[f.get("stale_ratio") if f else None for f in freshnesses]],
        ["is_fresh", *[f.get("is_fresh") if f else None for f in freshnesses]],
        ["Quality gate (GX + freshness)", *[q.get("success") if q else None for q in qualities]],
    ]

    expectation_names: list[tuple[str, str | None]] = []
    for quality in qualities:
        for check in (quality or {}).get("gx", {}).get("checks", []):
            key = (check["expectation"], check.get("column"))
            if key not in expectation_names:
                expectation_names.append(key)

    def _check_cell(quality: dict[str, Any] | None, key: tuple[str, str | None]) -> str:
        for check in (quality or {}).get("gx", {}).get("checks", []):
            if (check["expectation"], check.get("column")) == key:
                unexpected = check.get("unexpected_count")
                suffix = f" ({unexpected} unexpected)" if unexpected else ""
                return ("PASS" if check["success"] else "FAIL") + suffix
        return "-"

    expectation_rows = [
        [f"{name}({column})" if column else name, *[_check_cell(q, (name, column)) for q in qualities]]
        for name, column in expectation_names
    ]

    lines = [
        "# Corruption Report - Baseline vs Corrupted vs Repaired",
        "",
        f"_Generated at {now_utc().isoformat()}_",
        "",
        "Cung mot evaluation set (`data/eval/test_set.json`) cho ca 3 trang thai.",
        f"Judge backend: baseline={baseline_metrics.get('judge_backend', '-')}, "
        f"corrupted={corrupted_metrics.get('judge_backend', '-')}, repaired={repaired_metrics.get('judge_backend', '-')}.",
        "",
        "## 1. Agent metrics",
        "",
        *_table(["Metric", "Baseline", "Corrupted", "Repaired", "Delta (corrupted - baseline)", "Recovery"], metric_rows),
        "",
        "## 2. Data quality & freshness signals",
        "",
        *_table(["Signal", "Baseline", "Corrupted", "Repaired"], signal_rows),
        "",
        "### GX expectations by state",
        "",
        *_table(["Expectation", "Baseline", "Corrupted", "Repaired"], expectation_rows),
        "",
    ]

    if corruption_log:
        scenario_rows = [
            [item["scenario"], item["affected_rows"], ", ".join(f"{k}={v}" for k, v in item["params"].items() if k != "tokens")]
            for item in corruption_log.get("scenarios", [])
        ]
        lines += [
            "## 3. Corruption scenarios",
            "",
            f"- Rows: {corruption_log.get('input_rows')} -> {corruption_log.get('output_rows')} (seed={corruption_log.get('seed')})",
            "- Chi tiet tung dong bi bien doi: `data/results/corruption_log.json`",
            "",
            *_table(["Scenario", "Affected rows", "Params"], scenario_rows),
            "",
        ]

    if scenario_impact:
        impact_rows = [
            [
                item["scenario"],
                item["affected_rows"],
                ", ".join(item["test_questions_touched"]) or "none",
                ", ".join(item["test_questions_failed"]) or "none",
            ]
            for item in scenario_impact
        ]
        lines += [
            "### Impact on the evaluation set",
            "",
            "Cau hoi 'failed' = retrieval miss hoac token F1 < 0.5 tren corrupted index. "
            "Mot cau hoi co the bi nhieu scenario cung cham.",
            "",
            *_table(["Scenario", "Rows", "Test questions touched", "Failed"], impact_rows),
            "",
        ]

    if repair_info:
        lines += ["## 4. Repair", "", *_table(["Item", "Value"], [[k, v] for k, v in repair_info.items()]), ""]

    corrupted_failed = corrupted_quality.get("gx", {}).get("failed_expectations", [])
    noise = next((item for item in scenario_impact or [] if item["scenario"] == "inject_noise"), None)
    if noise is None:
        noise_note = "`inject_noise` khong vi pham expectation nao (summary van du dai, khong null) -> GX khong bat duoc."
    elif not noise["test_questions_touched"]:
        noise_note = (
            "`inject_noise` khong vi pham expectation nao va khong cham cau hoi nao trong test set -> "
            "ca quality gate lan metric deu khong thay: silent failure hoan toan (can them check noi dung, vd ty le token la)."
        )
    else:
        noise_note = (
            f"`inject_noise` khong vi pham expectation nao; cham {len(noise['test_questions_touched'])} cau hoi test, "
            f"lam hong {len(noise['test_questions_failed'])} -> silent failure chi lo ra qua metric."
        )
    lines += [
        "## 5. Observations (tu dong tu so lieu)",
        "",
        *[f"- {text}" for text in observations],
        f"- Quality gate tren corrupted: {_fmt(corrupted_quality.get('success'))}; expectation fail: "
        f"{', '.join(corrupted_failed) or 'none'}; is_fresh={corrupted_freshness.get('is_fresh')} "
        f"(stale_ratio={corrupted_freshness.get('stale_ratio')}).",
        f"- Quality gate tren repaired: {_fmt(repaired_quality.get('success'))}.",
        f"- {noise_note}",
        "",
    ]
    write_text(report_path, "\n".join(lines))

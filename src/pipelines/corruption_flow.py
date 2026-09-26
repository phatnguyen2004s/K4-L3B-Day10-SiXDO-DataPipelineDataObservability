from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe, save_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records, parse_crossref_payload
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import CORE_METRICS, generate_corruption_report
from retrieval.index import LocalEmbeddingIndex

# Cot khong phu thuoc ngay chay -> dung de so repaired voi baseline.
CONTENT_COLUMNS = ["paper_id", "title", "summary", "published", "authors_joined", "categories_joined", "text_for_embedding"]


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_baseline(settings: Settings) -> None:
    paths = settings.paths
    missing = [p for p in (paths.clean_json, paths.baseline_metrics, paths.eval_testset, paths.raw_records_json) if not p.exists()]
    if missing:
        names = ", ".join(str(p.relative_to(paths.project_dir)) for p in missing)
        raise FileNotFoundError(f"Missing baseline artifacts ({names}). Run `python script/run_phase1.py` first.")


def _content_fingerprint(df: pd.DataFrame) -> str:
    content = df[CONTENT_COLUMNS].sort_values("paper_id").to_json(orient="records")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _evaluate_stage(settings: Settings, df: pd.DataFrame, stage: str) -> dict[str, Any]:
    paths = settings.paths
    embeddings_path = {"corrupted": paths.corrupted_embeddings_json, "repaired": paths.repaired_embeddings_json}[stage]
    metrics_path = {"corrupted": paths.corrupted_metrics, "repaired": paths.repaired_metrics}[stage]
    answers_path = {"corrupted": paths.corrupted_answers, "repaired": paths.repaired_answers}[stage]
    index = LocalEmbeddingIndex.build(df, settings, embeddings_path)
    return evaluate_pipeline(settings, index, paths.eval_testset, metrics_path, answers_path).summary


def scenario_impact(corruption_log: dict[str, Any], corrupted_answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Moi scenario cham toi cau hoi test nao (qua ground-truth doc) va lam hong bao nhieu cau.

    Mot cau hoi bi coi la hong khi retrieval miss hoac token F1 < 0.5 tren corrupted index.
    """
    impact = []
    for scenario in corruption_log["scenarios"]:
        touched_docs = {change["paper_id"] for change in scenario["changes"]}
        touched = [a for a in corrupted_answers if set(a["ground_truth_doc_ids"]) & touched_docs]
        failed = [a for a in touched if not a["retrieval_hit"] or a["token_f1"] < 0.5]
        impact.append(
            {
                "scenario": scenario["scenario"],
                "affected_rows": scenario["affected_rows"],
                "test_questions_touched": [a["id"] for a in touched],
                "test_questions_failed": [a["id"] for a in failed],
            }
        )
    return impact


def repair_from_raw_snapshot(settings: Settings, run_date=None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Idempotent repair: dung lai clean dataset tu raw snapshot bat bien, ghi de artifact repaired.

    Khong sua tung loi tren dataframe hong; chay lai tu nguon raw nen chay 1 hay n lan deu cho
    cung ket qua. Raw file chi duoc doc, khong ghi.
    """
    paths = settings.paths
    run_date = run_date or now_utc()
    if paths.raw_records_json.exists():
        source_path = paths.raw_records_json
        records = load_raw_records(source_path)
    else:
        source_path = paths.raw_api_response
        records = parse_crossref_payload(read_json(source_path))

    source_hash_before = _sha256(source_path)
    repaired = build_clean_dataframe(records, run_date)
    save_clean_dataframe(repaired, paths.repaired_clean_csv, paths.repaired_clean_json)
    info = {
        "source": str(source_path.relative_to(paths.project_dir)),
        "source_sha256": source_hash_before,
        "source_unchanged": _sha256(source_path) == source_hash_before,
        "raw_records": len(records),
        "repaired_rows": len(repaired),
    }
    return repaired, info


def run_corruption_flow_pipeline(settings: Settings) -> dict[str, Any]:
    """Baseline -> Corrupt -> Evaluate (silent failure) -> Auto repair -> Evaluate -> Compare."""
    _require_baseline(settings)
    paths = settings.paths
    run_date = now_utc()
    baseline_metrics = read_json(paths.baseline_metrics)
    baseline_df = pd.DataFrame(read_json(paths.clean_json))
    baseline_quality = read_json(paths.baseline_quality_report) if paths.baseline_quality_report.exists() else None
    baseline_freshness = read_json(paths.freshness_report) if paths.freshness_report.exists() else None

    print("[corruption] 1/5 Inject 6 corruption scenarios")
    corrupted_df = corrupt_clean_dataframe(baseline_df, paths.corruption_log)
    save_clean_dataframe(corrupted_df, paths.corrupted_clean_csv, paths.corrupted_clean_json)

    print("[corruption] 2/5 Quality gate on corrupted data")
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = build_freshness_report(corrupted_df, settings, paths.quality_dir / "corrupted_freshness_report.json")

    # Co y index du lieu hong (bo qua gate) de do tac dong neu khong co observability -> silent failure.
    print("[corruption] 3/5 Index + evaluate corrupted data (gate bypassed on purpose)")
    corrupted_metrics = _evaluate_stage(settings, corrupted_df, "corrupted")

    repair_trigger = (
        f"quality gate failed: {corrupted_quality['gx']['failed_expectations']}, is_fresh={corrupted_quality['is_fresh']}"
        if not corrupted_quality["success"]
        else "quality gate passed; repair run for comparison only"
    )
    print(f"[corruption] 4/5 Auto repair from raw snapshot ({repair_trigger})")
    repaired_df, repair_info = repair_from_raw_snapshot(settings, run_date)
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    repaired_freshness = build_freshness_report(repaired_df, settings, paths.quality_dir / "repaired_freshness_report.json")
    if not repaired_quality["gx_success"]:
        raise RuntimeError(f"Repaired data still fails GX checks: {repaired_quality['gx']['failed_expectations']}")
    repair_info |= {
        "trigger": repair_trigger,
        "matches_baseline_content": _content_fingerprint(repaired_df) == _content_fingerprint(baseline_df),
    }

    print("[corruption] 5/5 Index + evaluate repaired data, write report")
    repaired_metrics = _evaluate_stage(settings, repaired_df, "repaired")
    corruption_log = read_json(paths.corruption_log)
    impact = scenario_impact(corruption_log, read_json(paths.corrupted_answers))
    generate_corruption_report(
        paths.comparison_report,
        baseline_metrics,
        corrupted_metrics,
        repaired_metrics,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
        baseline_quality=baseline_quality,
        baseline_freshness=baseline_freshness,
        corruption_log=corruption_log,
        repair_info=repair_info,
        scenario_impact=impact,
    )
    return {
        "baseline": baseline_metrics,
        "corrupted": corrupted_metrics,
        "repaired": repaired_metrics,
        "baseline_quality": baseline_quality,
        "corrupted_quality": corrupted_quality,
        "repaired_quality": repaired_quality,
        "repair": repair_info,
        "scenario_impact": impact,
    }


def _print_comparison(result: dict[str, Any]) -> None:
    header = f"{'Metric':<22}{'Baseline':>10}{'Corrupted':>11}{'Repaired':>10}"
    print("\n" + header + "\n" + "-" * len(header))
    for name in CORE_METRICS:
        values = [result[stage].get(name) for stage in ("baseline", "corrupted", "repaired")]
        print(f"{name:<22}" + "".join(f"{value:>10.4f} " if isinstance(value, float | int) else f"{'-':>10} " for value in values))
    gates = [result["baseline_quality"], result["corrupted_quality"], result["repaired_quality"]]
    labels = ["-" if gate is None else "PASS" if gate["success"] else "FAIL" for gate in gates]
    print(f"{'quality_gate':<22}{labels[0]:>10}{labels[1]:>11}{labels[2]:>10}")


def main() -> None:
    settings = load_settings()
    result = run_corruption_flow_pipeline(settings)
    _print_comparison(result)
    print(f"\n[corruption] Report: {settings.paths.comparison_report.relative_to(settings.paths.project_dir)}")

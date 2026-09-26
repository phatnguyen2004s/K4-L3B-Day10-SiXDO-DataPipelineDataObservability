from __future__ import annotations

from typing import Any

from core.config import Settings, load_settings, normalized_provider, require_llm_credentials
from core.utils import now_utc, read_json, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe, save_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex

DEMO_QUESTION_COUNT = 2


class QualityGateError(RuntimeError):
    """Du lieu khong qua GX quality gate -> khong duoc dua vao vector store."""


def _load_or_build_test_set(df, settings: Settings) -> list[dict[str, Any]]:
    """Giu nguyen test set da co (de so sanh baseline/corrupted/repaired), tru khi REFRESH_TEST_SET=1."""
    path = settings.paths.eval_testset
    if path.exists() and not settings.refresh_test_set:
        test_set = read_json(path)
        known_ids = set(df["paper_id"])
        if test_set and all(set(item["ground_truth_doc_ids"]) <= known_ids for item in test_set):
            return test_set
        print("[phase1] Existing test set references unknown documents -> rebuilding.")
    return build_test_set(df, path)


def _run_agent_demo(settings: Settings, index: LocalEmbeddingIndex, test_set: list[dict[str, Any]]) -> None:
    """Demo agent tren vai cau hoi; bo qua neu chua cau hinh LLM that."""
    try:
        require_llm_credentials(settings)
    except RuntimeError as exc:
        print(f"[phase1] Skip agent demo: {exc}")
        return
    if normalized_provider(settings) == "mock":
        print("[phase1] Skip agent demo: LLM_PROVIDER=mock.")
        return

    from retrieval.agent import build_agent, run_agent_question

    answers = []
    try:
        agent = build_agent(settings, index)
        for item in test_set[:DEMO_QUESTION_COUNT]:
            answers.append({"question": item["question"], "answer": run_agent_question(agent, item["question"])})
    except Exception as exc:  # demo khong duoc lam hong baseline pipeline
        answers.append({"error": f"{type(exc).__name__}: {exc}"})
    write_json(settings.paths.demo_answers, answers)


def run_phase1_pipeline(settings: Settings) -> dict[str, Any]:
    """Ingest -> Clean -> Quality gate -> Index ChromaDB -> Testset -> Evaluate -> Report."""
    paths = settings.paths
    run_date = now_utc()

    print("[phase1] 1/6 Ingest raw records")
    records = fetch_source_records(settings)

    print("[phase1] 2/6 Clean dataset")
    df = build_clean_dataframe(records, run_date)
    save_clean_dataframe(df, paths.clean_csv, paths.clean_json)

    print("[phase1] 3/6 Quality gate (GX 1.x + freshness SLA)")
    quality = run_data_quality_checks(df, settings, "baseline")
    freshness = build_freshness_report(df, settings, paths.freshness_report)
    if not quality["gx_success"]:
        raise QualityGateError(f"Baseline data failed GX checks: {quality['gx']['failed_expectations']}")
    if not freshness["is_fresh"]:
        print(f"[phase1] WARNING: freshness SLA violated (stale_ratio={freshness['stale_ratio']}).")

    print("[phase1] 4/6 Build ChromaDB index")
    index = LocalEmbeddingIndex.build(df, settings, paths.embeddings_json)

    print("[phase1] 5/6 Evaluate baseline")
    test_set = _load_or_build_test_set(df, settings)
    bundle = evaluate_pipeline(settings, index, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers)

    print("[phase1] 6/6 Write report")
    source_summary = {
        "source_api": settings.source_api,
        "query": settings.source_query,
        "filter": settings.source_filter,
        "run_date": run_date.isoformat(),
        "raw_records": len(records),
        "clean_rows": len(df),
        "duplicates_or_invalid_dropped": len(records) - len(df),
        "embedding_model": settings.embedding_model,
        "collection": index.collection_name,
        "top_k": settings.top_k,
        "llm_provider": settings.llm_provider,
        "test_set_size": len(test_set),
    }
    generate_phase1_report(paths.baseline_report, source_summary, bundle.summary, quality, freshness)
    _run_agent_demo(settings, index, test_set)

    return {"source": source_summary, "metrics": bundle.summary, "quality": quality, "freshness": freshness}


def main() -> None:
    result = run_phase1_pipeline(load_settings())
    metrics = result["metrics"]
    print(
        "[phase1] Done: "
        f"clean_rows={result['source']['clean_rows']}, "
        f"retrieval_hit_rate={metrics['retrieval_hit_rate']:.4f}, "
        f"mean_token_f1={metrics['mean_token_f1']:.4f}, "
        f"quality_success={result['quality']['success']}"
    )

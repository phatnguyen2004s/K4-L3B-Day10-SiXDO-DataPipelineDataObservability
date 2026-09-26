"""End-to-end: phase1 -> corruption flow tren project tam (MiniLM that, ChromaDB that, LLM mock)."""

from __future__ import annotations

import pandas as pd
import pytest

from conftest import make_project
from core.utils import read_json
from pipelines import corruption_flow, phase1
from retrieval.index import LocalEmbeddingIndex
from retrieval.qa import answer_question


@pytest.fixture(scope="module")
def pipeline_run(tmp_path_factory):
    settings = make_project(tmp_path_factory.mktemp("e2e") / "project")
    phase1_result = phase1.run_phase1_pipeline(settings)
    flow_result = corruption_flow.run_corruption_flow_pipeline(settings)
    return settings, phase1_result, flow_result


def test_phase1_produces_baseline_artifacts(pipeline_run):
    settings, result, _ = pipeline_run
    paths = settings.paths
    for path in (
        paths.raw_records_json,
        paths.clean_csv,
        paths.clean_json,
        paths.embeddings_json,
        paths.eval_testset,
        paths.baseline_metrics,
        paths.baseline_answers,
        paths.baseline_quality_report,
        paths.freshness_report,
        paths.baseline_report,
    ):
        assert path.exists(), path
    assert result["source"]["clean_rows"] == 24
    assert result["metrics"]["retrieval_hit_rate"] == 1.0
    assert result["metrics"]["judge_backend"] == "heuristic_fallback"
    report = paths.baseline_report.read_text()
    assert "retrieval_hit_rate" in report and "Freshness SLA" in report


def test_manifest_uses_relative_persist_path(pipeline_run):
    settings, _, _ = pipeline_run
    manifest = read_json(settings.paths.embeddings_json)
    assert manifest["persist_path"] == "data/chroma"
    index = LocalEmbeddingIndex.load(settings)
    assert index.persist_path == settings.paths.chroma_dir
    assert index.lookup(manifest["documents"][0]["paper_id"].upper()) is not None


def test_answer_question_exact_title_lookup(pipeline_run):
    settings, _, _ = pipeline_run
    item = read_json(settings.paths.eval_testset)[1]
    answer = answer_question(item["question"], settings, LocalEmbeddingIndex.load(settings))
    assert answer.retrieved_doc_ids[0] == item["ground_truth_doc_ids"][0]
    assert answer.answer == item["ground_truth"]


def test_corruption_degrades_and_repair_recovers(pipeline_run):
    settings, _, result = pipeline_run
    baseline, corrupted, repaired = result["baseline"], result["corrupted"], result["repaired"]
    assert corrupted["mean_token_f1"] < baseline["mean_token_f1"]
    assert corrupted["retrieval_hit_rate"] < baseline["retrieval_hit_rate"]
    assert repaired["mean_token_f1"] == baseline["mean_token_f1"]
    assert result["corrupted_quality"]["success"] is False
    assert result["repaired_quality"]["success"] is True
    assert result["repair"]["source_unchanged"] is True
    assert result["repair"]["matches_baseline_content"] is True
    report = settings.paths.comparison_report.read_text()
    assert "| retrieval_hit_rate |" in report and "Repaired" in report
    assert "Impact on the evaluation set" in report


def test_scenario_impact_links_corruption_to_failed_questions(pipeline_run):
    settings, _, result = pipeline_run
    impact = {item["scenario"]: item for item in result["scenario_impact"]}
    assert len(impact) == 6
    answers = {a["id"]: a for a in read_json(settings.paths.corrupted_answers)}
    for item in impact.values():
        assert set(item["test_questions_failed"]) <= set(item["test_questions_touched"])
    for question_id in impact["drop_latest_records"]["test_questions_touched"]:
        assert answers[question_id]["retrieval_hit"] is False


def test_repair_is_idempotent(pipeline_run):
    settings, _, _ = pipeline_run
    first, _ = corruption_flow.repair_from_raw_snapshot(settings)
    second, _ = corruption_flow.repair_from_raw_snapshot(settings)
    pd.testing.assert_frame_equal(first, second)


def test_repair_falls_back_to_raw_api_response(pipeline_run, tmp_path):
    settings = make_project(tmp_path / "project")
    settings.paths.raw_records_json.unlink()
    repaired, info = corruption_flow.repair_from_raw_snapshot(settings)
    assert len(repaired) == 24
    assert info["source"] == "data/raw/crossref_response.json"


def test_corruption_flow_requires_baseline(tmp_path):
    settings = make_project(tmp_path / "project")
    with pytest.raises(FileNotFoundError, match="run_phase1.py"):
        corruption_flow.run_corruption_flow_pipeline(settings)


def test_entrypoints_print_summary(pipeline_run, monkeypatch, capsys):
    settings, _, _ = pipeline_run
    monkeypatch.setattr(phase1, "load_settings", lambda: settings)
    monkeypatch.setattr(corruption_flow, "load_settings", lambda: settings)
    phase1.main()
    corruption_flow.main()
    output = capsys.readouterr().out
    assert "[phase1] Done: clean_rows=24" in output
    assert "Baseline  Corrupted  Repaired" in output
    assert "[phase1] Skip agent demo: LLM_PROVIDER=mock." in output

from __future__ import annotations

from dataclasses import replace

import pytest

from core.config import normalized_provider, require_llm_credentials
from evaluation import metrics
from retrieval.llm import build_llm

PROVIDER_KEYS = {
    "gemini": "google_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "openrouter": "openrouter_api_key",
    "custom": "custom_llm_base_url",
}


@pytest.mark.parametrize("provider, field", PROVIDER_KEYS.items())
def test_credentials_required(settings, provider, field):
    with pytest.raises(RuntimeError, match="required"):
        require_llm_credentials(replace(settings, llm_provider=provider, **{field: None}))


@pytest.mark.parametrize(
    "provider, field, value, client",
    [
        ("gemini", "google_api_key", "test-key", "ChatGoogleGenerativeAI"),
        ("openai", "openai_api_key", "test-key", "ChatOpenAI"),
        ("Anthorpic", "anthropic_api_key", "test-key", "ChatAnthropic"),
        ("openrouter", "openrouter_api_key", "test-key", "ChatOpenAI"),
        ("custom-llm", "custom_llm_base_url", "http://localhost:9999/v1", "ChatOpenAI"),
        ("ollama", "ollama_base_url", "http://localhost:11434", "ChatOllama"),
        ("mock", "google_api_key", None, "FakeListChatModel"),
    ],
)
def test_build_llm_routes_providers(settings, provider, field, value, client):
    llm = build_llm(replace(settings, llm_provider=provider, model_name="test-model", **{field: value}))
    assert type(llm).__name__ == client


def test_unsupported_provider(settings):
    unsupported = replace(settings, llm_provider="unknown")
    assert normalized_provider(unsupported) == "unknown"
    with pytest.raises(RuntimeError, match="Unsupported LLM_PROVIDER"):
        build_llm(unsupported)


def test_token_f1():
    assert metrics._token_f1("a b c", "a b c") == 1.0
    assert metrics._token_f1("a b", "c d") == 0.0
    assert metrics._token_f1("", "a") == 0.0


def test_judge_retries_on_quota_then_trips_breaker(settings, monkeypatch):
    class QuotaLLM:
        calls = 0

        def with_structured_output(self, schema):
            return self

        def invoke(self, prompt):
            QuotaLLM.calls += 1
            raise RuntimeError("429 RESOURCE_EXHAUSTED ... Please retry in 1.5s.")

    monkeypatch.delenv("JUDGE_MODE", raising=False)
    monkeypatch.setattr(metrics, "_quota_exhausted", False)
    monkeypatch.setattr(metrics, "build_llm", lambda **kwargs: QuotaLLM())
    monkeypatch.setattr(metrics.time, "sleep", lambda seconds: None)

    verdict = metrics._judge_answer(settings, "q", "a b", "a b")
    assert verdict.score == 5 and "RESOURCE_EXHAUSTED" in verdict.reasoning
    assert QuotaLLM.calls == metrics.JUDGE_MAX_ATTEMPTS
    assert metrics._quota_exhausted is True

    metrics._judge_answer(settings, "q", "a b", "c")
    assert QuotaLLM.calls == metrics.JUDGE_MAX_ATTEMPTS  # breaker: khong goi LLM nua


def test_judge_uses_llm_verdict_when_available(settings, monkeypatch):
    class GoodLLM:
        def with_structured_output(self, schema):
            return self

        def invoke(self, prompt):
            return metrics.JudgeVerdict(score=4, correct=True, reasoning="llm")

    monkeypatch.delenv("JUDGE_MODE", raising=False)
    monkeypatch.setattr(metrics, "_quota_exhausted", False)
    monkeypatch.setattr(metrics, "build_llm", lambda **kwargs: GoodLLM())
    assert metrics._judge_answer(settings, "q", "a", "b").reasoning == "llm"


def test_ragas_is_skipped_by_default(settings, monkeypatch):
    monkeypatch.delenv("RUN_RAGAS", raising=False)
    assert "skipped" in metrics._run_ragas(settings, [])

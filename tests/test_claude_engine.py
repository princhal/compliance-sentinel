"""ClaudeEngine with a fake Anthropic client: checks request shape and guards, spends nothing."""

from types import SimpleNamespace

import pytest

from sentinel.config import Settings
from sentinel.llm import (
    AssessedItem,
    Assessment,
    ClaudeEngine,
    EvidenceItem,
    LLMRefusal,
    ObligationDraft,
    ObligationExtraction,
    ObligationView,
)


class FakeMessages:
    def __init__(self, parsed, stop_reason="end_turn"):
        self.parsed, self.stop_reason, self.calls = parsed, stop_reason, []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.parsed, stop_reason=self.stop_reason,
                               stop_details=SimpleNamespace(explanation="declined"),
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                                                     cache_creation_input_tokens=0,
                                                     cache_read_input_tokens=0))


def engine(parsed, stop_reason="end_turn") -> tuple[ClaudeEngine, FakeMessages]:
    eng = ClaudeEngine.__new__(ClaudeEngine)
    eng.settings = Settings(llm_mode="anthropic")
    from sentinel.llm import UsageMeter

    eng.meter, eng.name = UsageMeter(), "anthropic:test"
    msgs = FakeMessages(parsed, stop_reason)
    eng.client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    return eng, msgs


OB = ObligationView("GDPR", "Art. 32(1)", "encryption_at_rest", "high", "Encrypt data.", "q")


def test_request_uses_structured_output_effort_and_fallbacks():
    eng, msgs = engine(ObligationExtraction(obligations=[]))
    eng.extract_obligations("GDPR", "Art. 7(1)", "", "The controller shall be able to demonstrate.")
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is ObligationExtraction
    assert call["output_config"] == {"effort": "medium"}
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert eng.meter.input_tokens == 100 and eng.meter.calls == 1


def test_quotes_not_in_source_are_dropped():
    good = ObligationDraft(actor="controller", action="a", condition="", category="consent",
                           severity="medium", code_checkable=True, summary="s",
                           quote="the controller shall be able to demonstrate")
    bad = good.model_copy(update={"quote": "the controller must encrypt everything"})
    eng, _ = engine(ObligationExtraction(obligations=[good, bad]))
    out = eng.extract_obligations("GDPR", "Art. 7(1)", "",
                                  "Where processing is based on consent, the controller shall be "
                                  "able to demonstrate that the data subject has consented.")
    assert out == [good]


def test_assessments_can_only_cite_supplied_evidence():
    items = [AssessedItem(evidence_id="E1", status="violation", severity="high", confidence=0.9,
                          reasoning="r"),
             AssessedItem(evidence_id="E99", status="violation", severity="high", confidence=0.9,
                          reasoning="invented")]
    eng, _ = engine(Assessment(items=items))
    ev = [EvidenceItem("E1", "a.py", 1, 1, "x", "ENC001")]
    assert [i.evidence_id for i in eng.assess(OB, ev)] == ["E1"]


def test_refusal_raises():
    eng, _ = engine(None, stop_reason="refusal")
    with pytest.raises(LLMRefusal):
        eng.plan_checks(OB)

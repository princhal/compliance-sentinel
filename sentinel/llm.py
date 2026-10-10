"""LLM engines for the four model-driven steps: extract, plan, assess and verify.

ClaudeEngine calls Claude with structured outputs. HeuristicEngine needs no network and applies
transparent rules, so the full pipeline runs in tests, CI and demos without an API key.

Both engines may only point at evidence the pipeline supplied (by evidence ID). A model can never
invent a file or line number: locations always come from real files.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, Field

from sentinel.config import Settings, get_settings
from sentinel.taxonomy import CATEGORIES, CategoryName, Severity, signal_matches

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# --- Structured output schemas -----------------------------------------------------------------


class ObligationDraft(BaseModel):
    actor: str = Field(description="Who must act, e.g. 'controller', 'business', 'covered entity'.")
    action: str = Field(description="What they must do, in plain words.")
    condition: str = Field(description="When it applies. Empty string if always.")
    category: CategoryName
    severity: Severity
    code_checkable: bool = Field(description="True if source code can show compliance or not.")
    summary: str = Field(description="One sentence an engineer can act on.")
    quote: str = Field(description="The exact sentence from the text that creates the duty.")


class ObligationExtraction(BaseModel):
    obligations: list[ObligationDraft]


class CheckPlan(BaseModel):
    search_queries: list[str] = Field(description="Two to five code search queries.")
    what_to_look_for: str


class AssessedItem(BaseModel):
    evidence_id: str = Field(description="ID of one supplied evidence item, e.g. 'E3'.")
    status: Literal["violation", "compliant", "needs_review"]
    severity: Severity
    confidence: float = Field(description="0 to 1.")
    reasoning: str = Field(description="Two or three sentences tying the code to the obligation.")


class Assessment(BaseModel):
    items: list[AssessedItem]


class Verification(BaseModel):
    confirmed: bool
    confidence: float = Field(description="0 to 1.")
    reason: str


# --- Inputs passed to the engines -----------------------------------------------------------


@dataclass
class EvidenceItem:
    id: str
    path: str
    start_line: int
    end_line: int
    snippet: str
    source: str  # static rule ID, or "search"
    message: str = ""
    rule_confidence: float = 0.0


@dataclass
class ObligationView:
    regulation: str
    section_ref: str
    category: str
    severity: str
    summary: str
    quote: str


# --- Usage metering --------------------------------------------------------------------------


@dataclass
class UsageMeter:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, usage: object) -> None:
        with self._lock:
            self.calls += 1
            for attr in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                self.input_tokens += int(getattr(usage, attr, 0) or 0)
            self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

    def cost(self, settings: Settings) -> float:
        return round(self.input_tokens / 1e6 * settings.price_input_per_mtok
                     + self.output_tokens / 1e6 * settings.price_output_per_mtok, 4)


class LLMRefusal(RuntimeError):
    pass


class Engine(Protocol):
    name: str
    meter: UsageMeter

    def extract_obligations(self, regulation: str, section_ref: str, heading: str,
                            text: str) -> list[ObligationDraft]: ...
    def plan_checks(self, ob: ObligationView) -> CheckPlan: ...
    def assess(self, ob: ObligationView, evidence: list[EvidenceItem]) -> list[AssessedItem]: ...
    def verify(self, ob: ObligationView, item: AssessedItem, ev: EvidenceItem,
               file_excerpt: str) -> Verification: ...


# --- Claude ----------------------------------------------------------------------------------

EXTRACT_SYSTEM = """You turn regulatory text into obligations a software team can check.
Return one obligation per distinct duty. Choose the single best category for each one.
Mark code_checkable true only when source code or configuration could show whether the duty is met.
The quote must be copied exactly from the text. If the text creates no duty, return an empty list.
Categories: """ + ", ".join(f"{c.name} ({c.label})" for c in CATEGORIES.values())

PLAN_SYSTEM = """You plan how to find code that matters for one legal obligation.
Write short code search queries using identifiers and API names a developer would actually use."""

ASSESS_SYSTEM = """You are a privacy compliance auditor reviewing code evidence for one obligation.
Judge each evidence item separately and refer to it only by its ID.
violation: the code clearly fails the obligation.
needs_review: it might fail, but the evidence is not conclusive.
compliant: the code meets the obligation or is unrelated to it.
Do not assume facts that are not in the evidence. Calibrate confidence honestly."""

VERIFY_SYSTEM = """You are a skeptical second reviewer. Another auditor flagged this code as a
violation. Confirm only if the code shown really fails the obligation. Look for mitigations in the
surrounding lines, such as hashing, encryption, redaction, consent checks or auth decorators."""


class ClaudeEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = anthropic.Anthropic(max_retries=4)
        self.meter = UsageMeter()
        self.name = f"anthropic:{self.settings.anthropic_model}"

    def _parse(self, system: str, user: str, schema: type[T], effort: str) -> T:
        response = self.client.beta.messages.parse(
            model=self.settings.anthropic_model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": effort},
            cache_control={"type": "ephemeral"},
            # Re-runs a safety-declined request on Anthropic's recommended fallback model.
            fallbacks="default",
            betas=["server-side-fallback-2026-07-01"],
        )
        self.meter.add(response.usage)
        if response.stop_reason == "refusal":
            raise LLMRefusal(getattr(response.stop_details, "explanation", None) or "refused")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise RuntimeError(f"Claude returned no parsable output (stop={response.stop_reason})")
        return response.parsed_output

    def extract_obligations(self, regulation: str, section_ref: str, heading: str,
                            text: str) -> list[ObligationDraft]:
        user = f"Regulation: {regulation}\nSection: {section_ref} {heading}\n\n<text>\n{text}\n</text>"
        out = self._parse(EXTRACT_SYSTEM, user, ObligationExtraction,
                          self.settings.anthropic_effort_extract)
        # Keep only quotes that really appear in the source text.
        norm = _norm(text)
        return [o for o in out.obligations if _norm(o.quote)[:80] in norm]

    def plan_checks(self, ob: ObligationView) -> CheckPlan:
        user = (f"{ob.regulation} {ob.section_ref} ({ob.category})\n{ob.summary}\n"
                f"Quote: {ob.quote}")
        return self._parse(PLAN_SYSTEM, user, CheckPlan, "low")

    def assess(self, ob: ObligationView, evidence: list[EvidenceItem]) -> list[AssessedItem]:
        if not evidence:
            return []
        blocks = "\n\n".join(
            f'<evidence id="{e.id}" path="{e.path}" lines="{e.start_line}-{e.end_line}" '
            f'source="{e.source}">\n{e.message}\n{e.snippet}\n</evidence>' for e in evidence
        )
        user = (f"Obligation: {ob.regulation} {ob.section_ref} [{ob.category}]\n{ob.summary}\n"
                f'Quote: "{ob.quote}"\n\n{blocks}')
        out = self._parse(ASSESS_SYSTEM, user, Assessment, self.settings.anthropic_effort_assess)
        valid = {e.id for e in evidence}
        return [i for i in out.items if i.evidence_id in valid]

    def verify(self, ob: ObligationView, item: AssessedItem, ev: EvidenceItem,
               file_excerpt: str) -> Verification:
        user = (f"Obligation: {ob.regulation} {ob.section_ref}\n{ob.summary}\n\n"
                f"Flagged: {ev.path} lines {ev.start_line}-{ev.end_line}\n"
                f"First reviewer said: {item.reasoning}\n\n<file_excerpt>\n{file_excerpt}\n"
                "</file_excerpt>")
        return self._parse(VERIFY_SYSTEM, user, Verification, self.settings.anthropic_effort_assess)


# --- Offline heuristic engine ------------------------------------------------------------------

_DUTY = re.compile(r"\b(shall|must|is required to|are required to|has the right|have the right)\b",
                   re.I)
_MITIGATIONS = {
    "pii_logging": re.compile(r"redact|mask|hash|scrub", re.I),
    "password_storage": re.compile(r"bcrypt|argon2|scrypt|pbkdf2|check_password_hash|passlib", re.I),
    "encryption_in_transit": re.compile(r"localhost|127\.0\.0\.1|https://", re.I),
    "encryption_at_rest": re.compile(r"encrypt|EncryptedType|ServerSideEncryption|kms", re.I),
    "secrets_management": re.compile(r"os\.environ|getenv|settings\.|secrets\.", re.I),
    "consent": re.compile(r"consent", re.I),
    "access_control": re.compile(r"Depends\(.*(user|auth)|login_required|require_", re.I),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.;:])\s+(?=[(A-Z])", flat) if s.strip()]


class HeuristicEngine:
    """Rule-based stand-in for Claude. Transparent and deterministic, not smart."""

    name = "offline-heuristic"

    def __init__(self) -> None:
        self.meter = UsageMeter()

    def extract_obligations(self, regulation: str, section_ref: str, heading: str,
                            text: str) -> list[ObligationDraft]:
        drafts: list[ObligationDraft] = []
        seen: set[str] = set()
        low = _norm(heading + " " + text)
        duty_sentences = [s for s in _sentences(text) if _DUTY.search(s)] or _sentences(text)[:1]
        for cat in CATEGORIES.values():
            if not cat.legal_signals or not any(signal_matches(sig, low) for sig in cat.legal_signals):
                continue
            if cat.name in seen:
                continue
            seen.add(cat.name)
            quote = next((s for s in duty_sentences
                          if any(signal_matches(sig, s.lower()) for sig in cat.legal_signals)),
                         duty_sentences[0] if duty_sentences else text[:300])
            actor = _guess_actor(quote)
            drafts.append(ObligationDraft(
                actor=actor, action=cat.label, condition="", category=cat.name,  # type: ignore[arg-type]
                severity=cat.severity, code_checkable=cat.code_checkable,
                summary=f"{regulation} {section_ref}: {actor} must prevent: {cat.label.lower()}.",
                quote=quote[:600],
            ))
        return drafts

    def plan_checks(self, ob: ObligationView) -> CheckPlan:
        terms = CATEGORIES.get(ob.category, CATEGORIES["other"]).code_terms
        queries = [" ".join(terms[i : i + 3]) for i in range(0, len(terms), 3)] or [ob.summary]
        return CheckPlan(search_queries=queries[:5],
                         what_to_look_for=CATEGORIES[ob.category].label)

    def assess(self, ob: ObligationView, evidence: list[EvidenceItem]) -> list[AssessedItem]:
        items = []
        for e in evidence:
            if e.source == "search":
                continue  # Without a model, only static rule hits count as evidence.
            mitigated = _MITIGATIONS.get(ob.category)
            if mitigated and mitigated.search(e.snippet) and e.rule_confidence < 0.9:
                status, conf = "compliant", 0.5
            elif e.rule_confidence >= 0.75:
                status, conf = "violation", e.rule_confidence
            else:
                status, conf = "needs_review", e.rule_confidence
            items.append(AssessedItem(
                evidence_id=e.id, status=status, severity=ob.severity, confidence=conf,  # type: ignore[arg-type]
                reasoning=f"Static check {e.source}: {e.message} This relates to {ob.section_ref}, "
                          f"which requires the {ob.category.replace('_', ' ')} duty to be met.",
            ))
        return items

    def verify(self, ob: ObligationView, item: AssessedItem, ev: EvidenceItem,
               file_excerpt: str) -> Verification:
        # The deterministic check: the flagged lines must still contain the matched code.
        present = _norm(ev.snippet.splitlines()[0] if ev.snippet else "") in _norm(file_excerpt)
        return Verification(confirmed=present, confidence=item.confidence if present else 0.2,
                            reason="Flagged code is present in the file." if present
                            else "Flagged code was not found at the cited lines.")


def _guess_actor(sentence: str) -> str:
    for actor in ("controller and the processor", "controller", "processor", "business",
                  "covered entity", "service provider"):
        if actor in sentence.lower():
            return actor
    return "the organisation"


def get_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    if settings.use_anthropic:
        return ClaudeEngine(settings)
    log.info("No Anthropic credentials found: using the offline heuristic engine")
    return HeuristicEngine()

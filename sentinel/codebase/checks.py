"""Static privacy checks. Each rule targets one taxonomy category and yields evidence for the agent.

Three kinds of rule:
  line rules     match one line, with an optional "unless" pattern for mitigations
  span rules     look at a whole function (e.g. a delete handler that only soft-deletes)
  repo rules     look for something missing across the whole repo (e.g. no breach process)

Semgrep runs too when it is installed, using sentinel/codebase/semgrep/privacy.yml.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess  # noqa: S404
from dataclasses import asdict, dataclass
from pathlib import Path

from sentinel.codebase.chunker import chunk_code
from sentinel.codebase.repo import iter_source_files

log = logging.getLogger(__name__)
SEMGREP_RULES = Path(__file__).parent / "semgrep" / "privacy.yml"

PII = (r"\w*(email|ssn|social_security|phone|date_of_birth|\bdob\b|passport|credit_card|"
       r"card_number|iban|home_address|street_address|password|diagnosis)\w*")


@dataclass
class StaticHit:
    rule_id: str
    category: str
    path: str
    start_line: int
    end_line: int
    snippet: str
    message: str
    confidence: float

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.category}|{self.path}|{self.start_line}".encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LineRule:
    id: str
    category: str
    pattern: re.Pattern[str]
    message: str
    confidence: float
    unless: re.Pattern[str] | None = None
    languages: frozenset[str] | None = None


def _r(p: str) -> re.Pattern[str]:
    return re.compile(p, re.I)


CODE = frozenset({"python", "javascript", "typescript", "tsx", "go", "java", "ruby"})

LINE_RULES: list[LineRule] = [
    LineRule("PII001", "pii_logging",
             _r(r"\b(log|logger|logging|console|LOG)\.(debug|info|warn|warning|error|exception|"
                r"critical|log)\s*\(.*" + PII + r"|\bprint\s*\(.*" + PII),
             "Personal data is written to application logs.", 0.85,
             unless=_r(r"redact|mask|scrub|\bhash"), languages=CODE),
    LineRule("PWD001", "password_storage",
             _r(r"hashlib\.(md5|sha1)\s*\(.*pass|md5\(.*pass|sha1\(.*pass|createHash\(['\"](md5|sha1)"),
             "Passwords are hashed with a fast, broken algorithm (MD5/SHA-1).", 0.9,
             languages=CODE),
    LineRule("PWD002", "password_storage",
             _r(r"\b(password|passwd)\s*=\s*(request|data|payload|body|form|user_in|params|"
                r"signup|req)\b[\w.\[\]'\"]*\s*(,|\)|$)"),
             "A password from user input is stored without hashing.", 0.8,
             unless=_r(r"hash|bcrypt|argon|scrypt|pbkdf|verify|check_password|compare"),
             languages=CODE),
    LineRule("TLS001", "encryption_in_transit",
             _r(r"[\"']http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|example\.)[^\"'\s]+[\"']"),
             "Data is sent over plain HTTP instead of HTTPS.", 0.8,
             unless=_r(r"xmlns|schema|w3\.org|#\s*noqa"), languages=CODE | {"yaml", "toml", "dotenv"}),
    LineRule("TLS002", "encryption_in_transit",
             _r(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|InsecureSkipVerify:\s*true|"
                r"sslmode=disable|ssl\s*=\s*False|CERT_NONE"),
             "TLS certificate checks or encryption are turned off.", 0.9),
    LineRule("ENC001", "encryption_at_rest",
             _r(r"\b(ssn|social_security\w*|card_number|credit_card\w*|iban|passport\w*|"
                r"diagnosis|medical_\w+|health_\w+)\b\s*(:\s*Mapped\[[^\]]*\]\s*)?[:=]\s*"
                r"(Column|mapped_column|models\.\w*Field|db\.Column|Mapped)"),
             "A sensitive personal data field is stored as plain text.", 0.8,
             unless=_r(r"encrypt|EncryptedType|Fernet|kms"), languages=CODE),
    LineRule("ENC002", "encryption_at_rest",
             _r(r"\.put_object\s*\((?!.*ServerSideEncryption)"),
             "Object written to storage without server-side encryption.", 0.7,
             unless=_r(r"ServerSideEncryption|SSEKMS"), languages=CODE),
    LineRule("SEC001", "secrets_management",
             _r(r"\b\w*(api[_-]?key|secret[_-]?key|client[_-]?secret|auth[_-]?token|access[_-]?token|"
                r"aws_secret_access_key|private[_-]?key|db_password|password)\w*[\"']?\s*[:=]\s*"
                r"[\"'][A-Za-z0-9_\-/+=.]{12,}[\"']"),
             "A credential is hardcoded in source code.", 0.9,
             unless=_r(r"environ|getenv|example|changeme|placeholder|your[_-]|xxx|dummy|test_"),
             languages=CODE | {"yaml", "toml"}),
    LineRule("SEC002", "secrets_management",
             _r(r"^\s*[A-Z0-9_]*(KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*\s*=\s*[^\s#]{8,}"),
             "A secret value is committed in an environment file.", 0.75,
             unless=_r(r"changeme|example|placeholder|your[_-]"), languages=frozenset({"dotenv"})),
    LineRule("RET001", "data_retention",
             _r(r"\b\w*(retention|retain|keep)\w*\s*[:=]\s*(None|null|-1|0\b|float\([\"']inf|"
                r"math\.inf|Infinity)|keep\s+forever|never\s+(delete|purge|expire)"),
             "Personal data is configured to be kept indefinitely.", 0.8),
    LineRule("MIN001", "data_minimization",
             _r(r"SELECT\s+\*\s+FROM\s+\w*(user|customer|patient|account|member)"),
             "Every column of a personal data table is selected, not just the needed ones.", 0.7),
    LineRule("MIN002", "data_minimization",
             _r(r"return\s+.*\b(user|customer|patient|member|account)\w*\.(__dict__|to_dict\(\)|"
                r"dict\(\)|model_dump\(\))"),
             "A full personal data record is returned, including fields the caller does not need.",
             0.75, languages=CODE),
    LineRule("XFR001", "cross_border_transfer",
             _r(r"[\"'](us|ap|sa|ca|me|af)-(east|west|south|north|central|northeast|southeast)-\d[\"']"),
             "Personal data may be stored in a region outside the EU.", 0.6),
]

ROUTE = _r(r"@(app|router|api|bp|blueprint)\.(get|post|put|delete|patch|route)\s*\(")
AUTH = _r(r"Depends\([^)]*(user|auth|token|principal)|login_required|require_|Security\(|"
          r"@auth|permission_classes|IsAuthenticated|jwt_required")
PERSONAL = _r(r"user|customer|patient|member|email|profile")
TRACKING = _r(r"\b(analytics|segment|mixpanel|amplitude|posthog|gtag|track_event|"
              r"send_marketing\w*|marketing_\w+)\s*[.(]")


def _span_rules(rel: str, span_text: str, symbol: str, start: int, end: int) -> list[StaticHit]:
    hits: list[StaticHit] = []
    lines = span_text.splitlines()

    def hit(rule_id, category, offset, msg, conf):
        line_no = start + offset
        hits.append(StaticHit(rule_id, category, rel, line_no, line_no,
                              lines[offset].strip()[:300], msg, conf))

    route_idx = next((i for i, ln in enumerate(lines) if ROUTE.search(ln)), None)
    if route_idx is not None and not AUTH.search(span_text) and PERSONAL.search(span_text):
        hit("ACC001", "access_control", route_idx,
            "An endpoint that handles personal data has no authentication check.", 0.75)
    if re.search(r"delete|erase|remove|forget", symbol, re.I):
        soft = next((i for i, ln in enumerate(lines)
                     if re.search(r"is_deleted\s*=\s*True|deleted_at\s*=|active\s*=\s*False", ln)),
                    None)
        hard = re.search(r"session\.delete|\.delete\(\)|DELETE\s+FROM|\.destroy\(|anonymi[sz]e",
                         span_text, re.I)
        if soft is not None and not hard:
            hit("DEL001", "data_deletion", soft,
                "Delete requests only flag the record; personal data is never erased.", 0.8)
    track = next((i for i, ln in enumerate(lines) if TRACKING.search(ln)), None)
    if track is not None and not re.search(r"consent", span_text, re.I):
        hit("CON001", "consent", track,
            "Data is sent for tracking or marketing without checking the user's consent.", 0.75)
    return hits


def _repo_rules(root: Path, texts: dict[str, str]) -> list[StaticHit]:
    hits: list[StaticHit] = []
    corpus = "\n".join(texts.values())
    stores_pii = re.search(PII, corpus, re.I) is not None
    if not stores_pii:
        return hits
    anchor = next((p for p in texts if re.search(r"model|schema|db", p, re.I)), next(iter(texts)))

    def repo_hit(rule_id, category, msg, conf):
        hits.append(StaticHit(rule_id, category, anchor, 1, 1,
                              f"(whole repository) {msg}", msg, conf))

    if not re.search(r"incident|breach|security\.txt|vulnerability disclosure", corpus, re.I) and \
            not (root / "SECURITY.md").exists():
        repo_hit("BRN001", "breach_notification",
                 "No incident or breach notification process was found in the repository.", 0.55)
    if not re.search(r"purge|retention_days|ttl|expire_after|cleanup_old|delete_expired", corpus,
                     re.I):
        repo_hit("RET002", "data_retention",
                 "No job or setting removes personal data after a retention period.", 0.55)
    if not re.search(r"def\s+(delete|erase|forget)_?\w*(user|account|customer|me)|"
                     r"right.to.(erasure|be.forgotten|delete)", corpus, re.I):
        repo_hit("DEL002", "data_deletion",
                 "No way for a person to have their data deleted was found.", 0.6)
    return hits


def run_semgrep(root: Path) -> list[StaticHit]:
    exe = shutil.which("semgrep")
    if not exe or not SEMGREP_RULES.exists():
        return []
    try:
        proc = subprocess.run(  # noqa: S603
            [exe, "--config", str(SEMGREP_RULES), "--json", "--quiet", "--metrics=off", str(root)],
            capture_output=True, text=True, timeout=600, check=False)
        data = json.loads(proc.stdout or "{}")
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        log.warning("Semgrep failed: %s", exc)
        return []
    hits = []
    for r in data.get("results", []):
        meta = r.get("extra", {}).get("metadata", {})
        hits.append(StaticHit(
            rule_id=f"semgrep:{r['check_id'].split('.')[-1]}", category=meta.get("category", "other"),
            path=str(Path(r["path"]).resolve().relative_to(root.resolve())),
            start_line=r["start"]["line"], end_line=r["end"]["line"],
            snippet=r.get("extra", {}).get("lines", "").strip()[:300],
            message=r.get("extra", {}).get("message", ""),
            confidence=float(meta.get("confidence_score", 0.8))))
    return hits


def run_checks(root: Path) -> list[StaticHit]:
    hits: list[StaticHit] = []
    texts: dict[str, str] = {}
    for path, lang in iter_source_files(root):
        rel = str(path.relative_to(root))
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        texts[rel] = text
        for i, line in enumerate(text.splitlines(), start=1):
            for rule in LINE_RULES:
                if rule.languages and lang not in rule.languages:
                    continue
                if rule.pattern.search(line) and not (rule.unless and rule.unless.search(line)):
                    hits.append(StaticHit(rule.id, rule.category, rel, i, i, line.strip()[:300],
                                          rule.message, rule.confidence))
        if lang in CODE:
            for span in chunk_code(text, lang):
                # Span rules need real function boundaries, not fallback line windows.
                if span.symbol and span.symbol != "<module>":
                    hits.extend(_span_rules(rel, span.text, span.symbol, span.start_line,
                                            span.end_line))
    if texts:
        hits.extend(_repo_rules(root, texts))
    hits.extend(run_semgrep(root))
    unique: dict[str, StaticHit] = {}
    for h in hits:
        if h.key not in unique or unique[h.key].confidence < h.confidence:
            unique[h.key] = h
    return sorted(unique.values(), key=lambda h: (h.path, h.start_line, h.rule_id))

"""The compliance categories that connect legal obligations to code checks.

Every obligation gets one category. Every static check targets one category. The agent only compares
an obligation with evidence from checks in the same category, which keeps the audit focused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["critical", "high", "medium", "low"]
SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}

CategoryName = Literal[
    "pii_logging",
    "password_storage",
    "encryption_in_transit",
    "encryption_at_rest",
    "secrets_management",
    "data_retention",
    "data_deletion",
    "consent",
    "access_control",
    "data_minimization",
    "cross_border_transfer",
    "breach_notification",
    "other",
]


@dataclass(frozen=True)
class Category:
    name: str
    label: str
    severity: Severity
    code_checkable: bool
    # Phrases in legal text that signal this category, used by the offline extractor.
    # "a+b" means both words must appear.
    legal_signals: tuple[str, ...]
    # Words that help hybrid code search find relevant functions.
    code_terms: tuple[str, ...]


CATEGORIES: dict[str, Category] = {
    c.name: c
    for c in [
        Category("pii_logging", "Personal data written to logs", "high", True,
                 ("confidentiality", "limited to what is necessary"),
                 ("log", "logger", "print", "email", "ssn", "phone", "address")),
        Category("password_storage", "Weak or plaintext password storage", "critical", True,
                 ("security of processing", "appropriate security", "reasonable security",
                  "confidentiality"),
                 ("password", "hash", "md5", "sha1", "bcrypt", "argon2")),
        Category("encryption_in_transit", "Unencrypted data in transit", "high", True,
                 ("encryption", "transmission security", "transmitted", "electronic communications"),
                 ("http://", "verify", "ssl", "tls", "requests", "httpx")),
        Category("encryption_at_rest", "Unencrypted personal data at rest", "high", True,
                 ("encryption", "pseudonymisation", "pseudonymization", "encrypt"),
                 ("encrypt", "column", "ssn", "card", "put_object", "ServerSideEncryption")),
        Category("secrets_management", "Hardcoded credentials", "high", True,
                 ("security of processing", "reasonable security", "appropriate security",
                  "credentials+stored"),
                 ("api_key", "secret", "token", "password", "credential")),
        Category("data_retention", "Personal data kept longer than necessary", "medium", True,
                 ("no longer than is necessary", "storage limitation", "retain",
                  "longer than is reasonably necessary"),
                 ("retention", "ttl", "expire", "purge", "cleanup", "keep")),
        Category("data_deletion", "Right to erasure not supported", "high", True,
                 ("erasure", "right to delete", "request that a business delete", "delete"),
                 ("delete", "erase", "soft_delete", "is_deleted", "purge")),
        Category("consent", "Processing without recorded consent", "medium", True,
                 ("based on consent", "has consented", "consent+demonstrate"),
                 ("consent", "track", "analytics", "marketing", "opt_in")),
        Category("access_control", "Personal data exposed without access control", "high", True,
                 ("unauthorised or unlawful processing", "unauthorized or illegal access",
                  "access control", "unauthorised access"),
                 ("route", "auth", "login_required", "Depends", "admin", "permission")),
        Category("data_minimization", "More personal data processed than needed", "medium", True,
                 ("limited to what is necessary", "data minimisation", "data minimization",
                  "only personal data which are necessary"),
                 ("select *", "serialize", "to_dict", "fields", "export")),
        Category("cross_border_transfer", "Transfer of personal data outside the EU", "medium", True,
                 ("third country", "international organisation", "transfer of personal data"),
                 ("region", "us-east", "us-west", "bucket", "endpoint")),
        Category("breach_notification", "No breach notification process", "high", True,
                 ("personal data breach", "breach of security", "breach+notif"),
                 ("incident", "breach", "notify", "alert", "security_contact")),
        Category("other", "Other obligation", "low", False, (), ()),
    ]
}


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, 9)


def signal_matches(signal: str, text_lower: str) -> bool:
    return all(part in text_lower for part in signal.split("+"))

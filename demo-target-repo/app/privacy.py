import hashlib


def redact(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]

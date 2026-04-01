"""Short-code generation: random base62, collision handled by unique-index retry.

62^7 ~= 3.5e12 -> collision probability is negligible at portfolio scale;
the retry loop in the create flow is correctness, not hope.
"""
import re
import secrets

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CODE_LENGTH = 7

# Words that must never be usable as a short code (route collisions / confusion).
RESERVED = frozenset(
    {"api", "healthz", "readyz", "metrics", "docs", "redoc", "openapi.json", "admin", "static"}
)

ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{4,12}$")


def generate_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(BASE62) for _ in range(length))


def is_valid_alias(alias: str) -> bool:
    return bool(ALIAS_RE.match(alias)) and alias.lower() not in RESERVED

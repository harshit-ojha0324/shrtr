"""Short-code generation: random codes, collision handled by unique-index retry.

8 characters from a 56-symbol alphabet with no look-alikes (0/O/o, 1/l/I), so a
code read off a slide or a printed QR label can be typed back. 56^8 ~= 9.7e13;
the retry loop in the create flow is correctness, not hope.
"""
import re
import secrets

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz"
CODE_LENGTH = 8

# Words that must never be usable as a short code (route collisions / confusion).
RESERVED = frozenset(
    {"api", "healthz", "readyz", "metrics", "docs", "redoc", "openapi.json", "admin", "static"}
)

# 32 must match links.short_code (migration 0002)
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


def generate_code(length: int = CODE_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def is_valid_alias(alias: str) -> bool:
    # fullmatch, not match: with match, '$' also matches before a trailing newline
    return bool(ALIAS_RE.fullmatch(alias)) and alias.lower() not in RESERVED

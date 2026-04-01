"""Submitted-URL validation.

Allow only http/https; block obvious SSRF/abuse targets (localhost, private/link-local
IP literals, credentials in URL, javascript:/data: smuggling). Known limitation
(documented in README): we do not resolve DNS, so a hostname pointing at a private IP
is not caught (DNS rebinding). We never fetch target URLs server-side, which is the
real mitigation here.
"""
import ipaddress
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048

_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "0.0.0.0", "[::1]", "::1"}


class InvalidURLError(ValueError):
    pass


def validate_url(raw: str) -> str:
    url = raw.strip()
    if len(url) > MAX_URL_LENGTH:
        raise InvalidURLError(f"URL longer than {MAX_URL_LENGTH} characters")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise InvalidURLError("only http:// and https:// URLs are allowed")
    if not parts.hostname:
        raise InvalidURLError("URL has no host")
    if parts.username or parts.password:
        raise InvalidURLError("credentials in URL are not allowed")
    host = parts.hostname.lower()
    if host in _BLOCKED_HOSTS:
        raise InvalidURLError("host is not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    ):
        raise InvalidURLError("IP-literal hosts in private/reserved ranges are not allowed")
    return url

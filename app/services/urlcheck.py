"""Submitted-URL validation.

Allow only http/https; block obvious SSRF/abuse targets (localhost, private/link-local
IP literals, credentials in URL, javascript:/data: smuggling). Known limitation
(documented in README): we do not resolve DNS, so a hostname pointing at a private IP
is not caught (DNS rebinding). We never fetch target URLs server-side, which is the
real mitigation here.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048

_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "0.0.0.0", "[::1]", "::1"}


class InvalidURLError(ValueError):
    pass


def _host_as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a host that is an IP literal, including the alternate IPv4 spellings
    browsers accept but ipaddress.ip_address rejects: decimal (2130706433),
    octal (0177.0.0.1), hex (0x7f000001), and short forms (127.1)."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


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
    ip = _host_as_ip(host)
    if ip is not None and (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise InvalidURLError("IP-literal hosts in private/reserved ranges are not allowed")
    return url

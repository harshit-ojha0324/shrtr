import pytest

from app.services.urlcheck import InvalidURLError, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/path?q=1",
        "http://sub.domain.co.uk",
        "https://example.com:8443/x",
    ],
)
def test_valid_urls(url):
    assert validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "javascript:alert(1)",
        "data:text/html,hello",
        "https://localhost/x",
        "http://127.0.0.1/x",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/admin",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "https://user:pass@example.com",
        "not-a-url",
        "https://",
    ],
)
def test_invalid_urls(url):
    with pytest.raises((InvalidURLError, ValueError)):
        validate_url(url)


def test_overlong_url_rejected():
    with pytest.raises(InvalidURLError):
        validate_url("https://example.com/" + "a" * 3000)

from types import SimpleNamespace

import pytest

from src.core.openai import oauth


def test_post_form_wraps_curl_cffi_network_errors(monkeypatch):
    class FakeRequestsError(Exception):
        pass

    def fake_post(*args, **kwargs):
        raise FakeRequestsError("boom")

    monkeypatch.setattr(oauth, "fingerprinted_post", fake_post)
    monkeypatch.setattr(
        oauth,
        "cffi_requests",
        SimpleNamespace(RequestsError=FakeRequestsError),
    )

    with pytest.raises(RuntimeError, match="token exchange failed: network error: boom"):
        oauth._post_form("https://example.com/token", {"code": "abc"})

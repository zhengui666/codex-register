from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core import dynamic_proxy
from src.core.dynamic_proxy_types import DynamicProxyFetchResult
from src.core.zdaye_proxy import fetch_zdaye_proxy
from src.web.routes.settings import router as settings_router


def test_fetch_dynamic_proxy_generic_result_field(monkeypatch):
    response = SimpleNamespace(status_code=200, text='{"data":{"proxy":"10.0.0.1:8080"}}')

    monkeypatch.setattr(
        "src.core.fingerprint.fingerprinted_get",
        lambda *args, **kwargs: response,
    )

    result = dynamic_proxy.fetch_dynamic_proxy_result(
        api_url="https://example.com/get_proxy",
        result_field="data.proxy",
    )

    assert result.proxy_url == "http://10.0.0.1:8080"
    assert result.provider == "generic"
    assert result.error is None


def test_fetch_zdaye_proxy_returns_first_verified_candidate(monkeypatch):
    response = SimpleNamespace(
        status_code=200,
        text="""
        {
          "code": "10001",
          "msg": "获取成功",
          "data": {
            "count": 2,
            "proxy_list": [
              {"ip": "1.1.1.1", "port": 8001, "protocol": "http", "adr": "美国", "level": "高匿"},
              {"ip": "2.2.2.2", "port": 8002, "protocol": "http", "adr": "美国", "level": "高匿"}
            ]
          }
        }
        """.strip(),
    )

    monkeypatch.setattr("src.core.zdaye_proxy.fingerprinted_get", lambda *args, **kwargs: response)
    monkeypatch.setattr("src.core.zdaye_proxy.random.shuffle", lambda items: items.reverse())

    calls = []

    def fake_probe(proxy_url, timeout=8):
        calls.append(proxy_url)
        if proxy_url == "http://2.2.2.2:8002":
            return DynamicProxyFetchResult(
                proxy_url=proxy_url,
                provider="zdaye_free_proxy",
                verified=True,
                probe_ip="2.2.2.2",
                probe_response_time=123,
            )
        return DynamicProxyFetchResult(
            proxy_url=proxy_url,
            provider="zdaye_free_proxy",
            error="probe_failed",
            message="boom",
        )

    monkeypatch.setattr("src.core.zdaye_proxy.probe_proxy_connectivity", fake_probe)

    result = fetch_zdaye_proxy("https://open.zdaye.com/FreeProxy/Get/?api=demo", api_key="secret")

    assert calls == ["http://2.2.2.2:8002"]
    assert result.proxy_url == "http://2.2.2.2:8002"
    assert result.verified is True
    assert result.checked_candidates == 1
    assert result.total_candidates == 2


def test_fetch_zdaye_proxy_returns_error_when_all_candidates_fail(monkeypatch):
    response = SimpleNamespace(
        status_code=200,
        text="""
        {
          "code": "10001",
          "msg": "获取成功",
          "data": {
            "count": 2,
            "proxy_list": [
              {"ip": "1.1.1.1", "port": 8001, "protocol": "http"},
              {"ip": "2.2.2.2", "port": 8002, "protocol": "http"}
            ]
          }
        }
        """.strip(),
    )

    monkeypatch.setattr("src.core.zdaye_proxy.fingerprinted_get", lambda *args, **kwargs: response)
    monkeypatch.setattr(
        "src.core.zdaye_proxy.probe_proxy_connectivity",
        lambda *args, **kwargs: DynamicProxyFetchResult(error="probe_failed", message="down"),
    )

    result = fetch_zdaye_proxy("https://open.zdaye.com/FreeProxy/Get/?api=demo")

    assert result.proxy_url is None
    assert result.error == "no_available_proxy"
    assert result.checked_candidates == 2
    assert result.total_candidates == 2


def test_fetch_zdaye_proxy_handles_invalid_payload(monkeypatch):
    response = SimpleNamespace(status_code=200, text='{"code":"10001","msg":"获取成功","data":[]}')
    monkeypatch.setattr("src.core.zdaye_proxy.fingerprinted_get", lambda *args, **kwargs: response)

    result = fetch_zdaye_proxy("https://open.zdaye.com/FreeProxy/Get/?api=demo")

    assert result.proxy_url is None
    assert result.error == "invalid_structure"


def test_settings_dynamic_proxy_test_uses_verified_provider_result(monkeypatch):
    app = FastAPI()
    app.include_router(settings_router, prefix="/api/settings")
    client = TestClient(app)

    monkeypatch.setattr(
        "src.core.dynamic_proxy.fetch_dynamic_proxy_result",
        lambda *args, **kwargs: DynamicProxyFetchResult(
            proxy_url="http://user:pass@1.2.3.4:8080",
            provider="zdaye_free_proxy",
            message="站大爷代理可用",
            verified=True,
            probe_ip="8.8.8.8",
            probe_response_time=88,
            checked_candidates=2,
            total_candidates=5,
        ),
    )

    response = client.post(
        "/api/settings/proxy/dynamic/test",
        json={
            "enabled": True,
            "api_url": "https://open.zdaye.com/FreeProxy/Get/?api=demo",
            "api_key": "secret",
            "api_key_header": "X-API-Key",
            "result_field": "",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["provider"] == "zdaye_free_proxy"
    assert payload["proxy_url"] == "http://***:***@1.2.3.*:8080"
    assert payload["checked_candidates"] == 2
    assert payload["total_candidates"] == 5


def test_settings_dynamic_proxy_test_returns_structured_failure(monkeypatch):
    app = FastAPI()
    app.include_router(settings_router, prefix="/api/settings")
    client = TestClient(app)

    monkeypatch.setattr(
        "src.core.dynamic_proxy.fetch_dynamic_proxy_result",
        lambda *args, **kwargs: DynamicProxyFetchResult(
            provider="zdaye_free_proxy",
            error="empty_candidates",
            message="站大爷代理 API 未返回可用候选代理",
            checked_candidates=0,
            total_candidates=0,
        ),
    )

    response = client.post(
        "/api/settings/proxy/dynamic/test",
        json={
            "enabled": True,
            "api_url": "https://open.zdaye.com/FreeProxy/Get/?api=demo",
            "api_key": "secret",
            "api_key_header": "X-API-Key",
            "result_field": "",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["provider"] == "zdaye_free_proxy"
    assert payload["error"] == "empty_candidates"
    assert payload["message"] == "站大爷代理 API 未返回可用候选代理"

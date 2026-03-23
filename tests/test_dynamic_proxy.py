from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core import dynamic_proxy
from src.core.dynamic_proxy_types import DynamicProxyFetchResult
from src.core.zdaye_proxy import fetch_zdaye_proxy, fetch_zdaye_proxy_with_cache
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


def test_fetch_zdaye_proxy_with_cache_reuses_cached_candidates(monkeypatch):
    store = {}

    class DummySetting:
        def __init__(self, value):
            self.value = value

    class DummyDB:
        pass

    class DummyContext:
        def __enter__(self):
            return DummyDB()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("src.database.session.get_db", lambda: DummyContext())
    monkeypatch.setattr(
        "src.database.crud.get_setting",
        lambda db, key: DummySetting(store[key]) if key in store else None,
    )
    monkeypatch.setattr(
        "src.database.crud.set_setting",
        lambda db, key, value, description=None, category="general": store.__setitem__(key, value),
    )

    calls = {"fetch": 0}

    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "code": "10001",
            "msg": "ok",
            "data": [
                {"ip": "1.1.1.1", "port": 8001, "protocol": "http"},
                {"ip": "2.2.2.2", "port": 8002, "protocol": "http"},
            ],
        },
        text="",
    )

    def fake_get(*args, **kwargs):
        calls["fetch"] += 1
        return response

    monkeypatch.setattr("src.core.zdaye_proxy.fingerprinted_get", fake_get)
    monkeypatch.setattr("src.core.zdaye_proxy.random.shuffle", lambda items: None)
    monkeypatch.setattr(
        "src.core.zdaye_proxy.probe_proxy_connectivity",
        lambda proxy_url: DynamicProxyFetchResult(
            proxy_url=proxy_url,
            provider="zdaye_free_proxy",
            verified=True,
        ),
    )

    first = fetch_zdaye_proxy_with_cache(
        "http://www.zdopen.com/FreeProxy/Get/?app_id=demo",
        api_key="secret",
        cooldown_seconds=600,
        max_attempts=3,
    )
    second = fetch_zdaye_proxy_with_cache(
        "http://www.zdopen.com/FreeProxy/Get/?app_id=demo",
        api_key="secret",
        cooldown_seconds=600,
        max_attempts=3,
    )

    assert first.verified is True
    assert second.verified is True
    assert calls["fetch"] == 1
    assert first.message == "请求新的 Zdaye 候选池并分配代理"
    assert second.message == "复用 Zdaye 缓存候选池并分配代理"


def test_fetch_zdaye_proxy_with_cache_returns_cooldown_exhausted(monkeypatch):
    store = {}

    class DummySetting:
        def __init__(self, value):
            self.value = value

    class DummyDB:
        pass

    class DummyContext:
        def __enter__(self):
            return DummyDB()

        def __exit__(self, exc_type, exc, tb):
            return False

    cached = {
        "fetched_at": 100,
        "cooldown_until": 9999999999,
        "candidates": [
            {"ip": "1.1.1.1", "port": 8001, "protocol": "http"},
            {"ip": "2.2.2.2", "port": 8002, "protocol": "http"},
        ],
        "used_candidates": {},
        "failed_candidates": {
            "http://1.1.1.1:8001": 101,
            "http://2.2.2.2:8002": 102,
        },
    }
    store["proxy.zdaye_candidate_cache"] = __import__("json").dumps(cached)

    monkeypatch.setattr("src.database.session.get_db", lambda: DummyContext())
    monkeypatch.setattr(
        "src.database.crud.get_setting",
        lambda db, key: DummySetting(store[key]) if key in store else None,
    )
    monkeypatch.setattr(
        "src.database.crud.set_setting",
        lambda db, key, value, description=None, category="general": store.__setitem__(key, value),
    )
    monkeypatch.setattr("src.core.zdaye_proxy.fingerprinted_get", lambda *args, **kwargs: None)

    result = fetch_zdaye_proxy_with_cache(
        "http://www.zdopen.com/FreeProxy/Get/?app_id=demo",
        cooldown_seconds=600,
        max_attempts=3,
    )

    assert result.proxy_url is None
    assert result.error == "cooldown_exhausted"
    assert result.message == "zdaye cooldown active and all cached candidates exhausted"
    assert store["proxy.zdaye_candidate_cache"] == ""


def test_fetch_zdaye_proxy_with_cache_tries_beyond_three_candidates(monkeypatch):
    store = {}

    class DummySetting:
        def __init__(self, value):
            self.value = value

    class DummyDB:
        pass

    class DummyContext:
        def __enter__(self):
            return DummyDB()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("src.database.session.get_db", lambda: DummyContext())
    monkeypatch.setattr(
        "src.database.crud.get_setting",
        lambda db, key: DummySetting(store[key]) if key in store else None,
    )
    monkeypatch.setattr(
        "src.database.crud.set_setting",
        lambda db, key, value, description=None, category="general": store.__setitem__(key, value),
    )
    monkeypatch.setattr("src.core.zdaye_proxy.fingerprinted_get", lambda *args, **kwargs: SimpleNamespace(
        status_code=200,
        json=lambda: {
            "code": "10001",
            "msg": "ok",
            "data": [
                {"ip": "1.1.1.1", "port": 8001, "protocol": "http"},
                {"ip": "2.2.2.2", "port": 8002, "protocol": "http"},
                {"ip": "3.3.3.3", "port": 8003, "protocol": "http"},
                {"ip": "4.4.4.4", "port": 8004, "protocol": "http"},
            ],
        },
        text="",
    ))
    monkeypatch.setattr("src.core.zdaye_proxy.random.shuffle", lambda items: None)

    seen = []

    def fake_probe(proxy_url):
        seen.append(proxy_url)
        if proxy_url == "http://4.4.4.4:8004":
            return DynamicProxyFetchResult(proxy_url=proxy_url, provider="zdaye_free_proxy", verified=True)
        return DynamicProxyFetchResult(proxy_url=proxy_url, provider="zdaye_free_proxy", error="probe_failed", message="down")

    monkeypatch.setattr("src.core.zdaye_proxy.probe_proxy_connectivity", fake_probe)

    result = fetch_zdaye_proxy_with_cache(
        "http://www.zdopen.com/FreeProxy/Get/?app_id=demo",
        cooldown_seconds=600,
    )

    assert result.verified is True
    assert result.proxy_url == "http://4.4.4.4:8004"
    assert seen == [
        "http://1.1.1.1:8001",
        "http://2.2.2.2:8002",
        "http://3.3.3.3:8003",
        "http://4.4.4.4:8004",
    ]


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

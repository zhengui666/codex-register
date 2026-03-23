from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .dynamic_proxy_types import DynamicProxyFetchResult, ProxyCandidate
from .fingerprint import fingerprinted_get

logger = logging.getLogger(__name__)

ZDAYE_PROVIDER_NAME = "zdaye_free_proxy"
ZDAYE_SUCCESS_CODE = "10001"
ZDAYE_REQUEST_TIMEOUT = 10
ZDAYE_PROBE_TIMEOUT = 8
ZDAYE_CANDIDATE_COUNT = 20
ZDAYE_PROBE_URL = "https://api.ipify.org?format=json"
ZDAYE_CACHE_SETTING_KEY = "proxy.zdaye_candidate_cache"
ZDAYE_CACHE_DESCRIPTION = "Zdaye candidate pool cache"


@dataclass
class ZdayeCandidateCache:
    fetched_at: int
    cooldown_until: int
    candidates: list[ProxyCandidate] = field(default_factory=list)
    used_candidates: dict[str, int] = field(default_factory=dict)
    failed_candidates: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "cooldown_until": self.cooldown_until,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "used_candidates": self.used_candidates,
            "failed_candidates": self.failed_candidates,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ZdayeCandidateCache":
        candidates: list[ProxyCandidate] = []
        for item in data.get("candidates", []):
            if not isinstance(item, dict):
                continue
            try:
                candidate = ProxyCandidate.from_dict(item)
            except (TypeError, ValueError):
                continue
            if candidate.ip and candidate.port:
                candidates.append(candidate)

        return cls(
            fetched_at=int(data.get("fetched_at", 0) or 0),
            cooldown_until=int(data.get("cooldown_until", 0) or 0),
            candidates=candidates,
            used_candidates={
                str(key): int(value)
                for key, value in dict(data.get("used_candidates", {})).items()
            },
            failed_candidates={
                str(key): int(value)
                for key, value in dict(data.get("failed_candidates", {})).items()
            },
        )


def is_zdaye_free_proxy_api(api_url: str) -> bool:
    parsed = urlparse(api_url or "")
    if not parsed.scheme or not parsed.netloc:
        return False

    normalized_path = parsed.path.lower().rstrip("/")
    return normalized_path.endswith("/freeproxy/get") or "freeproxy/get" in normalized_path


def fetch_zdaye_proxy(api_url: str, api_key: str = "") -> DynamicProxyFetchResult:
    candidates_result = _fetch_zdaye_candidates(api_url=api_url, api_key=api_key)
    if candidates_result.error:
        return candidates_result

    candidates = list(candidates_result.candidates)
    random.shuffle(candidates)
    for checked, candidate in enumerate(candidates, start=1):
        probe = probe_proxy_connectivity(candidate.to_proxy_url())
        if probe.verified:
            probe.provider = ZDAYE_PROVIDER_NAME
            probe.checked_candidates = checked
            probe.total_candidates = len(candidates)
            probe.candidates = candidates
            return probe

    return DynamicProxyFetchResult(
        provider=ZDAYE_PROVIDER_NAME,
        error="no_available_proxy",
        message=f"站大爷返回了 {len(candidates)} 个候选代理，但连通性探测均失败",
        checked_candidates=len(candidates),
        total_candidates=len(candidates),
        candidates=candidates,
    )


def fetch_zdaye_proxy_with_cache(
    api_url: str,
    api_key: str = "",
    cooldown_seconds: int = 600,
    max_candidates: int = ZDAYE_CANDIDATE_COUNT,
    max_attempts: int = 0,
) -> DynamicProxyFetchResult:
    from ..database import crud
    from ..database.session import get_db

    with get_db() as db:
        cache = _load_cached_pool(db)
        now = int(time.time())
        cache_refreshed = False

        if cache is None or cache.cooldown_until <= now:
            candidates_result = _fetch_zdaye_candidates(
                api_url=api_url,
                api_key=api_key,
                max_candidates=max_candidates,
            )
            if candidates_result.error:
                return candidates_result

            cache = ZdayeCandidateCache(
                fetched_at=now,
                cooldown_until=now + max(cooldown_seconds, 0),
                candidates=list(candidates_result.candidates),
            )
            _save_cached_pool(db, cache)
            cache_refreshed = True

        ordered_candidates = _order_cached_candidates(cache)
        attempted = 0

        attempt_limit = max_attempts if max_attempts and max_attempts > 0 else len(ordered_candidates)

        for candidate in ordered_candidates:
            if attempted >= attempt_limit:
                break
            attempted += 1

            probe = probe_proxy_connectivity(candidate.to_proxy_url())
            candidate_key = candidate.cache_key()
            if probe.verified:
                cache.used_candidates[candidate_key] = int(time.time())
                cache.failed_candidates.pop(candidate_key, None)
                _save_cached_pool(db, cache)
                probe.provider = ZDAYE_PROVIDER_NAME
                probe.checked_candidates = attempted
                probe.total_candidates = len(cache.candidates)
                probe.candidates = list(cache.candidates)
                if cache_refreshed:
                    probe.message = "请求新的 Zdaye 候选池并分配代理"
                else:
                    probe.message = "复用 Zdaye 缓存候选池并分配代理"
                return probe

            cache.failed_candidates[candidate_key] = int(time.time())

        _save_cached_pool(db, cache)
        if cache.cooldown_until > int(time.time()):
            exhausted_pool = attempted >= len(ordered_candidates)
            if exhausted_pool:
                _clear_cached_pool(db)
            return DynamicProxyFetchResult(
                provider=ZDAYE_PROVIDER_NAME,
                error="cooldown_exhausted" if exhausted_pool else "cooldown_retry_limit_reached",
                message=(
                    "zdaye cooldown active and all cached candidates exhausted"
                    if exhausted_pool
                    else "zdaye cooldown active and max cached candidate attempts reached"
                ),
                checked_candidates=attempted,
                total_candidates=len(cache.candidates),
                candidates=list(cache.candidates),
            )

        return DynamicProxyFetchResult(
            provider=ZDAYE_PROVIDER_NAME,
            error="no_available_proxy",
            message="站大爷候选池中没有可用代理",
            checked_candidates=attempted,
            total_candidates=len(cache.candidates),
            candidates=list(cache.candidates),
        )


def probe_proxy_connectivity(proxy_url: str) -> DynamicProxyFetchResult:
    started = time.time()
    try:
        response = fingerprinted_get(
            ZDAYE_PROBE_URL,
            timeout=ZDAYE_PROBE_TIMEOUT,
            proxies={"http": proxy_url, "https": proxy_url},
        )
    except Exception as exc:
        logger.debug("代理探测失败 %s: %s", proxy_url, exc)
        return DynamicProxyFetchResult(
            proxy_url=proxy_url,
            provider=ZDAYE_PROVIDER_NAME,
            error="probe_failed",
            message=f"代理探测失败: {exc}",
            probe_url=ZDAYE_PROBE_URL,
        )

    elapsed = int((time.time() - started) * 1000)
    if response.status_code != 200:
        return DynamicProxyFetchResult(
            proxy_url=proxy_url,
            provider=ZDAYE_PROVIDER_NAME,
            error="probe_bad_status",
            message=f"代理探测返回 HTTP {response.status_code}",
            probe_response_time=elapsed,
            probe_url=ZDAYE_PROBE_URL,
        )

    ip = ""
    try:
        ip = str(response.json().get("ip", "")).strip()
    except Exception:
        ip = ""

    return DynamicProxyFetchResult(
        proxy_url=proxy_url,
        provider=ZDAYE_PROVIDER_NAME,
        verified=True,
        probe_ip=ip,
        probe_response_time=elapsed,
        probe_url=ZDAYE_PROBE_URL,
    )


def _fetch_zdaye_candidates(
    api_url: str,
    api_key: str = "",
    max_candidates: int = ZDAYE_CANDIDATE_COUNT,
) -> DynamicProxyFetchResult:
    request_url = _build_request_url(api_url, api_key)

    try:
        response = fingerprinted_get(request_url, timeout=ZDAYE_REQUEST_TIMEOUT)
    except Exception as exc:
        logger.error("站大爷动态代理请求失败: %s", exc)
        return DynamicProxyFetchResult(
            provider=ZDAYE_PROVIDER_NAME,
            error="request_failed",
            message=f"站大爷代理 API 请求失败: {exc}",
        )

    if response.status_code != 200:
        logger.warning("站大爷动态代理返回错误状态码: %s", response.status_code)
        return DynamicProxyFetchResult(
            provider=ZDAYE_PROVIDER_NAME,
            error="bad_status",
            message=f"站大爷代理 API 返回 HTTP {response.status_code}",
        )

    try:
        payload = response.json()
    except Exception:
        try:
            payload = json.loads(response.text)
        except Exception:
            return DynamicProxyFetchResult(
                provider=ZDAYE_PROVIDER_NAME,
                error="invalid_json",
                message="站大爷代理 API 返回了无法解析的 JSON",
            )

    code = str(payload.get("code", "")).strip()
    msg = str(payload.get("msg", "")).strip()
    if code != ZDAYE_SUCCESS_CODE:
        return DynamicProxyFetchResult(
            provider=ZDAYE_PROVIDER_NAME,
            error="provider_error",
            message=f"站大爷代理 API 返回错误: {code or 'unknown'} {msg}".strip(),
        )

    try:
        candidates = _parse_candidates(payload)
    except (TypeError, ValueError) as exc:
        logger.warning("站大爷动态代理响应结构异常: %s", exc)
        return DynamicProxyFetchResult(
            provider=ZDAYE_PROVIDER_NAME,
            error="invalid_structure",
            message=f"站大爷代理 API 响应结构异常: {exc}",
        )

    if not candidates:
        return DynamicProxyFetchResult(
            provider=ZDAYE_PROVIDER_NAME,
            error="invalid_structure",
            message="站大爷代理 API 未返回可用候选代理",
        )

    return DynamicProxyFetchResult(
        provider=ZDAYE_PROVIDER_NAME,
        total_candidates=len(candidates[:max_candidates]),
        candidates=list(candidates[:max_candidates]),
    )


def _order_cached_candidates(cache: ZdayeCandidateCache) -> list[ProxyCandidate]:
    if not cache.candidates:
        return []

    available = [
        candidate
        for candidate in cache.candidates
        if candidate.cache_key() not in cache.failed_candidates
    ]
    if not available:
        return []

    unused = [
        candidate for candidate in available if candidate.cache_key() not in cache.used_candidates
    ]
    reusable = [
        candidate for candidate in available if candidate.cache_key() in cache.used_candidates
    ]

    random.shuffle(unused)
    reusable.sort(key=lambda candidate: cache.used_candidates.get(candidate.cache_key(), 0))
    return unused + reusable


def _load_cached_pool(db) -> ZdayeCandidateCache | None:
    from ..database import crud

    db_setting = crud.get_setting(db, ZDAYE_CACHE_SETTING_KEY)
    if not db_setting or not db_setting.value:
        return None

    try:
        payload = json.loads(db_setting.value)
    except json.JSONDecodeError:
        logger.warning("Zdaye 候选池缓存 JSON 无法解析，忽略旧缓存")
        return None

    cache = ZdayeCandidateCache.from_dict(payload)
    if not cache.candidates:
        return None
    return cache


def _save_cached_pool(db, cache: ZdayeCandidateCache) -> None:
    from ..database import crud

    crud.set_setting(
        db,
        key=ZDAYE_CACHE_SETTING_KEY,
        value=json.dumps(cache.to_dict(), ensure_ascii=False),
        description=ZDAYE_CACHE_DESCRIPTION,
        category="proxy",
    )


def _clear_cached_pool(db) -> None:
    from ..database import crud

    crud.set_setting(
        db,
        key=ZDAYE_CACHE_SETTING_KEY,
        value="",
        description=ZDAYE_CACHE_DESCRIPTION,
        category="proxy",
    )


def _build_request_url(api_url: str, api_key: str) -> str:
    parsed = urlparse(api_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if api_key and "akey" not in query:
        query["akey"] = api_key

    query.update(
        {
            "count": str(ZDAYE_CANDIDATE_COUNT),
            "return_type": "3",
            "dalu": query.get("dalu", "0"),
            "adr": query.get("adr", "美国"),
            "protocol_type": query.get("protocol_type", "1"),
            "level_type": query.get("level_type", "1"),
            "lastcheck_type": query.get("lastcheck_type", "2"),
            "sleep_type": query.get("sleep_type", "2"),
        }
    )

    return urlunparse(parsed._replace(query=urlencode(query)))


def _parse_candidates(payload: dict[str, Any]) -> list[ProxyCandidate]:
    data = payload.get("data")
    if isinstance(data, dict):
        if "proxy_list" not in data:
            raise TypeError("站大爷 data.proxy_list 字段缺失")
        data = data.get("proxy_list")
    elif data is None:
        data = []

    if not isinstance(data, Iterable) or isinstance(data, (str, bytes, dict)):
        raise TypeError("站大爷 data 字段不是候选列表")

    candidates: list[ProxyCandidate] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip", "")).strip()
        port_raw = item.get("port")
        if not ip or port_raw in (None, ""):
            continue

        candidates.append(
            ProxyCandidate(
                ip=ip,
                port=int(port_raw),
                protocol=str(item.get("protocol", "http") or "http"),
                adr=str(item.get("adr", "") or ""),
                level=str(item.get("level", "") or ""),
            )
        )

    return candidates

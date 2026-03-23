from __future__ import annotations

import json
import logging
import random
import time
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


def is_zdaye_free_proxy_api(api_url: str) -> bool:
    parsed = urlparse(api_url or "")
    if not parsed.scheme or not parsed.netloc:
        return False

    normalized_path = parsed.path.lower().rstrip("/")
    return normalized_path.endswith("/freeproxy/get") or "freeproxy/get" in normalized_path


def fetch_zdaye_proxy(api_url: str, api_key: str = "") -> DynamicProxyFetchResult:
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
        payload = json.loads(response.text)
    except json.JSONDecodeError:
        logger.warning("站大爷动态代理返回非 JSON 内容")
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
            error="empty_candidates",
            message="站大爷代理 API 未返回可用候选代理",
            total_candidates=0,
        )

    random.shuffle(candidates)

    for checked, candidate in enumerate(candidates, start=1):
        probe = probe_proxy_connectivity(candidate.to_proxy_url())
        if probe.verified:
            probe.provider = ZDAYE_PROVIDER_NAME
            probe.checked_candidates = checked
            probe.total_candidates = len(candidates)
            probe.message = (
                f"站大爷代理可用，已从 {len(candidates)} 个美国海外候选中随机筛出可用代理"
            )
            return probe

    return DynamicProxyFetchResult(
        provider=ZDAYE_PROVIDER_NAME,
        error="no_available_proxy",
        message=f"站大爷返回了 {len(candidates)} 个候选代理，但连通性探测均失败",
        checked_candidates=len(candidates),
        total_candidates=len(candidates),
    )


def probe_proxy_connectivity(proxy_url: str, *, timeout: int = ZDAYE_PROBE_TIMEOUT) -> DynamicProxyFetchResult:
    start = time.time()
    try:
        response = fingerprinted_get(
            ZDAYE_PROBE_URL,
            proxies={"http": proxy_url, "https": proxy_url},
            headers=None,
            timeout=timeout,
        )
    except Exception as exc:
        return DynamicProxyFetchResult(
            proxy_url=proxy_url,
            provider=ZDAYE_PROVIDER_NAME,
            error="probe_failed",
            message=f"代理连通性探测失败: {exc}",
        )

    elapsed = round((time.time() - start) * 1000)
    if response.status_code != 200:
        return DynamicProxyFetchResult(
            proxy_url=proxy_url,
            provider=ZDAYE_PROVIDER_NAME,
            error="probe_bad_status",
            message=f"代理连通性探测失败: HTTP {response.status_code}",
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


def _build_request_url(api_url: str, api_key: str) -> str:
    parsed = urlparse(api_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if api_key:
        query["akey"] = api_key

    query.update(
        {
            "count": str(ZDAYE_CANDIDATE_COUNT),
            "return_type": "3",
            "dalu": "0",
            "adr": "美国",
            "protocol_type": "1",
            "level_type": "1",
            "lastcheck_type": "2",
            "sleep_type": "2",
        }
    )

    return urlunparse(parsed._replace(query=urlencode(query)))


def _parse_candidates(payload: dict[str, Any]) -> list[ProxyCandidate]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("缺少 data 对象")

    proxy_list = data.get("proxy_list")
    if not isinstance(proxy_list, Iterable) or isinstance(proxy_list, (str, bytes, dict)):
        raise ValueError("缺少 proxy_list 数组")

    candidates: list[ProxyCandidate] = []
    for item in proxy_list:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip", "")).strip()
        port = item.get("port")
        protocol = str(item.get("protocol", "http")).strip().lower() or "http"
        if not ip or port in (None, ""):
            continue
        try:
            port_int = int(port)
        except (TypeError, ValueError):
            continue
        candidates.append(
            ProxyCandidate(
                ip=ip,
                port=port_int,
                protocol=protocol,
                adr=str(item.get("adr", "")).strip(),
                level=str(item.get("level", "")).strip(),
            )
        )
    return candidates

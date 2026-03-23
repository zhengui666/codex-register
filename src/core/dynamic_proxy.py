"""
动态代理获取模块
支持通过外部 API 获取动态代理 URL
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from .dynamic_proxy_types import DynamicProxyFetchResult
from .zdaye_proxy import fetch_zdaye_proxy, is_zdaye_free_proxy_api

logger = logging.getLogger(__name__)


def fetch_dynamic_proxy_result(
    api_url: str,
    api_key: str = "",
    api_key_header: str = "X-API-Key",
    result_field: str = "",
) -> DynamicProxyFetchResult:
    """
    从代理 API 获取代理 URL 及调试信息。
    """
    if is_zdaye_free_proxy_api(api_url):
        return fetch_zdaye_proxy(api_url=api_url, api_key=api_key)

    return _fetch_generic_dynamic_proxy(
        api_url=api_url,
        api_key=api_key,
        api_key_header=api_key_header,
        result_field=result_field,
    )


def fetch_dynamic_proxy(
    api_url: str,
    api_key: str = "",
    api_key_header: str = "X-API-Key",
    result_field: str = "",
) -> Optional[str]:
    return fetch_dynamic_proxy_result(
        api_url=api_url,
        api_key=api_key,
        api_key_header=api_key_header,
        result_field=result_field,
    ).proxy_url


def _fetch_generic_dynamic_proxy(
    api_url: str,
    api_key: str = "",
    api_key_header: str = "X-API-Key",
    result_field: str = "",
) -> DynamicProxyFetchResult:
    try:
        from .fingerprint import fingerprinted_get

        headers = {}
        if api_key:
            headers[api_key_header] = api_key

        response = fingerprinted_get(
            api_url,
            headers=headers,
            timeout=10,
        )

        if response.status_code != 200:
            logger.warning("动态代理 API 返回错误状态码: %s", response.status_code)
            return DynamicProxyFetchResult(
                provider="generic",
                error="bad_status",
                message=f"动态代理 API 返回 HTTP {response.status_code}",
            )

        proxy_url = _extract_proxy_url(response.text.strip(), result_field)
        if not proxy_url:
            logger.warning("动态代理 API 返回空代理 URL")
            return DynamicProxyFetchResult(
                provider="generic",
                error="empty_response",
                message="动态代理 API 返回为空或未提取到代理地址",
            )

        proxy_url = _normalize_proxy_url(proxy_url)
        logger.info(
            "动态代理获取成功: %s",
            f"{proxy_url[:40]}..." if len(proxy_url) > 40 else proxy_url,
        )
        return DynamicProxyFetchResult(
            proxy_url=proxy_url,
            provider="generic",
            message="动态代理地址获取成功",
        )

    except Exception as exc:
        logger.error("获取动态代理失败: %s", exc)
        return DynamicProxyFetchResult(
            provider="generic",
            error="request_failed",
            message=f"获取动态代理失败: {exc}",
        )


def _extract_proxy_url(text: str, result_field: str) -> Optional[str]:
    if not text:
        return None

    if result_field or text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
            if result_field:
                data = _extract_json_path(data, result_field)
                return str(data).strip() if data is not None else None

            if isinstance(data, dict):
                for key in ("proxy", "url", "proxy_url", "data", "ip"):
                    value = data.get(key)
                    if value:
                        return str(value).strip()
            return text
        except (ValueError, AttributeError, IndexError, TypeError):
            return text

    return text


def _extract_json_path(data: Any, result_field: str) -> Any:
    current = data
    for key in result_field.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            current = current[int(key)]
        else:
            return None
        if current is None:
            return None
    return current


def _normalize_proxy_url(proxy_url: str) -> str:
    if not re.match(r"^(http|https|socks4|socks5)://", proxy_url):
        return "http://" + proxy_url
    return proxy_url


def get_proxy_url_for_task() -> Optional[str]:
    """
    为注册任务获取代理 URL。
    优先使用动态代理（若启用），否则使用静态代理配置。

    Returns:
        代理 URL 或 None
    """
    from ..config.settings import get_settings
    settings = get_settings()

    # 优先使用动态代理
    if settings.proxy_dynamic_enabled and settings.proxy_dynamic_api_url:
        api_key = settings.proxy_dynamic_api_key.get_secret_value() if settings.proxy_dynamic_api_key else ""
        proxy_url = fetch_dynamic_proxy(
            api_url=settings.proxy_dynamic_api_url,
            api_key=api_key,
            api_key_header=settings.proxy_dynamic_api_key_header,
            result_field=settings.proxy_dynamic_result_field,
        )
        if proxy_url:
            return proxy_url
        logger.warning("动态代理获取失败，回退到静态代理")

    # 使用静态代理
    return settings.proxy_url

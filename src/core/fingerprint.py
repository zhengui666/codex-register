"""随机化 Chrome/浏览器指纹配置。

策略约束:
1. 业务代码不要手动拼接 UA、sec-ch-ua、accept-language 或 impersonate。
2. 直连 curl_cffi 请求统一使用 build_request_context()。
3. curl_cffi Session 统一使用 build_session_kwargs()。
4. 如果某个流程需要同一会话内保持稳定指纹，先生成 profile，再在该流程内复用。
"""

from __future__ import annotations

import random
from typing import Any, Optional

from curl_cffi import requests as cffi_requests


_CHROME_VERSIONS = [110, 111, 112, 116, 120, 124, 126, 128, 130]
_PLATFORMS = [
    "Windows",
    "Windows NT 10.0",
    "macOS",
    "Linux x86_64",
]
_LANGS = ["zh-CN", "zh-TW", "en-US", "en-GB"]
_TIMEZONES = ["Asia/Shanghai", "Asia/Singapore", "America/Los_Angeles", "Europe/London"]
_SCREEN_SIZES = [
    (1366, 768),
    (1440, 900),
    (1536, 864),
    (1920, 1080),
]


def _sec_ch_ua(version: int) -> str:
    return (
        f'"Chromium";v="{version}", '
        f'"Google Chrome";v="{version}", '
        f'"Not:A-Brand";v="99"'
    )


def random_browser_profile() -> dict:
    version = random.choice(_CHROME_VERSIONS)
    platform = random.choice(_PLATFORMS)
    lang = random.choice(_LANGS)
    timezone = random.choice(_TIMEZONES)
    width, height = random.choice(_SCREEN_SIZES)
    return {
        "impersonate": f"chrome{version}",
        "user_agent": (
            f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{version}.0.0.0 Safari/537.36"
        ),
        "sec_ch_ua": _sec_ch_ua(version),
        "platform": platform,
        "language": lang,
        "timezone": timezone,
        "screen": {"width": width, "height": height},
    }


def random_chrome_profile() -> dict:
    profile = random_browser_profile()
    return {
        "impersonate": profile["impersonate"],
        "user_agent": profile["user_agent"],
    }


def chrome_like_headers(profile: dict | None = None) -> dict:
    if profile is None:
        profile = random_browser_profile()
    return {
        "user-agent": profile["user_agent"],
        "sec-ch-ua": profile["sec_ch_ua"],
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": f"\"{profile['platform']}\"",
        "accept-language": f"{profile['language']},en;q=0.9",
    }


def build_request_context(headers: Optional[dict[str, str]] = None, profile: Optional[dict[str, Any]] = None) -> dict:
    """构造一套统一的请求上下文，用于 curl_cffi 直连请求。"""
    if profile is None:
        profile = random_browser_profile()
    merged_headers = {}
    if headers:
        merged_headers.update(headers)
    merged_headers.update(chrome_like_headers(profile))
    return {
        "profile": profile,
        "headers": merged_headers,
        "impersonate": profile["impersonate"],
    }


def build_session_kwargs(profile: Optional[dict[str, Any]] = None, **kwargs: Any) -> dict:
    """构造 curl_cffi Session 的统一参数。"""
    if profile is None:
        profile = random_browser_profile()
    session_kwargs = dict(kwargs)
    session_kwargs["impersonate"] = profile["impersonate"]
    if "headers" in session_kwargs and session_kwargs["headers"]:
        session_kwargs["headers"] = build_request_context(session_kwargs["headers"], profile)["headers"]
    else:
        session_kwargs["headers"] = chrome_like_headers(profile)
    return session_kwargs


def fingerprinted_session(**kwargs: Any):
    """创建带统一随机指纹的 curl_cffi Session。"""
    return cffi_requests.Session(**build_session_kwargs(**kwargs))


def fingerprinted_get(url: str, **kwargs: Any):
    """发送带统一随机指纹的 GET 请求。"""
    context = build_request_context(kwargs.pop("headers", None), kwargs.pop("profile", None))
    return cffi_requests.get(url, headers=context["headers"], impersonate=context["impersonate"], **kwargs)


def fingerprinted_post(url: str, **kwargs: Any):
    """发送带统一随机指纹的 POST 请求。"""
    context = build_request_context(kwargs.pop("headers", None), kwargs.pop("profile", None))
    return cffi_requests.post(url, headers=context["headers"], impersonate=context["impersonate"], **kwargs)


def fingerprinted_options(url: str, **kwargs: Any):
    """发送带统一随机指纹的 OPTIONS 请求。"""
    context = build_request_context(kwargs.pop("headers", None), kwargs.pop("profile", None))
    return cffi_requests.options(url, headers=context["headers"], impersonate=context["impersonate"], **kwargs)

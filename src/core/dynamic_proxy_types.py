from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProxyCandidate:
    ip: str
    port: int
    protocol: str = "http"
    adr: str = ""
    level: str = ""

    def to_proxy_url(self) -> str:
        protocol = (self.protocol or "http").lower()
        if protocol not in {"http", "https", "socks4", "socks5"}:
            protocol = "http"
        return f"{protocol}://{self.ip}:{self.port}"


@dataclass
class DynamicProxyFetchResult:
    proxy_url: Optional[str] = None
    provider: str = "generic"
    message: str = ""
    error: Optional[str] = None
    checked_candidates: int = 0
    total_candidates: int = 0
    verified: bool = False
    probe_ip: str = ""
    probe_response_time: Optional[int] = None
    probe_url: str = ""

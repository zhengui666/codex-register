from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


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

    def cache_key(self) -> str:
        return f"{(self.protocol or 'http').lower()}://{self.ip}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "protocol": self.protocol,
            "adr": self.adr,
            "level": self.level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProxyCandidate":
        return cls(
            ip=str(data.get("ip", "")).strip(),
            port=int(data.get("port", 0)),
            protocol=str(data.get("protocol", "http") or "http"),
            adr=str(data.get("adr", "") or ""),
            level=str(data.get("level", "") or ""),
        )


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
    candidates: list[ProxyCandidate] = field(default_factory=list)

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class FetchResult:
    url: str          # final URL (after redirects)
    status: int
    html: str
    elapsed_ms: int
    from_cache: bool = False


class Fetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult: ...

    async def aclose(self) -> None: ...

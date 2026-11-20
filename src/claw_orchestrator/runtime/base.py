from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RuntimeResult:
    runtime_id: str
    upstream_url: str
    container_name: str


class Runtime(Protocol):
    available: bool
    reason: str

    async def provision(self, instance: dict) -> RuntimeResult: ...

    async def probe(self, instance: dict) -> bool: ...

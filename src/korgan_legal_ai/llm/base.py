from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    @abstractmethod
    def parse(self, *, model: str, system: str, user: str, schema: type[T]) -> T:
        """Return model output validated as the requested Pydantic schema."""
        raise NotImplementedError

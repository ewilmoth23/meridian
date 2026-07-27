"""Ports for AI services (LLM, OCR, vision).

All AI use is optional and pluggable. The deed-parsing pipeline can run
fully without an LLM (regex-only) — when an LLM is configured, it falls
back to it on regex failure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Plain wrapper around an LLM completion."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    extra: dict[str, object] | None = None


class LLMClient(ABC):
    """Abstract LLM client."""

    name: str = ""

    @abstractmethod
    def complete(self, prompt: str, *, system: str | None = None, temperature: float = 0.0) -> LLMResponse:
        ...


class OCRClient(ABC):
    """Abstract OCR client (image / PDF → text)."""

    name: str = ""

    @abstractmethod
    def recognize_image(self, path: Path, *, languages: tuple[str, ...] = ("eng",)) -> str:
        ...


class VisionClient(ABC):
    """Abstract vision client (image + prompt → structured response)."""

    name: str = ""

    @abstractmethod
    def analyze(self, image_path: Path, prompt: str) -> str:
        ...

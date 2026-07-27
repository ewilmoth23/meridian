"""DeedLM inference adapter.

Two backends:

* **Ollama** — local, the default. Invokes a model served by an Ollama
  daemon (``ollama serve``). Zero per-document cost.
* **HuggingFace** — load the base + LoRA adapter directly with
  ``transformers``. Requires a GPU for production speed.

Both implement :class:`meridian.ports.ai.LLMClient`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from meridian.ai.deedlm.finetune import render_prompt
from meridian.ports.ai import LLMClient, LLMResponse


@dataclass(slots=True)
class OllamaDeedLM(LLMClient):
    """LLM client backed by a local Ollama model."""

    name: str = "deedlm-ollama"
    model: str = "deedlm:latest"
    host: str = "http://127.0.0.1:11434"
    timeout: float = 60.0

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        try:
            import requests
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("requests is required") from e
        wrapped = render_prompt(prompt) if system is None else f"<|system|>\n{system}\n<|user|>\n{prompt}\n<|assistant|>\n"
        r = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": self.model,
                "prompt": wrapped,
                "options": {"temperature": temperature},
                "stream": False,
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        data = r.json()
        return LLMResponse(
            text=data.get("response", ""),
            model=self.model,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
            extra={"backend": "ollama"},
        )


@dataclass(slots=True)
class HFDeedLM(LLMClient):
    """LLM client that loads the base + LoRA adapter directly."""

    name: str = "deedlm-hf"
    base_model: str = "mistralai/Mistral-7B-v0.3"
    adapter_path: Path | None = None
    device: str = "cuda"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:  # pragma: no cover — requires GPU
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as e:
            raise RuntimeError(
                "HFDeedLM requires transformers + peft + torch."
            ) from e

        tokenizer = AutoTokenizer.from_pretrained(self.base_model, use_fast=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )
        if self.adapter_path is not None:
            model = PeftModel.from_pretrained(model, str(self.adapter_path))
        wrapped = render_prompt(prompt) if system is None else f"<|system|>\n{system}\n<|user|>\n{prompt}\n<|assistant|>\n"
        inputs = tokenizer(wrapped, return_tensors="pt").to(model.device)
        out = model.generate(**inputs, max_new_tokens=512, temperature=temperature, do_sample=temperature > 0.0)
        text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return LLMResponse(
            text=text,
            model=self.base_model,
            extra={"backend": "hf", "adapter": str(self.adapter_path)},
        )


def parse_deedlm_response(text: str) -> dict:
    """Extract a JSON object from a DeedLM completion.

    The model is trained to emit pure JSON, but we tolerate a stray
    leading / trailing markdown fence or comment.
    """
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rstrip("`").rstrip()
    # Locate the first '{' and the last '}' for resilience.
    first = s.find("{")
    last = s.rfind("}")
    if first == -1 or last == -1 or last <= first:
        raise ValueError(f"No JSON object found in DeedLM response: {text[:200]!r}")
    return json.loads(s[first : last + 1])

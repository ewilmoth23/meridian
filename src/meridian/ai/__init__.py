"""DeedLM + Pulse — domain LLM and conversational co-pilot (v0.4).

Two paired features:

**DeedLM** — domain-specific transformer fine-tuned on US deed corpora.
Lives under :mod:`meridian.ai.deedlm`.

**Pulse** — docked AI co-pilot panel exposing tool access to the project
DB, deed parser, retracement engine, compliance engine, and field-note
dictation. Lives under :mod:`meridian.ai.pulse`.

Both are designed to run locally first (Ollama / vLLM); cloud providers
are pluggable through :mod:`meridian.ports.ai`.
"""

from __future__ import annotations

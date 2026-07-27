"""DeedLM — domain-specific transformer for cadastral / deed text.

Layout::

    deedlm/
    ├── corpus_builder.py   # assembles the training corpus from public sources
    ├── synthetic.py        # generates adversarial deed text in jurisdictional dialects
    ├── finetune.py         # LoRA fine-tune driver (HuggingFace + PEFT)
    ├── inference.py        # local-first inference adapter (Ollama / vLLM / HF)
    └── eval/               # benchmark harness

The scaffolding is shippable today so contributors can run the corpus
builder and (with a GPU) the fine-tune. The trained weights are *not*
committed to this repo — they're released through a separate channel.
"""

from __future__ import annotations

from meridian.ai.deedlm.corpus_builder import (
    CorpusBuilder,
    CorpusEntry,
)
from meridian.ai.deedlm.synthetic import generate_synthetic_deed

__all__ = ["CorpusBuilder", "CorpusEntry", "generate_synthetic_deed"]

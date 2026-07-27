"""LoRA fine-tune driver for DeedLM.

Trains a low-rank adapter on top of a small open base model
(``mistralai/Mistral-7B-v0.3``, ``meta-llama/Llama-3.1-8B``, or
``microsoft/Phi-3-mini-4k-instruct``) using the corpus produced by
:mod:`meridian.ai.deedlm.corpus_builder`.

This module is *importable* without ``transformers`` / ``peft`` /
``bitsandbytes`` installed — those are only loaded when ``train()`` is
called. That way the rest of Meridian doesn't pull in 4 GB of ML
dependencies just to import :mod:`meridian.ai.deedlm`.

Run from the CLI with:

    python -m meridian.ai.deedlm.finetune --corpus data/deedlm --base mistralai/Mistral-7B-v0.3 --out runs/deedlm-v1

Or programmatically:

    from meridian.ai.deedlm.finetune import TrainConfig, train
    train(TrainConfig(corpus_dir=Path("data/deedlm"), base="..."))
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class TrainConfig:
    """Hyperparameters + paths for a single fine-tune run."""

    corpus_dir: Path                                # produced by CorpusBuilder.write_jsonl
    base_model: str = "mistralai/Mistral-7B-v0.3"
    output_dir: Path = Path("runs/deedlm-v1")
    learning_rate: float = 2e-4
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    max_seq_length: int = 2048
    seed: int = 42
    quantization_4bit: bool = True
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    deepspeed_config: Path | None = None


SYSTEM_PROMPT = (
    "You are DeedLM, a domain-specific surveying assistant. Given a metes-and-bounds "
    "legal description, produce a JSON object with a 'calls' array. Each call has: "
    "kind (line | curve_chord | point_of_beginning), bearing_rad (azimuth from grid "
    "north, clockwise), distance_m (meters), and curve fields (radius_m, delta_rad, "
    "chord_m, clockwise) when applicable. Output ONLY valid JSON; no commentary."
)


def render_prompt(text: str) -> str:
    """Wrap a deed text in DeedLM's prompt template."""
    return f"<|system|>\n{SYSTEM_PROMPT}\n<|user|>\n{text}\n<|assistant|>\n"


def train(config: TrainConfig) -> Path:
    """Run a LoRA fine-tune. Returns the path to the saved adapter."""
    try:
        import torch  # noqa: F401
        from datasets import load_dataset
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            DataCollatorForSeq2Seq,
            Trainer,
            TrainingArguments,
        )
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "DeedLM fine-tuning requires transformers / peft / datasets / accelerate "
            "/ bitsandbytes. Install in a GPU-equipped environment with: "
            "pip install transformers peft datasets accelerate bitsandbytes torch"
        ) from e

    config.output_dir.mkdir(parents=True, exist_ok=True)

    quant = (
        BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
        if config.quantization_4bit
        else None
    )
    tokenizer = AutoTokenizer.from_pretrained(config.base_model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        config.base_model,
        quantization_config=quant,
        device_map="auto",
    )

    peft_config = LoraConfig(
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=list(config.target_modules),
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    ds = load_dataset(
        "json",
        data_files={
            "train": str(config.corpus_dir / "train.jsonl"),
            "validation": str(config.corpus_dir / "val.jsonl"),
        },
    )

    def _format(example):
        prompt = render_prompt(example["text"])
        completion = example["target_json"]
        full = prompt + completion + tokenizer.eos_token
        ids = tokenizer(full, truncation=True, max_length=config.max_seq_length)
        ids["labels"] = list(ids["input_ids"])
        return ids

    tokenised = ds.map(_format, remove_columns=ds["train"].column_names)

    training_args = TrainingArguments(
        output_dir=str(config.output_dir),
        learning_rate=config.learning_rate,
        num_train_epochs=config.num_train_epochs,
        per_device_train_batch_size=config.per_device_train_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        save_strategy="epoch",
        evaluation_strategy="epoch",
        logging_steps=20,
        bf16=True,
        deepspeed=str(config.deepspeed_config) if config.deepspeed_config else None,
        seed=config.seed,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenised["train"],
        eval_dataset=tokenised["validation"],
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model),
    )
    trainer.train()
    adapter_path = config.output_dir / "adapter"
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    return adapter_path


# CLI entry point ------------------------------------------------------------
def _main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="LoRA fine-tune DeedLM.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--base", type=str, default="mistralai/Mistral-7B-v0.3")
    parser.add_argument("--out", type=Path, default=Path("runs/deedlm-v1"))
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    args = parser.parse_args()
    config = TrainConfig(
        corpus_dir=args.corpus,
        base_model=args.base,
        output_dir=args.out,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
    )
    path = train(config)
    print(f"Adapter saved to {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())

"""Train a new, isolated QLoRA adapter from push_nervous_system_v1 only."""
from __future__ import annotations

import argparse, hashlib, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "training" / "push_nervous_system_v1"

def rows(path: Path):
    out = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not out or any(r.get("provenance") != "synthetic_structure/external_teacher" or r.get("phase8_source") for r in out):
        raise SystemExit("dataset provenance gate failed")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--allow-model-download", action="store_true")
    ap.add_argument("--base-model", default="Qwen/Qwen2.5-14B-Instruct")
    ap.add_argument("--output", type=Path, default=ROOT / "adapter_qwen25_14b_push_v1")
    args = ap.parse_args()
    train, evals = rows(ROOT / "push_sft_train.jsonl"), rows(ROOT / "push_sft_holdout.jsonl")
    manifest = {"base_model": args.base_model, "train_rows": len(train), "holdout_rows": len(evals),
                "dataset_sha256": hashlib.sha256((ROOT / "push_sft_train.jsonl").read_bytes()).hexdigest(),
                "base_overwritten": False, "production_adapter_overwritten": False}
    if not args.run:
        print(json.dumps({"status": "ready", **manifest}, ensure_ascii=False, indent=2)); return
    if args.output.exists(): raise SystemExit(f"refusing to overwrite adapter path: {args.output}")
    try:
        import torch
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments
    except ImportError as exc: raise SystemExit(f"missing training dependency: {exc.name}") from exc
    if not torch.cuda.is_available(): raise SystemExit("CUDA unavailable")
    os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "hf_cache"))
    local_only = not args.allow_model_download
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, local_files_only=local_only)
    tokenizer.pad_token = tokenizer.pad_token or tokenizer.eos_token
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                               bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(args.base_model, local_files_only=local_only, device_map={"": 0}, quantization_config=quant)
    model.config.use_cache = False
    class TokenizedRows(torch.utils.data.Dataset):
        def __init__(self, items):
            self.items = []
            for row in items:
                text = tokenizer.apply_chat_template(row["training_messages"] + [{"role":"assistant", "content":row["target"]}], tokenize=False, add_generation_prompt=False)
                encoded = tokenizer(text, truncation=True, max_length=512)
                encoded["labels"] = list(encoded["input_ids"])
                self.items.append(encoded)
        def __len__(self): return len(self.items)
        def __getitem__(self, index): return self.items[index]
    def collate(features):
        max_len = max(len(f["input_ids"]) for f in features)
        batch = {"input_ids": [], "attention_mask": [], "labels": []}
        for f in features:
            pad = max_len - len(f["input_ids"])
            batch["input_ids"].append(f["input_ids"] + [tokenizer.pad_token_id] * pad)
            batch["attention_mask"].append(f["attention_mask"] + [0] * pad)
            batch["labels"].append(f["labels"] + [-100] * pad)
        return {key: torch.tensor(value) for key, value in batch.items()}
    args.output.mkdir(parents=True)
    (args.output / "training_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    from peft import get_peft_model
    model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=.05, target_modules=["q_proj","k_proj","v_proj","o_proj"], task_type="CAUSAL_LM"))
    trainer = Trainer(model=model, tokenizer=tokenizer, train_dataset=TokenizedRows(train), eval_dataset=TokenizedRows(evals), data_collator=collate,
        args=TrainingArguments(output_dir=str(args.output / "checkpoints"), per_device_train_batch_size=1, per_device_eval_batch_size=1,
            gradient_accumulation_steps=4, learning_rate=1e-4, max_steps=48, warmup_ratio=.05, logging_steps=2, save_steps=24, eval_steps=24,
            eval_strategy="steps", optim="paged_adamw_8bit", fp16=True, gradient_checkpointing=True, report_to="none", save_total_limit=2, seed=4107))
    trainer.train(); trainer.save_model(str(args.output / "final_adapter"))
    (args.output / "COMPLETE.json").write_text(json.dumps({**manifest, "status":"complete"}, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__": main()

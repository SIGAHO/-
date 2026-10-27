# Preference pipeline v1

Runtime ledger: `<event-log>.fio.preferences/candidates.jsonl`, with separate
`reviews.jsonl`. Raw Session JSONL remains authoritative. These ledgers contain
private conversation; they stay under ignored `data/`. No historical training
assets are imported. No inference response, verifier score or ambiguous reaction
can grant human approval.

Source order: real_user_feedback > human_authored_approved > external_teacher_candidate.
All sources still require a separate human review bound to the candidate hash.
External teachers must carry teacher_generated=true, human_approved=false and
teacher_model. The target Qwen family cannot serve as its own external teacher.
An actual user can explicitly approve/reject a target response: this is feedback,
not a Qwen-authored correctness label. Candidate chosen/rejected are nullable;
one must be present. A correction's text remains feedback provenance, not an
automatically trusted replacement answer.

Version 1 fields are defined in `schema-v1.json` and validated by
`companion_core.preferences.validate`. SHA-256(session_id) assigns immutable
75% train / 15% dev / 10% blind_holdout groups. All turns from one session stay
together, even across process restarts. A consumed fixture is development data,
never an untouched blind test. Corpus size and source balancing need a human
audit before training; no universal sufficient sample count is claimed.

```powershell
python scripts/preferences.py --store data/events.jsonl.fio.preferences status
python scripts/preferences.py --store data/events.jsonl.fio.preferences approve <candidate-id> --reviewer <human-name>
python scripts/preferences.py --store data/events.jsonl.fio.preferences export --split train --output data/trusted-train.jsonl
python scripts/training_readiness.py --store data/events.jsonl.fio.preferences
```

Approval is an explicit human operation. The chat runtime never calls approve.
Import is available via `import-candidates <file.jsonl>`; unsupported/target
teacher sources and group split overrides are rejected. No blind export command
is exposed for training or tuning.

`training_readiness.py` only reports a method/config plan. KTO is a candidate
when approved singleton desirable/undesirable responses dominate; DPO or SimPO
when approved pairs dominate. Preserve the exact prompt, CPU response_spec and
raw IDs when mapping into a trainer's prompt/chosen/rejected or completion/label
format. Do not manufacture the missing side with the target model.

QLoRA requires an unquantized Hugging Face base revision and tokenizer matching
the inference base, a compatible PyTorch/CUDA/PEFT/bitsandbytes stack, enough
VRAM for weights, activations and optimizer, and disk for separate versioned
adapters. Ollama GGUF is an inference asset, not a training checkpoint. The
config is a scaffold, not a guaranteed VRAM fit. The readiness report checks
available hardware but does not install dependencies, download a base or train.
Pin actual trainer versions and base revision before a training run. Keep base
immutable and record dataset SHA, source counts, hyperparameters and adapter
parent in each run manifest. Roll back by unloading the adapter.

Primary method references: [TRL KTO](https://huggingface.co/docs/trl/kto_trainer),
[TRL DPO](https://huggingface.co/docs/trl/dpo_trainer),
[SimPO](https://github.com/princeton-nlp/SimPO).

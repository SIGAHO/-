# Breaktail v2 Hardening Phase

Base: c827924. Existing test assertions and historical experiment outcomes are unchanged.

- Unit: **237/237 PASS** (existing 157 + new 80).
- Behavior: **107/107 PASS** (state25/correction12/topic21/open_loops22/memory14/emotion13).
- Durability/fuzz: seeded 500 turns, 1000 events, zero crashes; nonruntime derived metadata equal after restart.
- Fault coverage: duplicate daemon, daemon kill, disconnect during generation, concurrent clients, stale endpoint/writer, timeout, invalid model response, partial final record, corrupt middle record, duplicate IDs/JSON keys, same-size tamper, uncertain fsync, replay, CP932/UTF-8, one-command launcher.
- Observed human corpora: 7000 utterances, 638/638 replays, zero historical structural invariant violations. Human topic metrics remain in hardening-corpus.json; this is NOT 7000 correct conversations or a new holdout.
- Real qwen2.5:14b: 6 input smoke, all six coded property checks PASS. Casual text uses the real model; generic memory/source/ambiguous/time responses are intentionally CPU guarded. No generated labels, teachers, scores or training data.
- CPU temporal fixture: 2026-10-23 07:41 Asia/Tokyo is Friday, 08:00 is 19 minutes away. Actual afternoon smoke correctly reports today's 08:00 has passed.

Guarantees: route isolation; no model calls for unsupported external facts; direct source admission rejection; no assistant fact promotion; duplicate ID no double apply; complete JSONL delimiter/schema checks; immutable append copies; event-derived IDs/times; bounded CPU arithmetic; UTF-8 boundaries; persisted supplied-context provenance.

Limits: routing and relevance rules are finite, free model prose may still be inaccurate or unnatural, and unspecified question tails are not fully guaranteed. Supplied-context provenance is not per-claim verification. Source APIs trust Python callers, runtime clocks refresh on restart, unlogged direct facts do not replay, log hashing grows with file size, and multi-event transactions/unlimited uptime are not guaranteed. Existing manual experiment result modifications and diagnostics were preserved outside this commit.

Run from checkout:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\diagnose.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\diagnose.ps1 -ModelSmoke
.\.venv\Scripts\python.exe .\scripts\start.py
```

`hardening-results.json` records hashes of the tested source, tests, scripts and README. Full unit/behavior and real-model observations accompany this report. Frozen Core state.py is archived without changing its historical hash.

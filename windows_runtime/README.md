# Breaktail: current runtime

The one supported runtime is `current/`, backed by `data/` and observed through
`breaktail_studio/`. It uses the BASE Ollama model `qwen2.5:14b`. No Phase8
adapter is enabled or loaded by the supported start path.

## Start and stop

From PowerShell or Explorer, run `START_ALL.cmd`. It starts the loopback-only
services only when their ports are free, and never replaces a process already
listening on those ports.

- Web conversation: <http://127.0.0.1:8765/>
- Studio: <http://127.0.0.1:8778/>
- Stop only services launched by this start script: `STOP_ALL.cmd`

`STOP_ALL.cmd` checks the saved PID and command line before it stops anything;
it does not kill an unknown process just because it owns a port.

See `project_docs/CURRENT_RUNTIME_MAP.md` for the paths, data flow, adopted
features, isolated experiments, and smoke evidence.

## Integrated CLI / daemon (2026-10-20)

`python current/breaktail_orchestrator.py chat` runs the existing conversation
core with persistent five-turn history, Raw/Memory readback, evaluation and a
reference-only review queue. `python current/breaktail_orchestrator.py daemon`
adds periodic health checks and supervised worker restart. Settings, dry-run,
safe mode, recovery and Linux instructions: `current/ORCHESTRATOR.md`.
`current/start_cli.ps1` uses this integrated CLI. Web/Studio keep their existing
entry points; no model training or adapter promotion is automatic.

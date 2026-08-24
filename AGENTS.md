# AGENTS.md: icloud-tagger

Front door for any agent working in this repo, Claude Code or otherwise.

> **This is an auto-generated stub, not a written lead file.** It points at what exists; it does not describe the project's mission, voice, or architecture, because nobody has written that down here yet. Replace it with a real lead file when this repo gets serious attention. `~/DEV/icf-astro/AGENTS.md` is the reference for what a good one looks like.

## Read these first, in this order

| File | What it holds |
|---|---|
| [PROJECT-BRIEF.md](PROJECT-BRIEF.md) | goals, status, work log, constraints |
| [README.md](README.md) | whatever the repo documents about itself |

## Machine-wide context (same facts for every model)

| Need | Where |
|---|---|
| Every skill and agent available on this Mac, one line each | `~/DEV/shared/CAPABILITY-INDEX.md` |
| Ask which one fits a task | `python3 ~/.claude/scripts/router/capabilities.py --find "<task>"` |
| What services/keys/DNS exist and whether they are actually wired | `~/DEV/shared/SYSTEM-INDEX.md` |
| All projects, with Hebrew/English aliases | `~/.claude/project-registry.json` |
| Past failures, searchable before debugging | `python3 ~/.claude/scripts/incidents/incident.py search "<symptom>"` |
| Cross-machine task state (Omac, PC, Ollama) | `python3 ~/.claude/scripts/delegation/status.py` |

## Two rules that hold in every repo here

1. **Never put a secret value in a tool argument.** Write it to `~/DEV/_inbox/<project>/`, then `sed` it into place from there. A PreToolUse hook enforces this and will block the call.
2. **Incoming files go to `~/DEV/_inbox/<project>/`,** never inside the repo. Anything dropped in the repo gets committed and deployed.

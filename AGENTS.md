# AGENTS.md: icloud-tagger

Front door for any agent working in this repo, Claude Code or otherwise.

> **This is an auto-generated stub, not a written lead file.** It points at what exists; it does not describe the project's mission, voice, or architecture, because nobody has written that down here yet. Replace it with a real lead file when this repo gets serious attention. `~/DEV/icf-astro/AGENTS.md` is the reference for what a good one looks like.

## Read these first, in this order

| File | What it holds |
|---|---|
| [PROJECT-BRIEF.md](PROJECT-BRIEF.md) | goals, status, work log, constraints |
| [README.md](README.md) | whatever the repo documents about itself |

## The rules are machine-wide, and they live in one place

Do not reconstruct them from this file. Read the canon:

| File | What it holds |
|---|---|
| `~/DEV/shared/HOUSE-RULES.md` | the procedures that bind every model here. **Read first.** |
| `~/DEV/shared/LAUNCHER.md` | how to find and run anything, one command shape |
| `~/DEV/shared/MACHINES.md` | the three machines, pools, cost, how to dispatch |
| `~/DEV/shared/VAULT-GUIDE.md` | the two Obsidian vaults, folder map, note rules |
| `~/DEV/AGENTS.md` | the root front door, same map, fuller |

```
~/DEV/shared/bin/run.sh rules                what binds you here
~/DEV/shared/bin/run.sh context icloud-tagger         goal, status, last 5 actions, open bugs
~/DEV/shared/bin/run.sh find "<your task>"    which skill or agent already does this
```

The three that bite hardest if you skip the canon: **never `rm`** (`mv` to `~/.Trash/`), **never put a secret value in a command or an edit** (read it from `~/DEV/_inbox/<project>/` and `sed` it in), and **incoming files go to `~/DEV/_inbox/<project>/`**, never inside the repo, because anything dropped in the repo gets committed and deployed.

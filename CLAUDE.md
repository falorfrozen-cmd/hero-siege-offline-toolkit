# CLAUDE.md

**Read [`agents.md`](agents.md) before doing anything in this repository.** It is
the authoritative guide for this toolkit and it is not loaded automatically —
this file exists only to point at it, so keep the rules there, not here.

Then, before working inside any submodule or directory, read that module's own
guide:

- Index: [`docs/submodules/README.md`](docs/submodules/README.md)
- Per module: `docs/submodules/<submodule-name>/instructions.md`

A module guide is not optional background. It carries the workflow, the test
commands, the packaging guardrails and the release-notes rules for that module,
and several of them require steps that no amount of reading the code reveals —
e.g. ForgePact treats a player-visible change with no `release-notes-vX.Y.Z.md`
file as an incomplete change.

## Why this file exists

On 2026-09-14 an agent fixed two ForgePact bugs, opened both pull requests, and
only then discovered `agents.md` — so the change shipped for review with no
documentation updates, against that file's own "Documentation & Instructions
Maintenance" rule, and without consulting
`docs/submodules/ForgePact/instructions.md` at all. Nothing pointed at either
document from a path the tooling reads by default. Now something does.

## The short version

- `agents.md` → repository-wide rules. Start there, every time.
- `docs/submodules/<name>/instructions.md` → the module you are about to touch.
- Updating docs is part of finishing a change, not a follow-up task.
- Never commit decompiled or disassembled game source — see the hard rule in
  `agents.md`, which governs tracked files, commit messages, and PR text alike.

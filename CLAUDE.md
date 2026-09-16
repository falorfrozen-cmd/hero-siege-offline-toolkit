@AGENTS.md

# CLAUDE.md

The line above imports [`AGENTS.md`](AGENTS.md), which holds this repository's
actual rules. Claude Code loads `CLAUDE.md` automatically; nearly every other
coding agent reads `AGENTS.md`. Keeping the rules in one file and importing them
here means there is never a second copy to drift.

**Do not add rules to this file.** They belong in `AGENTS.md`, where every agent
will see them.

## Before touching a submodule

`AGENTS.md` § "Submodule & Directory Development Instructions" sends you to that
module's own guide, and it is not optional background:

- Index: [`docs/submodules/README.md`](docs/submodules/README.md)
- Per module: `docs/submodules/<submodule-name>/instructions.md`

Those guides carry the workflow, test commands, packaging guardrails and release
rules for each module — several of which no amount of reading the code reveals.
ForgePact, for instance, expects a player-visible change to carry its
`release-notes-vX.Y.Z.md` in the same PR, because its tag workflow composes the
draft release body from those files.

Each submodule also carries its own `AGENTS.md` and `CLAUDE.md` pointing back
here, since a submodule checkout is a separate repository and does not inherit
this one.

## Why this file exists

On 2026-09-14 an agent fixed two ForgePact bugs, opened both pull requests, and
only then found `AGENTS.md` — so the change went up for review with no
documentation updates, against that file's own "Documentation & Instructions
Maintenance" rule, and without ever reading
`docs/submodules/ForgePact/instructions.md`. Nothing pointed at either document
from a path the tooling loads by default. Now something does.

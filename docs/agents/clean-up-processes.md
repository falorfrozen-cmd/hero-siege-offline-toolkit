Story and evidence behind `AGENTS.md` § ["Clean Up the Processes You Started Before Ending a Reply"](../../AGENTS.md#clean-up-the-processes-you-started-before-ending-a-reply).

## Why this matters over a long day

A session in this repository routinely starts real processes: `npm start` in
`hub/` for the section above (a Tauri debug build plus its MCP bridge), `cargo`,
`npx -y -p @hypothesi/tauri-mcp-cli tauri-mcp driver-session start`, a
`run_in_background` shell, a `Monitor` task, a test or game launch. Left
running past the reply that started them, these are exactly how a machine's
memory fills up over a long day — one process at a time, none of them
individually alarming.

## What the leftover-process hook does and does not do

`.claude/hooks/leftover_processes.py` backs this up: a `Stop` hook reports
whatever it can attribute to this session's own tool calls and is still alive
when a reply ends, once per process. It never kills anything — reporting is
all it does. A quiet hook is "not observed", not proof that nothing leaked; it
can only see what its own ledger recorded, so the rule above is still yours to
follow, not something to wait for the hook to catch. When it cannot track a
session at all — no `claude.exe` ancestor, or unreadable hook settings — it
says so with a visible warning instead of staying silently blind.

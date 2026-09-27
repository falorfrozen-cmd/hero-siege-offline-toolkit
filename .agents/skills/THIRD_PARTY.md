# Vendored third-party skills

These skill directories are copied unmodified from
[`emilkowalski/skill`](https://github.com/emilkowalski/skill) at commit
`85e8e2363b713506e1d5b6e07a0eb2da66be1bc3`, under the MIT license kept beside
them in [`LICENSE.emilkowalski-skill`](LICENSE.emilkowalski-skill):

`animate`, `animation-vocabulary`, `apple-design`,
`ask-sonner`, `emil-design-eng`, `find-animation-opportunities`,
`improve-animations`, `mobile-native`, `pick-ui-library`, `prototype`,
`review-animations`

`animate-expo` and `write-swift` (React Native and Swift) are left out, as
this repository has neither.

They are vendored rather than installed per machine so every contributor's
agent works from the same frontend and motion guidance. Do not edit them in
place: to update, copy the new upstream `skills/<name>/` over the old one and
change the commit above, then run `py -3 tools/sync_agent_tooling.py`, which
mirrors this directory into `.claude/skills/` for Claude Code and adds an
`agents/openai.yaml` (Codex's "explicit invocation only") to each skill whose
frontmatter sets `disable-model-invocation: true`. Those generated files are
the only additions; the upstream files stay unmodified. Everything else in
`skills/` is this repository's own.

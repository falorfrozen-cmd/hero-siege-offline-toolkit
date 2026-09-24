# `stash_tab_counts.py` — the shared stash's special tabs, counted from the save

`tools/stash_tab_counts.py` reads the shared stash file and prints what its two
special tabs hold: the **Socketable** tab (`socket_tab`, and any `socket_tab_<n>`)
and the **Materials** tab (`material_tab`, `material_tab_<n>`). It exists for
ForgePact issue #14 (crafting at the game's Crafting Cube from those tabs): the
research build's `craftprobe node` reader sums what it finds inside the running
game, and a reader's sum is only worth something once it has been compared with
a count taken another way. The eye is one way; this tool is the other.

Nothing here ships to a player. It is a stdlib script under `tools/`, the way
`freeze_probe.ps1` and `source_index.py` are, and ForgePact's plugin never runs
or imports it.

## What it reads

`%LOCALAPPDATA%\Hero_Siege\hs2saves\stash.hss` — or `--path <file>`, for a
backup. The directory is resolved the way `tools/hs_drive_mcp/saves.py`'s
`save_dir()` resolves it, so `HS_DRIVE_SAVE_DIR` overrides it there too.

The file is decoded by **hero-siege-item-editor's own decoder**
(`hs_item_editor_gui.decode_hss`), imported from that submodule. The codec and
its key live in the item editor and are never copied here, so a change to the
format is fixed once, there. If the submodule is not initialized, the tool says
so and names the command that initializes it:

```powershell
py -3 .claude/skills/workorder/ensure_submodule.py hero-siege-item-editor
```

The decoded document is JSON. Each tab key maps item keys (`0-0-<n>-<class>`) to
entries whose `data` holds the item: `data.b` is the base item id and `data.o`
the stack count, a missing `o` meaning a single item (the editor's own
`native_stack_count`, which the tool also imports).

## What it prints

For every special tab present, the number of entries and, per (class, b), the
summed stack and how many entries made it up. The class is the item key's
trailing number and b is `data.b`:

```text
stash_tab_counts: C:\Users\...\hs2saves\stash.hss (read-only; the last saved state - run it with the game closed)
material_tab: entries=0
socket_tab: entries=84
  class=15 b=1 stack=212 entries=1
  class=15 b=2 stack=215 entries=1
  ...
```

A special tab absent from the document prints `<tab>: not in the document`. An
entry without `data.b`, or with an `o` that is not a positive whole stack, is
listed as `skipped` with the reason instead of being dropped silently. `--json`
prints the same as one JSON object (`{"path": ..., "tabs": {"socket_tab":
{"entries": ..., "stacks": [{"class", "b", "stack", "entries"}], "skipped":
[...]}}}`) for a session to read mechanically.

## What it never does

- **It never writes.** The file is opened for reading only, by the editor's
  decoder; nothing in the tool writes a file of any kind.
- **It never counts an ordinary tab.** `stash_tab_<n>`, `unique_items`, the
  personal stash and `stash_tab_data` are skipped by the tab-key pattern.
- **It never reads a live stash.** The game owns `stash.hss` while it runs and
  rewrites it on exit. The answer is the last saved state, so run the tool with
  the game closed, or read a running session's result as "before this session".
- **It never guesses on a bad file.** A missing, undecodable or non-JSON file
  exits with status 2 and one line naming the file and the failure.

## Its two controls

1. **The fixture round trip** (`tests/test_stash_tab_counts.py`). A document
   encoded with the item editor's own encoder carries a Socketable stack pair of
   one (class 15, b 2) — 200 and 14 — a Materials entry without `o`, and an
   ordinary `stash_tab_1` stack of the *same* (15, 2). The tool must answer 214
   and 1; 264 would mean it counted the ordinary tab (the negative control). Two
   more cases pin that it never writes: a corrupt file exits non-zero and is left
   byte-identical, and every open of the save is read-only — checked by a
   recorder that is first shown to catch a write-mode open, so a clean result is
   the tool and not a blind recorder.

   ```powershell
   py -3 -m unittest tests.test_stash_tab_counts -v
   ```

   The tests skip, with the reason, only when `hero-siege-item-editor` is not
   initialized in the checkout.

2. **The live comparison** (ForgePact `docs/crafting-materials-research.md`,
   `### Live procedure 1b`). Before the session, the tool's Socketable line for
   the stack the owner will move is compared with the count seen in the tab by
   eye (`counts-tool-before`); inside the game, `craftprobe node stash` must
   print the same per-(class, b) sum; after the game has exited, the tool's sum
   must equal the count the owner stated last (`counts-tool-after`). Only when
   all three agree does a reader's sum count as the tab's contents.

## Observed

2026-09-22, read-only against the owner's current save: the document decoded,
and `socket_tab` held 84 entries (all class 15); `material_tab` held 0 entries
in that saved state. This matters for the live session, which needs a material
stack in the Materials tab: the owner puts one there first.

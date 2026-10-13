# `save_item_keys.py` — every item key in a save, by the container it sits in

`tools/save_item_keys.py` reads one or more Hero Siege save files and prints
every item key (`0-0-<n>-<class>`) it finds, grouped by the container the key is
saved under. It exists for ForgePact issue #68 ("Move all" from the bag into the
stash): after a live session the research and acceptance procedures have to show
that a moved item is saved under a stash container, under no bag container, and
exactly once. The in-game reads (`menulayout`, `craftprobe node`) say where an
item sits while the game runs; this says where the game saved it.

Nothing here ships to a player. It is a stdlib script under `tools/`, beside
[`stash_tab_counts.py`](stash-tab-counts.md), and ForgePact's plugin never runs
or imports it.

## What it reads

Any `.hss` file given on the command line. The files are decoded by
**hero-siege-item-editor's own decoder** (`hs_item_editor_gui.decode_hss`),
imported from that submodule and never copied, as `stash_tab_counts.py` does. If
the submodule is not initialized, the tool says so and names the command:

```powershell
py -3 .claude/skills/workorder/ensure_submodule.py hero-siege-item-editor
```

An item can be saved in three files, and they are laid out differently (read on
the owner's saves, 2026-09-28):

| File | Layout | Containers that hold items |
|---|---|---|
| `stash.hss` | one JSON object | `stash_tab_1` .. `stash_tab_<n>` (the shared tabs), `material_tab`, `socket_tab`, `unique_items` |
| `inventory_order_<slot>.hss` | one JSON object | the bag: `inventory_tab_0` .. `inventory_tab_4` (its pages), `inventory_material_tab`, `inventory_socket_tab`, `inventory_key_tab`, `inventory_relic_tab`, `inventory_tarot_tab`, `inventory_charms`, `inventory_vault_*` |
| `herosiege<slot>.hss` | `key="value"` lines; some values are base64 of a JSON object | `inventory.personal_stash` (the personal stash tab), `inventory.equipped_items`, `inventory.potions`, `inventory.minion_inventory_*`, and single-item fields such as `item_2` |

`<slot>` is the file's own number, one less than the slot the game shows (slot
14 is `herosiege13.hss` and `inventory_order_13.hss`). The bag is **not** in the
character file: a check that an item left the bag has to read
`inventory_order_<slot>.hss`.

A container is the dotted path to the JSON object that holds the keys; for a
character file the path starts with the field's name. Only object keys are
listed. A key that appears as a string value somewhere (a reference, not an
entry) is not.

## What it prints

For each file, a header line and then each container with its key count and
keys:

```text
save_item_keys: C:\...\hs2saves\stash.hss (read-only; the last saved state - run it with the game closed)
material_tab: keys=69
  0-0-...-14
stash_tab_1: keys=62
  ...
```

`--key <key>` (repeatable) prints only those keys, and ends with one line per
key naming every `file:container` it was found in, or `not in any file read`.
A key named twice is saved twice, which is what a duplicate check looks for.
`--json` prints the same as one object: `{"files": {<path>: {<container>:
[keys]}}, "keys": {<key>: [{"file", "container"}]}}` (the `keys` part only
with `--key`).

### Each key's definition: `--defs`

`--defs` prints, beside each listed key, four fields of the saved entry's
definition (its `data` object): `a` (the seed), `b` (the base), `c` (the
repository: `0.0` normal, `1.0` unique) and `o` (the stack count, or a relic's
level). Each is spelled **exactly as the decoded file writes it**: numbers are
kept as their own text and never parsed, so a `b` saved as `2.10` prints `2.10`
(a parsed float would print `2.1`) and a `c` saved as `0.0` prints `0.0`. A
field the entry does not carry prints `-`. It works with `--key`, and in every
file layout, the character file's base64 fields included.

```text
PS> py -3 tools/save_item_keys.py "$env:LOCALAPPDATA\Hero_Siege\hs2saves\inventory_order_13.hss" --defs
save_item_keys: C:\...\hs2saves\inventory_order_13.hss (read-only; the last saved state - run it with the game closed)
inventory_key_tab: keys=35
  0-0-197573647678-12  a=352809214 b=0 c=0.0 o=964
  0-0-200921386013-12  a=3020021 b=30 c=0.0 o=84
  ...
```

With `--json` the same fields come as strings under `"defs": {<path>:
{<container>: {<key>: {"a", "b", "c", "o"}}}}`, narrowed by `--key` as the
text is, beside the unchanged `files` (and `keys`) parts. Without `--defs` the output, text or JSON, is byte for byte
what it was before the flag existed.

**Why it exists.** ForgePact #197 builds a boss soul piece on a key whose
definition `b` carries a fraction (for example the key's base plus a tenth),
so that the game's own stack check, which compares `b`, keeps pieces apart from
the real key and from each other. Whether the game writes a saved real through
its `string()` conversion, keeping two decimals, is an open hypothesis
(`soul_piece_model.HYPOTHESES['string_keeps_two_decimals']`; a saved whole `c`
reads `0.0`, neither `0` nor `0.00`), so whether the fraction survives a save
is a question about what the save file says. `--defs` answers
it from the file, after the session, without the game running.

## What it never does

- **It never writes.** The files are opened for reading only, by the editor's
  decoder.
- **It never reads a live game.** The game owns these files while it runs and
  rewrites them on exit, so run it with the game closed and read the answer as
  the last saved state.
- **It never guesses on a bad file.** A missing or undecodable file, a file that
  holds neither JSON nor a base64 JSON field, or a `--key` that is not an item
  key exits with status 2 and one line.

## Its two controls

1. **The fixture round trip** (`tests/test_save_item_keys.py`). Three synthetic
   documents, encoded with the item editor's own encoder, in the three layouts
   above. The target: every key under its container, the personal stash inside
   the character file included, and `--key` naming each place a key is saved
   (a key saved in the stash and in the bag is named twice). The baseline, a
   negative control: a key held only as a string value, the character file's
   plain fields and its one base64 field that is not JSON are never listed. A
   fourth fixture, a bag file's Key tab written as raw text with a `b` of `2.10`,
   covers `--defs`: the baseline pins the plain text and JSON output line for
   line, unchanged by the flag's existence, and the target reads `b=2.10`,
   `c=0.0` and `-` for a missing field, in text and in JSON. Two
   more cases pin that it never writes: a corrupt or missing file exits
   non-zero and is left as it was, and every open of a save is read-only,
   checked by a recorder first shown to catch a write-mode open.

   ```powershell
   py -3 -m unittest tests.test_save_item_keys -v
   ```

   The tests skip, with the reason, only when `hero-siege-item-editor` is not
   initialized in the checkout.

2. **A known save.** Run over the copy taken before ForgePact #68's first live
   session (slot 14), it placed each key that session read in game where the
   game showed it: the bag items read in the bag grid under
   `inventory_order_13.hss`'s `inventory_tab_0`, the material read in the bag's
   Materials sub-tab under `inventory_material_tab`, and the personal-tab stash
   item under `herosiege13.hss`'s `inventory.personal_stash`.

## Observed

2026-09-28, read-only, against that copy: `stash.hss` held `material_tab` (69
keys), `socket_tab` (91), `stash_tab_1` to `stash_tab_7` and `unique_items`
(670); `inventory_order_13.hss` held the bag's `inventory_tab_0` (7 keys) and
its sub-tabs; `herosiege13.hss` held `inventory.personal_stash` (4 keys),
`inventory.equipped_items` (15), `inventory.potions` (4),
`inventory.minion_inventory_melee` (7) and one key in `item_2`. So on this save
the personal stash tab is saved with the character, and the shared tabs in
`stash.hss`.

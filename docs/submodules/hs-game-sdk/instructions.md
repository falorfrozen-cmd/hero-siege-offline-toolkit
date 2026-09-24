# HS Game SDK Module Development Instructions

## Module Overview & Metadata

`hs-game-sdk` is the centralized, multi-language SDK and metadata library providing GameMaker objects, scripts, assets, stat IDs, and runtime struct definitions extracted directly from `Hero_Siege.exe` and `data.win`.

It serves as the unified source of truth for:
* **C++ plugins** (`ForgePact/plugin`, `HS-Offline-Tracker/aurie-producer`, `hs-stat-forge`)
* **Python tools** (`hero-siege-item-editor`, `HSSaveEditor`, `HS-Offline-Launcher`)
* **TypeScript / Web interfaces** (`HSCraftSim`, `HS-Offline-Tracker/src`)

| Item | Value |
| --- | --- |
| **Directory** | `hs-game-sdk/` |
| **Languages** | Python 3.10+, C++20, TypeScript / JavaScript |
| **Output Formats** | Python package (`hs_game_sdk`), C++ headers (`include/hs_game_sdk/`), TypeScript package (`@hero-siege/sdk`), JSON dumps |
| **Supported Game Build** | Hero Siege Season 10 (Steam / Offline) |

---

## Architecture & Directory Map

```text
hs-game-sdk/
├── data/                       # Extracted JSON databases (ignored by git for clean distribution)
│   ├── manifest.json           # Binary metadata and hashes
│   ├── objects.json            # 6,016 GameMaker Object definitions, indexes, parent hierarchy
│   ├── scripts.json            # 6,254 GML Script names and asset indexes
│   ├── sprites.json            # 32,270 Sprite indexes and names
│   ├── rooms.json              # 306 Room indexes and names
│   └── sounds.json             # 2,718 Sound indexes and names
├── curated/                    # Hand-verified game knowledge (NOT gitignored - tracked)
│   ├── satanic_zone.json       # Satanic Zone buff/debuff ids/names/descriptions + Controller_obj var names
│   ├── drop_types.json         # LoadDrops drop types + GetNormalRepoStruct repository categories (data only)
│   ├── special_content.json    # global.eSt slot -> stat -> content map + Spawn_*_obj markers (data only)
│   └── stash_containers.json   # Stash map/special-tab Controller_obj var names (ForgePact #14, data-only, no generator)
├── python/                     # Python SDK package
│   ├── hs_game_sdk/
│   │   ├── objects.py          # GameObject enum & index maps
│   │   ├── scripts.py          # GameScript enum & index maps
│   │   ├── rooms.py            # GameRoom enum & index maps
│   │   ├── sprites.py          # GameSprite enum & index maps
│   │   ├── sounds.py           # GameSound enum & index maps
│   │   ├── stats.py            # StatId enum, proc bundles (116/117/118), buff IDs (332)
│   │   ├── structs.py          # Dataclasses: ItemDefinitionStruct, ItemStatStruct, etc.
│   │   ├── player.py           # EquipmentSlot enums, PlayerEquipment, container scanners
│   │   ├── item_type.py        # ItemType IntEnum: the item instance's itemType class (hand-written)
│   │   ├── mod_registry.py     # ModDefinition & ModRegistry for declarative mods
│   │   └── satanic_zone.py     # SATANIC_BUFFS/SATANIC_DEBUFFS tuples, generated from curated/satanic_zone.json
│   ├── pyproject.toml
│   └── setup.py
├── cpp/                        # C++ Header SDK for YYToolkit / Aurie Plugins
│   └── include/hs_game_sdk/
│       ├── objects.hpp         # enum class GameObject & GetObjectName()
│       ├── scripts.hpp         # constexpr string_view script names & indexes
│       ├── rooms.hpp           # enum class GameRoom
│       ├── stats.hpp           # Stat constants & proc families
│       ├── yytk_helpers.hpp    # Typed helper wrappers for YYTKInterface
│       ├── hooks.hpp           # InstallScriptHook: table swap + inline detour, repeat-safe
│       ├── player.hpp          # Player discovery; relic scanners (positive ID only)
│       ├── item_type.hpp       # HeroSiege::Items::ItemType + enumerable kItemTypes (hand-written, no YYToolkit)
│       ├── satanic_zone.hpp    # HeroSiege::SatanicZone::kBuffs/kDebuffs, generated from curated/satanic_zone.json
│       └── hs_game_sdk.hpp     # Main aggregate header
├── ts/                         # TypeScript / ESM SDK for web and UI modules
│   ├── src/
│   │   ├── objects.ts
│   │   ├── scripts.ts
│   │   ├── rooms.ts
│   │   ├── stats.ts
│   │   ├── player.ts
│   │   ├── item_type.ts        # ItemType enum + enumerable ITEM_TYPES (hand-written)
│   │   ├── satanic_zone.ts     # SATANIC_BUFFS/SATANIC_DEBUFFS, generated from curated/satanic_zone.json
│   │   └── index.ts
│   └── package.json
└── (Configured via repository root .gitignore & README.md)
```

**`data/` vs `curated/`:** `data/` is mechanically extracted straight from `Hero_Siege.exe`/`data.win`
by `tools/extract_and_generate_sdk.py` and is gitignored (see Safety section below) - it never leaves
a contributor's machine. `curated/` is hand-verified game knowledge that no extractor can derive (item
names/effect text that requires playing the game and cross-checking, not just walking a symbol table)
and IS tracked in git, generated into the same three language targets by a small sibling script,
`tools/generate_satanic_zone_sdk.py` (run it after editing a `curated/*.json` file; it is not part of
`extract_and_generate_sdk.py`'s pipeline since it has nothing to extract from a binary). `curated/`
is the pattern to extend for any future hand-verified, non-mechanically-extracted domain knowledge a
submodule needs to share - see `ForgePact/docs/satanic-zone-mods-research.md` for how `satanic_zone.json`
came to exist. Not every `curated/*.json` file is generated into bindings: `drop_types.json` and
`special_content.json` (2026-09-24) are data only, read as JSON, with no `tools/generate_*_sdk.py`
counterpart; each file's `$schema_note` says so, and `docs/RUNTIME_DATA_MODELS.md` §13-§14 carries
the prose and sources. `tests/test_sdk_all.py` checks every script and object they name is bound.
`stash_containers.json` (ForgePact issue #14's stash and Crafting Cube container names, see
`docs/RUNTIME_DATA_MODELS.md` § 16) is data-only too, with no generator and no consumer yet, checked
against the SDK and that doc section by `tests/test_curated_stash_containers.py`.

---

## OBJT Record Layout & the Object Parent Hierarchy

`objects.json` is extracted by walking the `OBJT` chunk's pointer list. This build's
runtime inserts a `managed` flag right after `visible`, which pushes every later field
4 bytes further than the pre-2022.5 layout most references describe. Offsets relative
to an object's record pointer, as measured against `data.win`
(`2fc37b1b…`, GEN8 bytecode version 17, `UILR`/`PSEM`/`PSYS`/`FEAT` chunks present).
**Reverified against `07D864C91EFE…` on 2026-09-17** (hub `4539e68`,
`hs-game-sdk/data/manifest.json` records the full hash): the game had been
patched, the extractor ran with this layout unchanged, a second run produced no
diff, it still yields 6,016 object records, and the regenerated closure names
matched the method values read off live instances in ForgePact's prospect window
session (`anon@1065/2806/3657@gml_Object_UI_Prospect_obj_Create_0`). That is a
check of the extractor's output, not a field-by-field re-measurement of every
anchor below. The patch renumbered every closure (`anon@N`) and shifted sprite and
mask indices, so code that spells a closure name as a literal goes stale with each
game update (see the ForgePact guide's Maintenance Triggers):

| Offset | Field | Notes |
| --- | --- | --- |
| `+0` | name | string pointer |
| `+4` | `sprite_index` | `-1` = no sprite |
| `+8` | `visible` | bool32 |
| `+12` | `managed` | bool32 — **the inserted field**; `true` for all 6,016 objects |
| `+16` | `solid` | bool32 |
| `+20` | `depth` | i32 — `0` for every object in this build (depth is layer-driven) |
| `+24` | `persistent` | bool32 |
| `+28` | `parent_index` | i32 **object** index, `-100` = root object |
| `+32` | `mask_index` | i32 **sprite** index, `-1` = collide using `sprite_index` |
| `+36` | `uses_physics` | bool32, followed by the physics block and the 15 event lists |

Anchors that pin this layout, in case it has to be re-derived for a future game build:

* `+48`/`+52`/`+64`/`+72` hold the GameMaker physics defaults `0.5`, `0.1`, `0.1`, `0.2`.
* Parsing the tail from `+68` (physics vertex count) yields exactly 15 event lists whose
  pointers are in-chunk and ascending for all 6,016 records, and no record's parsed end
  overruns the next record's start.
* `+28` is never anything but `-100` or a valid object index, and grouping by it produces
  the families the names imply (`Collision_Prop_obj` 1,495 children, `Visual_Parent_obj` 960,
  `Player_Damage_Parent_obj` 582, …), with 840 roots and no cycles.
* `+32` reaches past the object table into the sprite table and resolves to the game's own
  mask sprites (`Abandoned_Mine_Entrance_obj` → `Abandoned_Mine_Mask_spr`).

`tests/test_object_hierarchy.py` asserts all of the above, including the three-level chain
`Quest_Act_01_Coffee_Beans_obj → Quest_Object_Parent_obj → Pickup_Parent_obj`. Before
2026-09-10 the extractor used the unshifted offsets, so `parent_index` carried the
`persistent` flag (`0`/`1` only) and `mask_index` carried the parent index; any consumer
written against a `data/objects.json` from before that date needs regenerating.

### Hierarchy lookups in the bindings

All three targets expose the parent/mask tables plus lookup helpers, so a hook can ask
"is this instance an enemy?" instead of enumerating indices (the GML `object_is_ancestor`
relation):

```python
from hs_game_sdk import get_parent_index, get_child_indices, is_descendant_of

is_descendant_of("Quest_Act_01_Coffee_Beans_obj", "Pickup_Parent_obj")  # True
len(get_child_indices("Collision_Prop_obj"))                            # 1495
```

```cpp
using namespace HeroSiege::Objects;
static_assert(IsDescendantOf(GameObject::Quest_Act_01_Coffee_Beans_obj,
                             GameObject::Pickup_Parent_obj));
std::vector<int32_t> props = GetChildObjects(static_cast<int32_t>(GameObject::Collision_Prop_obj));
```

```typescript
import { GameObject, isDescendantOf, getChildObjects } from '@hero-siege/sdk';
```

Python: `OBJECT_PARENT_INDEX`, `OBJECT_MASK_SPRITE_INDEX`, `NO_PARENT`, `NO_MASK`,
`get_parent_index`, `get_ancestor_indices`, `get_child_indices`, `get_descendant_indices`,
`is_descendant_of`, `get_mask_sprite_index`. C++: `kObjectParents`, `kObjectMasks`,
`kNoParent`, `kNoMask`, `GetParentObject`, `GetMaskSpriteIndex`, `IsDescendantOf`,
`GetChildObjects`, `GetDescendantObjects` (the first three are `constexpr`, so ancestry
checks can be `static_assert`ed). TypeScript mirrors the Python names in camelCase.

---

## Item class: `ItemType`

`ItemType` names the value an item **instance** carries in its `itemType` field — the
field ForgePact already reads off live item structs, and the one `s_ItemInstanceStruct`
carries alongside its definition, info and stat structs (`HSCraftSim/RESEARCH.md` § 2).
It does **not** describe the item *definition* struct's `c` field: HSCraftSim treats `c`
as a 0/1 unique flag, and `docs/RUNTIME_DATA_MODELS.md` labels it a rarity tier. Do not
match `ItemType` against `c`.

| Binding | Enum | Enumerable companion |
| --- | --- | --- |
| Python | `from hs_game_sdk import ItemType` (`IntEnum`, UPPER_SNAKE) | iterate the enum |
| C++ | `HeroSiege::Items::ItemType` (`enum class : int32_t`, PascalCase) in `<hs_game_sdk/item_type.hpp>` | `HeroSiege::Items::kItemTypes` — `(std::string_view name, ItemType)` pairs |
| TypeScript | `ItemType` (`export enum`, PascalCase) from `@hero-siege/sdk` | `ITEM_TYPES` — readonly `{ name, value }` array |

`item_type.hpp` is self-contained (standard headers only, no YYToolkit), so any plugin can
include it on its own; `hs_game_sdk.hpp` pulls it in too.

| Value | Python | C++ / TS | Source |
| --- | --- | --- | --- |
| 0 | `HELMET` | `Helmet` | R |
| 1 | `BODY` | `Body` | R |
| 2 | `BOOTS` | `Boots` | R |
| 3 | `WEAPON` | `Weapon` | R |
| 4 | `GLOVES` | `Gloves` | R |
| 5 | `AMULET` | `Amulet` | R |
| 6 | `SHIELD` | `Shield` | R (`RUNTIME_DATA_MODELS.md` gives 6 a different label on `c`) |
| 7 | `RING` | `Ring` | R |
| 8 | `BELT` | `Belt` | R (`RUNTIME_DATA_MODELS.md` gives 8 a different label on `c`) |
| 10 | `CHARM` | `Charm` | R (`RUNTIME_DATA_MODELS.md` gives 10 a different label on `c`) |
| 11 | `CONSUMABLE` | `Consumable` | R + V (catalog row `(11, 23)` Infernal Codex) |
| 12 | `KEY` | `Key` | R + V (`(12, 8)` Angelic Key) + D (repository category 12 = keys) |
| 13 | `TAROT` | `Tarot` | R + V (`(13, 24)` The Wheel of Fortune) |
| 14 | `MATERIAL` | `Material` | R + V (`(14, 69)` Infernal Codex Page) + M (measured in-game 2026-09-19) |
| 15 | `SOCKETABLE` | `Socketable` | R + V (`(15, 82)` Exan Jewel) — runes, gems and jewels |
| 16 | `RELIC` | `Relic` | R + S (`RELIC_RARITY_TIER` / `kRelicRarityTier`, matched against `itemType`) + D (repository category 16 = relics) |
| 18 | `POTION` | `Potion` | R |
| 19 | `OTHER` | `Other` | R |

Sources:
- **R** — `HSCraftSim/RESEARCH.md` § 2, the "Item types (= catalog `cls`)" list, which names
  all 18 values.
- **V** — the same paragraph's "Verified" list: `(itemType, itemId)` pairs cross-checked
  against Item Editor catalog rows `(cls, b)`. HSCraftSim's `data/README.md` documents the
  catalog's `cls` column as the crafting `itemType`.
- **S** — already in this SDK: the relic contract in `player.py` / `player.hpp` identifies a
  relic by tier 16 read from `itemType` among other fields. `tests/test_item_type_parity.py`
  asserts `ItemType.RELIC == RELIC_RARITY_TIER`; the relic contract itself is unchanged.
- **D** — `docs/RUNTIME_DATA_MODELS.md` § 13.2, the item repository categories that
  `GetNormalRepoStruct(category, 0, index)` answers (measured 2026-08-27; also in
  `curated/drop_types.json`). Until 2026-09-24 this row cited § 3's "Dungeon Keys `12`" /
  "Relics `16`" examples, which mixed drop types with repository categories.
- **M** — measured in-game, 2026-09-19: ForgePact research build `8c56ca7`'s
  `prospectprobe stackmove` route read `itemType` off a live item twice in the same
  session — the Prospect Cube grid cell's `nodeFingerprint` (a Mallet Fragment)
  resolved through the game's own `GetItemFromFingerprint(fp, 0)`, called by name,
  and the existing stack `InventoryGridCanAddToStack` returned for that same
  material — and both reported `itemType = 14`, matching
  `HeroSiege::Items::ItemType::Material`. One material type, this row only; see
  `ForgePact/docs/prospect-window-research.md` (Stage C, `M-identity`/`M-shapes`)
  and ForgePact issue #52.

The integers **9** and **17** appear in no source and have no member. Do not add one without
evidence. Row 14 is measured in-game (Source M above); **no other row has been read from a
live item instance on this runner yet**: every other Source above is the research note or a
catalog cross-check, not a runtime measurement. When a live read confirms another value, mark
its row "measured in-game" with the date the same way. The other values rest on the research
note above, so treat a live mismatch on one of them as a finding to record here, not a typo.

The three declarations are hand-written, not generated, and nothing derives one from another:
that is what makes `tests/test_item_type_parity.py` a real check rather than a tautology. It
parses `item_type.hpp` and `item_type.ts` as text (runs in any checkout), imports
`item_type.ts` under `node --experimental-transform-types` (skips without `node` ≥ 22.7), and checks
no binding declares 9 or 17. `tests/test_cpp_sdk.py`'s
`test_compiled_item_type_table_matches_python` compares the *compiled* `kItemTypes`, printed by
the harness as `ITEM_TYPE <Name> <value>` lines, against the Python enum. A `curated/*.json` +
generator was considered and not used: with one generated source, the parity test would compare
a file with itself, and for 18 stable constants the extra artifact costs more than the drift it
prevents — revisit if the table grows.

---

## Integration Workflow Across Submodules

### 1. Python Submodules (`hero-siege-item-editor`, `HSSaveEditor`, etc.)
Install in editable mode:
```powershell
py -3 -m pip install -e hs-game-sdk/python
```
Or import directly:
```python
from hs_game_sdk import GameObject, GameScript, StatId, PROC_FAMILIES, ItemDefinitionStruct, ItemType
```

### 2. C++ Submodules (`ForgePact/plugin`, `HS-Offline-Tracker/aurie-producer`)
Add `hs-game-sdk/cpp/include` to the include search path and include the aggregate header:
```cpp
#include <hs_game_sdk/hs_game_sdk.hpp>

using namespace HeroSiege;

void ExampleHook() {
    auto obj = Objects::GameObject::Enemy_Parent_obj;
    std::string_view script = Scripts::gml_Script_DropItem;
    auto material = Items::ItemType::Material;  // itemType 14
}
```

### 3. TypeScript Submodules (`HSCraftSim`, `HS-Offline-Tracker` UI)
Import from the module:
```typescript
import { GameObject, GameScripts, StatId, ItemType } from '@hero-siege/sdk';
```

---

## Setup, Extraction & Test Command Reference

| Command | Working Directory | Purpose | Verification Status |
| --- | --- | --- | --- |
| `py -3 tools/extract_and_generate_sdk.py --game-bin "<path-to-game-bin>"` | Workspace Root | Re-extract symbols from `data.win` and regenerate all SDK bindings | Verified 2026-09-17 (hub `4539e68`, `data.win` `07D864C91EFE…`, default game path; idempotent) |
| `py -3 tools/generate_satanic_zone_sdk.py` | Workspace Root | Regenerate `satanic_zone.py`/`.hpp`/`.ts` from `hs-game-sdk/curated/satanic_zone.json` (hand-edited, not extracted) | Verified 2026-09-10 |
| `py -3 -m unittest discover -s tests` | Workspace Root | Run the SDK test suite. Passes in a clean checkout; extraction- and compiler-dependent suites skip (see below) | Verified 2026-09-12 |
| `py -3 -m unittest tests.test_cpp_sdk -v` | Workspace Root | Compile and run the C++ relic/hook behavioural tests against the stubbed YYToolkit surface | Verified 2026-09-12 |
| `py -3 -m unittest tests.test_item_type_parity -v` | Workspace Root | Check the Python, C++ and TypeScript `ItemType` declarations match value for value, the aggregates match their generator templates, and this guide's value table claims "measured in-game" for row 14 only | Verified 2026-09-20 (14 tests OK, node v24) |
| `py -3 -m pip install -e hs-game-sdk/python` | Workspace Root | Install Python SDK in development mode | Verified |

### Which tests need a game install, and which do not

`py -3 -m unittest discover -s tests` passes from a clean checkout with no game
installed and no build tools. Anything that cannot run there **skips** rather than
fails, because `hs-game-sdk/data/` is gitignored extraction output that no
contributor can be assumed to have:

| Suite | Needs | Behaviour without it |
| --- | --- | --- |
| `test_sdk_python.py`, `test_expanded_sdk.py`, `test_relic_identification.py` | nothing | always runs |
| `test_sdk_all.py` → `TestSdkArtifacts` | nothing | always runs |
| `test_sdk_all.py` → `TestExtractedDataArtifacts` | `hs-game-sdk/data/` | skips |
| `test_object_hierarchy.py` → `TestObjectParentChain` | nothing (reads the tracked bindings) | always runs |
| `test_object_hierarchy.py` → `TestObjectsJsonMatchesBindings` | `hs-game-sdk/data/` | skips |
| `test_extractor_layout.py` | nothing (builds a synthetic `data.win`) | always runs |
| `test_cpp_sdk.py` | Windows + MSVC or g++/clang++ | skips |
| `test_item_type_parity.py` | nothing (parses the tracked bindings and this guide); `node` for the executed-TypeScript sub-test | always runs; only `test_executed_enum_matches_python` skips, when `node` is missing from `PATH` or older than 22.7 (no `--experimental-transform-types`); `TestGuideRecordsTheMeasuredRow` checks this guide's ItemType table names only row 14 as "measured in-game" |
| `test_curated_stash_containers.py` | nothing (reads the tracked `curated/stash_containers.json`, the SDK and `docs/RUNTIME_DATA_MODELS.md`) | always runs |

`test_extractor_layout.py` is how the OBJT offsets stay verifiable without the
game: it writes a tiny GameMaker IFF file by hand, with each field at its
documented offset and a distinct value, so a one-field shift fails immediately.

`test_cpp_sdk.py` compiles `tests/cpp/test_sdk_player_hooks.cpp` against the
**unchanged** production headers, with the YYToolkit and Aurie surfaces supplied
by `tests/cpp/stubs/`. Because the SDK detects YYToolkit with
`__has_include(<YYToolkit/YYTK_Shared.hpp>)`, putting the stubs on the include
path is enough to compile the real code paths and drive them with controlled
responses - no Aurie runtime, no DLL in the game, no live game.

---

## Runtime helper semantics

### `Player::GetOwnedRelicLevels` / `GetMaxedRelicIds` — relic identification

Both take the player as an **instance handle of either kind**: `VALUE_OBJECT` or
`VALUE_REF`, tested with `Player::IsInstanceHandle`. This runner produces
`VALUE_REF` (kind 15) for the local player, so the reference is the normal case —
see `docs/RUNTIME_DATA_MODELS.md` §1.

That was a real defect too (REPORTED 2026-09-14): the gate read
`player.m_Kind != VALUE_OBJECT -> return {}`, so the scan returned an empty map
for every player on this runner. An empty maxed set means "nothing to hold back",
which is indistinguishable downstream from "the player owns no maxed relics" —
so `ForgePact`'s relic filter armed, installed its hook, logged
`hook installed -> ON`, and filtered nothing, for every user, silently.

If a caller hands in something that is neither kind (an undefined value, a bare
instance id), the scan still returns empty rather than guessing: convert an id
with `GetInstanceObject` first.

An item counts as a relic only on **positive identification**: rarity tier 16 via
`c` / `cls` / `itemType`, or the relic-specific `relicLevel` field. Level is read
only from `o`, `level` and `relicLevel`.

A level-shaped field is not evidence of relic-ness, and this was a real defect
(REPORTED 2026-09-12 against PR #3): the scanner accepted `isRelic || level > 0`,
so the ordinary item `{b:15, c:8, level:100}` was reported as maxed relic 15.
`ForgePact`'s `RelicFilterMod` calls `GetMaxedRelicIds` directly, so that false
positive could suppress an unrelated relic drop. `p` is a star upgrade count and
stacks carry `amount`/`count`/`qty`, so the old field list both invented relics
and inflated levels past the maxed threshold.

Container shape matters too, via `Player::ContainerKind`:

| Kind | Containers | A bare number means |
| --- | --- | --- |
| `General` | `equippedItems`, `inventory`, `bags` | nothing - item structs only |
| `RelicTable` | `relic_levels`, `relics`, `relic_tab`, `relic_array`, `pRelics`, `relic_inventory`, `relics_collected`, `inventory_relic_tab`, `relicPage` | `relic id -> level` |

#### The contract shared with the Python SDK

Both scanners must accept exactly the same layouts. REPORTED 2026-09-12 by
origin's second review of PR #3: C++ recognised `cls` and read numeric arrays out
of `relic_levels` while Python did neither, so on identical input
`{"relic_levels":[0,0,10]}` C++ said `{2:10}` and Python said `{}`. They now
declare one contract, as enumerable constants on both sides:

| Contract | Value | C++ | Python |
| --- | --- | --- | --- |
| Id fields | `b`, `relicId` | `kRelicIdFields` | `RELIC_ID_FIELDS` |
| Rarity-tier fields (`== 16` means relic) | `c`, `cls`, `itemType` | `kRelicTierFields` | `RELIC_TIER_FIELDS` |
| Level fields (highest present wins) | `o`, `level`, `relicLevel` | `kRelicLevelFields` | `RELIC_LEVEL_FIELDS` |
| Relic-only field (presence means relic) | `relicLevel` | `kRelicOnlyField` | `RELIC_ONLY_FIELD` |
| General containers | see table above | `kGeneralContainerFields` | `GENERAL_CONTAINER_FIELDS` |
| Relic containers | see table above | `kRelicContainerFields` | `RELIC_CONTAINER_FIELDS` |
| Plausible id range | `0 .. 159` | `kRelicIdLimit` | `RELIC_ID_LIMIT` |
| Maxed at | `10` | `kMaxedRelicLevel` | `MAXED_RELIC_LEVEL` |
| Recursion budget | `5` | `kMaxScanDepth` | `MAX_SCAN_DEPTH` |
| Array read cap | `512` | `kMaxScannedArrayLength` | `MAX_SCANNED_ARRAY_LENGTH` |

They are enumerable rather than inline literals for one reason: the C++ harness
prints them and `tests/test_cpp_sdk.py` asserts the Python tuples match field for
field, so editing one side without the other fails a test instead of drifting
silently. The three reported cases are in that shared suite too, negative control
included.

**One difference is deliberate: how each side walks its input.** C++ reads named
variables off a live `CInstance` and can only follow what it looks up - the `data`
field and array elements - because YYToolkit gives it no way to enumerate a
struct's keys. Python walks every key of a decoded save-file tree. So
`{"inventory": {"bag1": [relic]}}` resolves in Python and has no C++ equivalent
to resolve. The contract above is about *which layouts are recognised*; the
traversal differs because the inputs do. There is no TypeScript scanner -
`ts/src/player.ts` only carries `EquipmentSlot` - so the contract covers exactly
these two implementations.

### `Hooks::InstallScriptHook` — both call routes, and safe to install twice

```cpp
static PFUNC_YYGMLScript g_origDropRelic = nullptr;  // static, zero-initialised

HeroSiege::Hooks::ScriptHookOptions options;
options.selfModule = g_ArSelfModule;      // required for native interception
options.hookId = "forgepact_drop_relic";  // required, unique per detour
const auto result = HeroSiege::Hooks::InstallScriptHook(
    yytk, "gml_Script_DropRelic", &Hook_DropRelic, &g_origDropRelic, options);
if (!result.IsNative()) {
    Log(std::string("table-only: ") + result.note);  // surface it, do not ignore it
}
```

A script-table swap alone catches only calls the game routes through the table;
compiled GML also calls straight into the function's address. So the installer
does **both** - the table swap and an inline detour - and `*outOriginalFunc`
becomes the trampoline, reaching the real original from either route without
re-entering the hook. See the "Prove the Instrument" rule in
[`AGENTS.md`](../../../AGENTS.md).

Check `result.kind`:

| Kind | Meaning |
| --- | --- |
| `Native` | both routes covered |
| `TableOnly` | the detour could not be installed; `note` says why, and direct compiled-GML calls bypass the hook |
| `AlreadyInstalled` | a hook was already present; the recorded original was left alone |
| `Failed` | nothing was installed |

Repeat installation is safe, which matters because a shared chokepoint gets hooked
from more than one call site. The detour is attempted only on the first install
(`!*outOriginalFunc`) - the one moment the table still holds the game's own
function - and the table entry must be executable code inside the game module, or
it is not ours to patch. Pass a **static, zero-initialised** original pointer: it
is how the installer knows which install is the first.

`InstallScriptHookTableOnly` is a deliberately limited variant, named so the
limitation is visible at the call site. It exists for research - observing
table-routed calls without patching code - and still preserves the original
across repeat installs. It is not what a shipped gameplay hook should use.

---

### Never hand-edit a generated file

`tools/extract_and_generate_sdk.py` rewrites **every** file under `python/hs_game_sdk/`,
`cpp/include/hs_game_sdk/` and `ts/src/` on each run — including the ones with no extracted
content in them (`__init__.py`, `hs_game_sdk.hpp`, `yytk_helpers.hpp`, `index.ts`), which come
from string templates inside the generator. Editing those files in place works right up until
the next extraction silently reverts them. Change the template in the generator instead, then
re-run it; regeneration is idempotent, so a second run must produce no diff.

`satanic_zone.py`/`.hpp`/`.ts` are the exception: they belong to
`tools/generate_satanic_zone_sdk.py` and are regenerated from `curated/satanic_zone.json`.

"Every file" is broader than the code, though: `player.py`/`.hpp`/`.ts`, `hooks.hpp`,
`mod_registry.py` and `item_type.py`/`.hpp`/`.ts` are hand-written, and the generator neither
writes nor deletes them. Edit those in place. They still have to be wired into the aggregates
through the templates — `init_content`, `main_header` and `index_content` all include
`item_type` now, and `tests/test_item_type_parity.py` fails if a committed aggregate stops
matching its template.

---

## Safety, Git & Intellectual Property Boundaries

* **No Game Binaries / Bytecode in Git**: Root `.gitignore` excludes `data.win`, `.exe`, `.dll`, audio groups, texture pages, and raw dump folders (`hs-game-sdk/data/`, `raw/`, `extracted/`). `hs-game-sdk/curated/` is the deliberate exception to this rule: it holds hand-verified data (not extracted bytecode/assets) and is meant to be shared, so it is tracked normally.
* **Interoperability Definitions**: Distributes typed symbol names, enum IDs, and data structures necessary for interoperability and modding.
* **Idempotent Regeneration**: Extraction tooling is deterministic and can be rerun against any updated game binary to regenerate SDK bindings.


## Independent reward cooperation (2026-09-22)

`cpp/include/hs_game_sdk/reward_scope.hpp` provides a process-local, thread-owned
RAII scope shared by AFK FARM and optional ForgePact. It exposes compatibility
and observed native drop denominators, never calls plugin symbols, and restores
scope depth on exception. Keep mapping version/layout identical in both builds.
`reward_stats.hpp` distinguishes runtime query IDs from item/UI stat IDs: native
`ReturnSpecificStat` Magic Find uses query 34 on the verified AFK build.

AFK's C++ rewards smoke checks defaults, bounds, nesting, thread isolation,
exception restoration and published bases. Native MF positive control requires
the query to reach StatMagicFind, not just return a plausible number.

## Native routine names (AFK FARM, 2026-09-23)

`cpp/include/hs_game_sdk/native_names.hpp` (namespace `HeroSiege::Hooks`) finds
the one function that references a GML routine's name string: it looks for the
NUL-terminated name in readable, non-executable sections, then for RIP-relative
`LEA` references to it inside caller-supplied function bounds. Ambiguous matches
and names inlined into another script's body are refused. It never calls or
patches a resolved address, and an offline PE probe runs the same search as the
live one. AFK FARM's plugin (`HS-AFK-Expedition/plugin`) includes it; ForgePact
does not.

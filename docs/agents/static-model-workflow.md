Story and evidence behind `AGENTS.md` § ["Mod Development Workflow: Test Before / After, Then Build to It"](../../AGENTS.md#mod-development-workflow-test-before--after-then-build-to-it),
and its static-model paragraph.

# Static reading, a written spec, a model: the drop-roll pilot (issue #162)

Issue #162 proposed a research workflow with four steps:

1. Read the game locally.
2. Write the mechanism down in our own words.
3. Build a model from that spec and from measured traces.
4. Develop mods against the model, so that fewer live launches are needed.

The pilot ran it backwards over research already finished: ForgePact's
drop-rate levers on the two-stage drop roll. It needed no new live session. The
measurements it uses were already recorded in ForgePact's docs, code comments
and commits.

What it produced:

- [`docs/models/drop-roll-spec.md`](../models/drop-roll-spec.md): the mechanism,
  with every claim labelled static reading, measured, our code or not
  established.
- [`hs-game-sdk/python/hs_game_sdk/drop_roll_model.py`](../../hs-game-sdk/python/hs_game_sdk/drop_roll_model.py):
  a stdlib-only, deterministic model of the game's side.
- [`hs-game-sdk/curated/drop_roll_measurements.json`](../../hs-game-sdk/curated/drop_roll_measurements.json):
  ten recorded measurements, M1–M10. Each names the test that reproduces it, or
  says why it cannot be reproduced.
- [`tests/test_drop_roll_model.py`](../../tests/test_drop_roll_model.py): baseline
  and target tests. ForgePact's levers are input transforms in that file, pinned
  to ForgePact's source by `LeverParityTests`.

## The clean-room split

Two roles are kept apart, even when one person or session plays both:

- **The reader** looks at the decompiled game locally and writes the spec in
  their own words. Every claim gets a label and a source, and the reader's
  output never leaves the machine (`AGENTS.md` § "Legal").
- **The builder** writes the model and its tests from the spec and the recorded
  measurements only. If the spec is not enough to write a test, the builder asks
  for the gap to be read. The builder does not go and read the game.

This pilot kept the split. The planning pass read the game locally on 2026-09-24
and kept everything it saw in its scratchpad. The model, fixture and tests were
written from the spec alone. `NoDecompilerOutputTests` checks the pilot's files
against `.claude/hooks/decompiled_output.py`'s signatures, with a positive control
built at runtime.

## Live rounds

**Counting rule.** A round is one dated in-game session or release whose result
the sources record as its own finding. Measurements made within one session
count once. A release that reached players counts as a round when its outcome
was then measured or reported. The counter misreadings within round 5 are part
of that round.

| # | Date | What happened | Source | With this workflow |
|---|---|---|---|---|
| 1 | 2026-08-26 | Drop multipliers did nothing. A small sample (`Gold c=4`) was misdiagnosed as the wrong gold script. | ForgePact `docs/S10-special-content-notes.md`, "Drop carpanlari - neden calismiyordu", "### 2) Anahtarlar icin YANLIS fonksiyon kancaliydi" | Answered statically for the mechanism: the type-to-script map says which `Drop*` script each key type reaches. The same day's other finding (the hooks were not installed in the release build at all) is outside any model. The confirmation run below would catch it. |
| 2 | 2026-08-26 | A full map of per-script call counts (DungeonKeys 0, Keys 57, …). | Same heading | Answered statically (same map). |
| 3 | before 2026-08-27 | "önceki turların üçü de bu noktada yanılmıştı": three earlier rounds went wrong on the gate and denominator question. | ForgePact `docs/dungeon-key-research.md` §1 | The source does not say whether these three were live sessions, so they are **not counted** in the total. The static reading of the gate answers the question they were asking. |
| 4 | 2026-08-27 | `dungeonkey probe`: `chances[12]` was 0 in 200 of 200 calls (M1). | `S10-special-content-notes.md`, "COZULDU - zindan anahtarlari dogal olarak dusuyor" | Answered statically. Type 12 never sits beside 11 in the drop tables, and the model gives a zero chance a zero gate. |
| 5 | 2026-08-27 | Gate opened: 95 of 1233 extra type-12 rolls passed. Inner base 1500, then 50, then 3 (M2–M5). The `c=N` counter was misread twice. | Same heading | **Still live, as one trace**: log the die range and the key's inner bound on one monster. That pins N and `s`, and it is the positive control for everything after it. |
| 6 | 2026-08-28 | v1.2.1 was **released**, and its relic fix (scaling the gate chance by 0.05, then 0.001) was measured as a no-op (M6). | ForgePact `799ac2f`, `c0a6a6b`; the comment above `g_DkTipOlcek` | Answered without a launch or a release. The whole-number gate makes every chance in (0, 1] the same (`test_m6_…`). |
| 7 | 2026-08-28 | v1.2.2 pre-roll tuning: 0.01 and then 0.0005 at x2, measured as a share of dropped items (M8). | ForgePact `c0a6a6b` | **Still live**: this is feel tuning. The model can say that a pre-roll before the gate gives continuous control, but not which share feels right. |
| 8 | 2026-08-28 | x100 checks and the quadratic curve (M8). | ForgePact `cbac161` | **Still live** (feel tuning). The model does check the identity `0.00025 × 2² = 0.0005 × 2` and the clamp at x100. |
| 9 | 2026-09-06/07 | 1.3.10–1.3.12 were **released** with the gate opened everywhere and the lever squared; players reported the flood (M9). | ForgePact `5822d3a`; `src/forgepact.py` `build_key_cmds` and `KEYS` comments | Answered without a launch. The model shows that a multiplier on both the gate and the roll gives m² (`test_m9_…`). |

**Total: 8 counted live rounds** (rows 1, 2 and 4–9), plus row 3's three rounds
of unknown kind. Two of the eight shipped a defect to players (v1.2.1, and
1.3.10–1.3.12).

**With this workflow: 4 rounds.** Row 5 becomes one trace. Rows 7 and 8 stay,
because they are feel tuning. Add one final confirmation run with the finished
build, which is also where "does the hook attach at all" (row 1's other half) is
settled. Rows 1, 2, 4, 6 and 9 need no launch. Neither of the two defective
releases would have shipped with its defect: the model predicts both.

This is hindsight. The spec was written knowing which questions mattered, and
the rounds it "saves" are the ones whose answers were already known when it was
written. The forward test is to use the workflow on the next drop change and
count again.

## Tooling findings

- **Most drop scripts have no name in Ghidra.** `%USERPROFILE%\tools\hs-symbols\symbols.csv`
  (the file `citrace symdump` writes, which `ImportSymbols.java` imports) has 83
  rows whose module is `other`. Every drop script is among them:
  `DropDungeonKeys`, `DropKeys`, `DropItem`, `DropRelic` and `LootGroundCreate`.
  So the imported program has no names for them. The likely cause is that
  `symdump` ran while ForgePact's table hooks were installed, so those table
  entries pointed into the plugin. **UNVERIFIED.** The planning pass found
  `DropDungeonKeys` another way: it decompiled the unnamed direct callees of
  `LoadDrops` and identified the script by the named scripts it calls.
  **Run `symdump` in a game with no ForgePact hooks installed** until this is
  checked. A note in `ImportSymbols.java` would belong to a separate ForgePact
  change.
- **The reading scripts are not in any repository.** Apart from
  `ImportSymbols.java`, the helpers used for reading (`DecompileTo.java`,
  `FindCallers.java` and others) exist only in `%USERPROFILE%\ghidra_scripts` on
  one machine. A second reader would have to rewrite them.
- **One YYC drop script decompiles to about 50KB.** The planning pass stopped
  before it reached the direction of the inner adjustment. That is why `s` is a
  parameter and not a number.

## What the pilot did not show

- **That the workflow saves rounds going forward.** The count above is a
  retrospective over solved research. No new change has yet been developed
  against the model first.
- **The unknowns.** N and `s` are still hypotheses. The pilot described the
  trace that would pin them but did not run it.
- **That the clean-room split scales.** One mechanism was read, by the same
  session that planned the work. A spec for a larger mechanism, handed between
  people, was not tried.
- **Anything a pure function cannot see.** Hook attachment, frame timing, value
  kinds, stale addresses and moving `anon@N` names, the game's RNG sequence and
  feel tuning. They are listed in the spec's
  [What the model cannot catch](../models/drop-roll-spec.md#what-the-model-cannot-catch).
- **Parity across bindings.** The model is Python only. There is no C++ or
  TypeScript counterpart, so no parity is claimed.
- **A pull-request check.** The hub suite, and this test with it, runs in
  `hub-release.yml` on a `hub-v*` tag or a manual dispatch, not on pull requests.
  CI checks out without submodules, so `LeverParityTests` skips there. It runs
  only in a local checkout with ForgePact initialised. The owner decided on
  2026-09-24 to leave CI as it is.
- **The inert relic lever, fixed.** The relic half of `droprate group relic`
  divides every relic base by the same factor, which changed nothing observable
  because `DropRelic`'s drop is not a 1-in-base roll. That is recorded in ForgePact's
  Known Limitations. Removing it is a separate ForgePact change.

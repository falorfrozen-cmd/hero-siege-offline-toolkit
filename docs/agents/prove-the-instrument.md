Story and evidence behind `AGENTS.md` § ["Prove the Instrument Before Trusting a Negative Result"](../../AGENTS.md#prove-the-instrument-before-trusting-a-negative-result).

## The false negative that started this rule

The batching advice above is necessary but was not sufficient, and the reason
is worth its own rule. The same Pet Quest Collector research went on to spend
several more sessions on a *false negative*: 34 hooked call sites reporting
**0 calls** across multiple confirmed, observed collects. The conclusion drawn
- "the game does not call any of these" - was wrong. `HookOneScript` installs
by swapping a pointer inside the script-table entry, and this game's compiled
GML calls another script with a direct `call rel32` bound at compile time,
which never reads that table. **Every one of those zeros measured the
instrument, not the game** (`ForgePact/docs/pet-quest-collector-c-research.md`,
"The hooks were blind"). Two whole mechanisms were abandoned on that evidence.

## The same blindness, found as a shipping bug (ForgePact PR #2)

**The same blindness is a shipping bug, not only a research one.** A
table-only hook prints "HOOK INSTALLED" and then silently changes nothing on
the paths compiled GML actually uses - a feature that reports armed and does
nothing. Origin's review of ForgePact PR #2 found direct native callers for
`StatMovementSpeed`, `StatAttackSpeed`, `DropRelic`, `DropMonsterGold` and
`DropGold`, so stat scaling, drop multipliers and the max-level relic filter
were all in that state. `ForgePact`'s `HookOneScript` therefore installs
**both** - the table swap and an inline detour at the function's own address -
and hands the hook body the trampoline. `HookOneScriptTable` still exists for
exactly one purpose: `citrace nativetrace` needs a deliberately table-only
hook to compare against, and that comparison is what proved the problem.

## The same fix, needed again in the shared SDK (hub PR #3)

**And the rule applies to every installer, including a shared one.** Origin's
review of hub PR #3 found `hs-game-sdk`'s own `HeroSiege::Hooks::InstallScriptHook`
- the API other submodules are told to adopt - still table-only, and worse,
overwriting the saved original with the hook itself on a second install, so a
hook body forwarding through that pointer would recurse into itself. The shared
installer now does what ForgePact's does: both routes, trampoline as the
original, detour attempted only on the first install, and a result that *says*
`TableOnly` with a reason rather than reporting plain success.
`InstallScriptHookTableOnly` is the deliberately-limited variant, named so the
limitation is visible at the call site. A correction landing in one submodule is
not done until the shared SDK that other submodules copy has it too.

## The same shape outside C++, in a Python MCP server (hs-drive)

Everything above is a C++ hook, which is a problem for this rule's reach: a
reader writing a host-side Python tool reads `HookOneScript`,
`InstallScriptHook` and `citrace nativetrace` and reasonably concludes the
section is about hooks. It is not. The `hs-drive` MCP server produced the
same shape **three times**, in ordinary Python, with no hook anywhere near
it.

- **`hs_selfcheck` reported itself healthy while blind.** `checks.py`
  computed `healthy = counts["fail"] == 0`, so a run in which every check
  *skipped* reported `healthy: true` - and `healthy` is the field a caller
  branches on. The fix marks `process_snapshot` and `backup_roundtrip` as
  declared positive controls and requires them to have **passed**, not
  merely not-failed; the summary now carries `positive_controls` and
  `positive_controls_proven` so the difference is visible rather than
  inferred (`tools/hs_drive_mcp/checks.py`, `register(...,
  positive_control=True)`; pinned by
  `tests/test_hs_drive_mcp_server.py::SelfCheckSummaryTests`, which covers
  an all-skipped run, a single skipped control, an empty registry, and a
  raising check reported as `fail` rather than `skipped`).
- **`hs_input` reported a refused keystroke as delivered.** The
  `post_message` route returned a bare `bool(PostMessageW(...))`, every call
  site ignored it, `ctypes.get_last_error()` was never read although the
  library was opened `use_last_error=True`, and the sent/rejected counters
  were incremented only on the `SendInput` path - so a post refused by a
  UIPI mismatch, a destroyed window or `ERROR_NOT_ENOUGH_QUOTA` replied
  `records_sent: 0, records_rejected: 0, complete: true`. A refusal now
  stops the rest of the sequence, counts, clears `complete` and names the
  message and the error code (`tools/hs_drive_mcp/input.py`, pinned by
  `tests/test_hs_drive_mcp_input.py`).
- **`hs_input`'s `click` reported a press that never happened.** Its own
  existing test, `test_a_client_click_converts_then_moves_then_presses_then_releases`,
  asserted three `INPUT` records in that order and never asked whether
  anything separated the down record from the up one - so it could not have
  caught a `click` that emitted both back to back, which is exactly what
  `_do_pointer` did. Measured live (`ForgePact/docs/character-select-research.md`
  C-1.10): both records landed inside one frame, invisible to a 144 fps
  sample loop, so the click moved the cursor, lit the button and reported
  `complete: true` having activated nothing. The fixture's `sent`/`posted`/
  `slept` lists could represent "no sleep" but not "sleep in the wrong
  place," so the fix (`hold_ms` on `click`, a sleep between down and up)
  needed a fixture that logs one ordered sequence of calls, not three
  separate ones, before the ordering itself could be pinned
  (`tests/test_hs_drive_mcp_input.py`, `ClickHoldOrderTests`).

The second one is why this matters to research and not only to shipping: the
route's positive controls in the character-select procedure are a human
holding a key and a human clicking a button, and **neither exercises the
posted route's delivery path**. Had it stayed, the live session would have
recorded that candidate as "not observed" about the *game* when nothing had
ever left the MCP process - a zero that measured the instrument, which is
this rule's opening paragraph in a different language.

### What the first two have in common: a test double that could not represent the failing return

`AGENTS.md` § "HS Game SDK Usage" already states this for input kinds - "a
stub that cannot represent the failing input cannot catch the bug", learned
when a C++ test double did not define the `RValue` kind the real runtime
returns. The `hs_selfcheck` and `hs_input`-refusal instances above are the
same rule pointed at a **return value** instead: `hs_input`'s fake
`post_message` returned a hardcoded `True`, so no test could express a
refusal; `hs_selfcheck`'s summary counted `skipped` as not-a-failure, so no
test could express "ran nothing". The failing case was not missed, it was
*unrepresentable*. The `click`-hold instance is the same rule pointed at a
fixture's **structure**: `sent`/`posted`/`slept` were three separate lists,
which could express *that* something happened but not *where in the
sequence* - so an assertion checking presence and count could never say
whether a sleep landed between two button records or after both, and the
gap it could not have caught was exactly the one C-1.10 measured.

The first two were found by a **reviewer**, neither by a test; the third by
**live measurement**, neither by a test nor by review. All three suites were
green throughout: they asserted the field was present and well-typed, or the
records were sent in order, never that the effect was *earned*. So the
operational form of the rule, for whoever is writing the tests rather than
reading them afterwards, is:

> **Ask what your green would look like if the thing under test did
> nothing.** If the answer is "the same", the test is measuring the
> instrument.

That is the question a test author does not naturally ask about their own
instrument, which is why two rounds of review caught what two test suites
did not.

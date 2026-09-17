Story and evidence behind `AGENTS.md` § ["HS Game SDK Usage"](../../AGENTS.md#hs-game-sdk-usage).

## Identify a thing by what it is, not by a field it happens to carry

**Identify a thing by what it is, not by a field it happens to carry.** Origin's
review of hub PR #3 found the C++ relic scanner accepting any item with a level
field, so the ordinary item `{b:15, c:8, level:100}` came back as maxed relic 15
- and `ForgePact`'s `RelicFilterMod` calls that scanner directly, so an unrelated
item could suppress a real relic drop. Level-shaped fields are everywhere in this
game's item structs (`p` is a star upgrade count, stacks carry
`amount`/`count`/`qty`), so "has a level" identifies nothing. Use the documented
positive signal instead - rarity tier 16, or the relic-specific `relicLevel` field
(`docs/RUNTIME_DATA_MODELS.md`) - and read the value only from the fields
documented to hold it. The same applies to shape: a bare number is only a
`relic id -> level` entry inside a container that is specifically a relic table,
never in a general inventory.

## Accept the kinds the runtime actually produces

**Accept the kinds the runtime actually produces, and never let a kind check
decide whether the work happens at all.** `GetOwnedRelicLevels` opened with
`player.m_Kind != VALUE_OBJECT -> return {}`, but this runner resolves the local
player as `VALUE_REF` (kind 15, `docs/RUNTIME_DATA_MODELS.md` §1). So the scan
returned an empty map for every player, and because an empty maxed set means
"nothing to hold back", ForgePact's relic filter armed, hooked, logged
`hook installed -> ON`, and then let every relic through (reported 2026-09-14).
This is a **recurring bug class in this codebase, not a one-off**: `orbpickup`
logged `seen=176993 noplayer=176993`, the relic filter's own arming step never
fired, and upstream had already fixed the same class in the Headhunter
kill/steal path (`HhResolveInstance`, shipped in 1.3.16) — each found
separately, each costing a live session. That is why the kinds now live in a
named `IsInstanceHandle` predicate instead of one more inline comparison. Every accessor involved
(`variable_instance_exists`, `variable_instance_get`) takes a reference straight
through, so the kind was never load-bearing; it only decided whether anything
ran. A feature that reports itself ON while doing nothing is the expensive
shape of this bug: prefer a log line that names what it *did* ("holding back N")
over one that names what it *is*.

## A stub that cannot represent the failing input cannot catch the bug

**A stub that cannot represent the failing input cannot catch the bug.** Nine
C++ SDK tests passed over that dead scanner because
`tests/cpp/stubs/YYToolkit/YYTK_Shared.hpp` did not define `VALUE_REF` at all
and `FakePlayer()` only ever built a `VALUE_OBJECT` - the test double had
quietly narrowed the world to the half that worked. When a stub stands in for a
runtime surface, its enums and shapes are part of the contract under test: give
it the values the real runtime returns, then assert the two paths agree on one
shared fixture rather than asserting each is separately non-empty. Keep a
negative control alongside (an undefined player still scans nothing), so
widening what is accepted cannot quietly become accepting anything.

## Testing two language bindings against the same fixture was still not enough

**When two language bindings answer the same question, test them against the same
fixture - and make the contract itself comparable.** The Python scanner was
already correct while the C++ one was not, and nothing caught the divergence
because only Python had tests. Adding one shared fixture was still not enough:
origin's second review found the *opposite* gap on the same pair - C++ accepted
`cls` and read numeric arrays out of `relic_levels`, Python did neither - because
a single flat fixture cannot cover a contract. So the accepted fields, limits and
container names are now declared as **enumerable constants in both bindings**
(`kRelicTierFields` / `RELIC_TIER_FIELDS` and friends), the C++ test harness
prints them, and `tests/test_cpp_sdk.py` asserts the two lists match field for
field. Editing one side now fails a test rather than drifting.

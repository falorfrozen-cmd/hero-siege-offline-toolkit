Story and evidence behind `AGENTS.md` § ["Don't Suspend the Game's Own Runtime"](../../AGENTS.md#dont-suspend-the-games-own-runtime).

## Why suspension features are a different risk class, in full

- **The failure mode inverts.** Ordinary mods fail by doing nothing (a dead
  `relicgate`, a collect that never fires). A suspension feature fails by
  leaving the player's session stuck, or by letting the game save while its own
  state is half-removed. When a design needs a panic hotkey, a watchdog and a
  fail-open path on every branch before it can ship, that machinery is the
  signal, not the mitigation.
- **The precise instruments are unavailable on this build.** YYToolkit's
  per-event hook (`EVENT_OBJECT_CALL`) is deliberately disabled in the
  YYToolkit this project ships — it crash-looped on Season 10 — and
  named-script hooks are structurally blind against this YYC build's direct
  calls (see the section above). What remains is blunt, whole-subtree
  instance deactivation, with the widest possible blast radius.
- **The claim cannot be verified.** "Everything stops" is a statement about
  every timer, DoT, cooldown and internal counter in the game, including the
  ones nobody has enumerated. Contract tests can pin the mod's own structure;
  they cannot establish that. A miss surfaces as a buff that quietly expired or
  a cooldown that quietly advanced — wrongness a player reports months later as
  "the mod broke my character".
- **It taxes every future game patch.** Anything that has to know the game's
  full object or UI surface (which windows count as a menu, which objects are
  actors) is upkeep on someone else's release schedule.

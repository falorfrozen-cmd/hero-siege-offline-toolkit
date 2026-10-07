# ForgePact Discord release announcement

The post that goes to Discord when a ForgePact release is published. It is
written from that version's `release-notes-vX.Y.Z.md` (or the GitHub release
body: `gh release view vX.Y.Z -R falorfrozen-cmd/ForgePact`). The notes are
the full, exact record. The Discord post is for players skimming to see what
changed. The 2.0.0 + 2.0.1 post is the model, and 2.1.0 was the first one
written from this template.

## Template

```markdown
@everyone 
## ForgePact X.Y.Z
<One sentence on what the release is about>. Every new switch is **off by default**.

**New**
- **<Feature name>:** <what it does for the player, and where it is if that helps>.

**Changed**
- <Changed behaviour, or a renamed or moved setting>.

**Fixed**
- **<Mod name>** <what works now, or what no longer goes wrong>.

**How to update:** <one or two sentences, condensed from the notes' "How to update">.

Offline / EAC-disabled copies only.
<https://github.com/falorfrozen-cmd/ForgePact/releases/tag/vX.Y.Z>
```

## Rules

- **Keep it under 2000 characters.** Discord rejects a longer message.
- **Use plain player words.** Bold the setting's name as the panel shows it,
  then say in one short bullet what it does for the player. Leave out
  measurements, coverage and log commands. One striking number is fine, such
  as a frame-time drop.
- **Keep bullets flat.** Don't nest them, and leave out a section that has
  nothing in it.
- **Name both versions when two ship together.** Title it `X.Y.Z + X.Y.Z+1`
  and link the newer one.
- **Wrap the link in `<>`.** That stops Discord from adding a preview card.
- **Post only after you publish the release.** The tag link 404s while the
  release is still a draft.

## Example: 2.0.0 + 2.0.1

```markdown
@everyone 
## ForgePact 2.0.0 + 2.0.1
A new look for the panel and a round of bug fixes. Every new switch is **off by default**.

**New**
- **New look:** the **Ember Forge** theme (new default) adds a sidebar, Overview shortcuts and a search across every setting. Ledger, Graphite and Sigil are still under Setup → Appearance.
- **Enabled mods list:** see everything you've turned on and switch any of it off in one click.
- **On/off switch on every slider:** turn a slider off without losing your value.
- **Far scenery sleep:** far trees, rocks and fences stop updating until they come into view, about a sixth less work per frame in Act 1's first zone.
- **Pet moves on from loot it can't pick up:** the pet stops hopping around an item it can't grab and goes for the rest.

**Changed**
- **Pet Collects Quest Items** handles several quest items at once and comes back for ones it missed.
- Gems of Incarnation moved to the Loot tab, and its mod filter is now searchable.
- Mining Ore Amount is now called **Mining Ore Multiplier**.

**Fixed**
- A high **Gold multiplier** no longer freezes the game: it drops one bigger coin instead of thousands, and monster gold now matches the multiplier you set (10× used to give about 100×).
- **Remove owned relics from drop pool** now sees the relics you're wearing.
- The **timed skill countdown** now shows on Mana Orb.
- **Craft from the stash** says why a craft was refused.

**How to update:** extract the full release or update through the hub, reopen ForgePact (your settings are kept), then press **Install Mod Plugin**. Updating only the panel leaves the old plugin in place.

Offline / EAC-disabled copies only.
<https://github.com/falorfrozen-cmd/ForgePact/releases/tag/v2.0.1>
```

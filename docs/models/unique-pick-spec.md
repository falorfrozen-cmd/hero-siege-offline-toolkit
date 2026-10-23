# Which unique a unique roll yields: spec for a model

This is the written mechanism behind
[`hs-game-sdk/python/hs_game_sdk/unique_pick_model.py`](../../hs-game-sdk/python/hs_game_sdk/unique_pick_model.py),
tested by [`tests/test_unique_pick_model.py`](../../tests/test_unique_pick_model.py),
and checked against
[`hs-game-sdk/curated/unique_pick_measurements.json`](../../hs-game-sdk/curated/unique_pick_measurements.json).
It was written for ForgePact#158 (hub #500), the flight charms. The owner asked
that their drop rates be "as intended": each charm should drop with one entry's
share of its roll, as Headhunter and Tyrant's Crown already do (ForgePact#74).
This spec covers *which* unique comes out once a unique roll runs. Whether the
Angelic roll runs at all on a kill is the game's own chance, which is not
modelled here (see Not established). [`drop-roll-spec.md`](drop-roll-spec.md)
covers the gates that come before a roll, and
[`relic-pick-spec.md`](relic-pick-spec.md) the relic pick, which works
differently.

ForgePact#166 (hub #518) added a third roll, the Heroic roll
(`DropItemHeroic`), for the Mark 1 set: with the "Mark 1 drops" switch on, each
of the four Mark 1 pieces joins that roll with one entry's share, the way the
flight charms join the Angelic roll. On the owner's 2026-10-20 route the
pieces also drop from ordinary kills, the way the game's own set items do: the
same switch pushes them onto the ordinary unique roll (`DropUniqueItems`), the
kill route, beside Pocket Elf.

ForgePact#166's Mod live procedure 7 then found that an ordinary kill does not
reach `DropUniqueItems` at all: its unique comes from a draw inside `DropItem`
itself, from `lootListUnique[k]` with k what `LoadSatanicDropTier` answered in
the same call ("the draw" below). With their switches on, each Mark 1 piece
and Pocket Elf join that draw too, and the spec covers it in each section. The
`DropUniqueItems` and Heroic routes stay as they were.

It was written from the shared references only:
[`docs/RUNTIME_DATA_MODELS.md`](../RUNTIME_DATA_MODELS.md) (RDM) § 13.4, § 13.12,
§ 23.4 and § 23.8, ForgePact's `mark1-set-research.md` ("Mod live 7 results"
and "Phase 4 decision") for the draw's measurements, and ForgePact's own
source for the Our code section. The Heroic roll's reading of 2026-10-20 is
folded into RDM § 23.4, and the draw's into RDM § 13.12, by the same feature.

Every claim carries one of four labels, and a source:

- **Static reading**: read from the compiled game locally and written here in our
  own words. No script text is quoted or transcribed (`AGENTS.md` § "Legal").
- **Measured**: observed in a running game.
- **Our code**: what ForgePact does. The model leaves it out, and the test expresses
  it as an input transform.
- **Not established**: carried by the model as a parameter.

## Names used here

- **The unique list.** `Controller_obj.lootListUnique` is an array of six
  `ds_list`s (RDM § 13.4, measured). Each entry of a sub-list is a triple of
  numbers: type, sub-type and base (`b`), the key a unique is looked up by in
  the game's unique repository (`GetUniqueRepoStruct`).
- **Droppable.** An entry is droppable on a roll when that roll keeps it once
  picked. Each roll has its own test, below.
- **T**: the number of droppable entries on `lootListUnique[5]`, the Angelic
  roll's list, counted with repeats.
- **T_H**: the number of entries the Heroic roll keeps on the sub-list it
  reads, counted with repeats. The roll reads `lootListUnique[5]` when its
  index argument is left undefined; which index its callers pass is not
  established (see Not established).
- **L_k**: the length of `lootListUnique[k]`, for k from 0 to 4, the ordinary
  unique roll's sub-lists, and from 0 to 5 on the draw. **k is always a
  sub-list index in this spec.**
- **D_k**: how many entries of sub-list k the ordinary unique roll keeps.
- **c**: how many copies of a stand-in entry ForgePact pushes for one item in one
  roll. ForgePact's research commands call this "copies k"; this spec calls it c
  so that k stays the sub-list index.
- **e**: the total number of entries ForgePact pushes onto one list for one
  roll, the sum of c over the items switched on.
- **n**: how many vanilla entries of a list carry exactly a stand-in's whole
  triple.
- **m**: how many droppable vanilla entries of `lootListUnique[5]` carry the sub
  and `b` (the pair, not the triple) of either of #74's validated stand-ins. It
  is only needed to read #74's `standinPicks=` counter (see Measured).
- **The draw**: the unique draw inside `DropItem`, from `lootListUnique[k]`.
  **Here k is the tier `LoadSatanicDropTier` answered in the same call, 0 to
  5**, which is also the index of the list the draw reads.
- **a**: an entry's acceptance on the draw, the chance the draw keeps it once
  it has read it: 0 for an entry flagged by field 40 or 41, and otherwise set
  by its rarity branch, whose keep rule is not read.
- **W_k**: the kept weight of `lootListUnique[k]`, the sum of a over its own
  entries, counted with repeats. When every entry is either kept or refused
  outright, it is the number of entries the draw keeps.
- **p**: on the draw, the kept weight of the entries ForgePact adds to each
  list for one `DropItem` call; with every pushed entry kept as read, the sum
  of c over the items switched on.
- **n_k**: how many entries of `lootListUnique[k]` carry exactly a draw
  stand-in's whole triple.

## Static reading

- **The Angelic roll re-draws until it keeps a droppable entry** (RDM § 13.4,
  "The pick", static reading of 2026-10-02 for ForgePact#74).
  - `DropItemAngelicChance` takes a random entry of its list and looks the
    triple up through `GetUniqueRepoStruct`.
  - It throws the entry away and draws again when the base's hidden flag
    (base-info flag 40, a hidden or development item) is set, or when the
    definition's rarity (field 27) is neither 7 (Angelic) nor 10 (Unholy). It
    keeps drawing until one passes.
  - So each droppable entry, counted with repeats, is equally likely to be the
    one the roll keeps: an entry listed r times among T droppable entries comes
    out r / T of the time.
  - Roughly one entry in eight passes, which accounts for the eight or so
    definition reads per roll measured on 2026-09-23 (RDM § 13.4).
  - The list it draws from is `lootListUnique[5]` of the first `Controller_obj`
    instance (RDM § 13.4, static reading, with the layout measured).
- **A hit builds one item from the kept entry** (RDM § 13.4, static reading).
  The roll calls `CreateDefaultParams` with the entry's sub-type and base, and
  the placement takes the item's type from the entry itself. One hit is one
  ground item.
- **The ordinary unique roll makes one draw** (RDM § 23.4 and § 23.8, static
  reading of 2026-10-11 and 2026-10-12 for ForgePact#158).
  - `DropUniqueItems` is reached from `LoadDrops`. It chooses a sub-list
    `lootListUnique[k]`, k from 0 to 4, from a protected zone value that has a
    random chance of stepping up (§ 23.4).
  - It reads one random index of that sub-list. Only when the entry there is a
    triple does it look it up through `GetUniqueRepoStruct`.
  - It keeps the entry when the rarity is below 7 and the entry is not flagged
    hidden. Then it builds the drop's parameters with `CreateDefaultParams`
    and places the item with `LootGroundCreate`, with the entry's type.
  - An entry that fails any test drops nothing. There is no second draw and no
    die per entry.
  - So one call drops a given entry listed r times in sub-list k with chance
    r / L_k, and drops anything at all with chance D_k / L_k.
- **A kill reaches the ordinary unique roll through drop type 45** (RDM
  § 13.1 and § 23.4). An enemy's Destroy event calls `DropItem`, which calls
  `LoadDrops` (§ 13.1, static reading). Drop type 45 is "a unique item"
  (§ 13.1, measured on 2026-08-27 by opening every gate on one monster), and
  `LoadDrops` calls `DropUniqueItems` (§ 23.4, static reading of
  2026-10-11). Chests, goblins, destructibles and piles reach `DropItem` too
  (§ 13.1), so whatever joins the ordinary roll can come from those as well;
  that is an inference, not a reading of each.
- **Set items are Satanic uniques of that roll's lists** (RDM § 23.4). The
  roll was read again on 2026-10-20 for ForgePact#166: one draw from
  `lootListUnique[k]`, kept when the repository rarity is below 7 and the
  entry is not hidden, and no branch for set items (static reading). A game
  set piece, Sacred Pendant, came out of the unique repository at rarity 6
  (Satanic) when the Heroic roll was called by name (measured, ForgePact#166
  Live 1), and every one of the 218 kept entries on `lootListUnique[4]` is
  rarity 6 (measured, same session). The ordinary roll keeps every rarity
  below 7, so a set piece that sits on one of lists 0 to 4 drops through it
  with one entry's share, like any other unique there.
- **The two rolls read different sub-lists.** The Angelic roll reads index 5;
  the ordinary unique roll reads 0 to 4. Other routines read the same lists
  (RDM § 13.4, "Other readers of the list"), which is why ForgePact takes its
  entries off again after each roll.
- **The Heroic roll re-draws too, with the opposite rarity test** (RDM § 23.4,
  static reading of 2026-10-11, read again on 2026-10-20 for ForgePact#166).
  - `DropItemHeroic` (1374) takes three arguments: a position, which it takes
    from the calling instance when the first two are left undefined, and a
    sub-list index, which is 5 when left undefined.
  - It takes a random entry of `lootListUnique` at that index. An entry that
    is not a triple is drawn again. A triple is looked up through
    `GetUniqueRepoStruct`, and the roll keeps it only when the base's hidden
    flag (base-info flag 40) is clear and the definition's rarity (field 27)
    is neither 7 (Angelic) nor 10 (Unholy). Otherwise it draws again, until
    it keeps one.
  - So it keeps Satanic (6) and Heroic (9) uniques, and every other rarity
    except 7 and 10. An entry listed r times among the T_H entries the roll
    keeps comes out r / T_H of the time. Because a miss is drawn again, it
    makes no difference whether the random index can reach the list's length.
  - After the loop it calls `CreateDefaultParams` once, with the kept entry's
    sub-type and base, and then the placement, given the entry's own type. So
    the placed item's class is the entry's, as in the Angelic roll, and one
    call places one item.
  - Its direct callers (RDM § 23.4, static reading of a byte scan) are
    `VaultUse` (4597), which runs when a player uses a vault item from the
    bag, and a Chaos Tower NPC closure. No caller on a kill has been read.
    Which index and which calling instance `VaultUse` passes was not read.
- **On one list the two re-drawing rolls split the entries between them.** An
  entry that is not flagged hidden is kept by the Angelic roll when its rarity
  is 7 or 10 and by the Heroic roll otherwise, never by both (static reading,
  the two tests above).
- **`DropItem` draws a unique itself** (RDM § 13.12, static reading of
  2026-10-20 for ForgePact#166, from a byte scan for direct calls and a call
  list, since `DropItem` is too large for the decompiler).
  - `DropItem` is the only direct caller of `LoadSatanicDropTier` (2173),
    which answers a whole number from 0 to 5 by brackets of the monster's
    level, stepped inside each bracket by random cut-offs.
  - It reads `Controller_obj.lootListUnique[k]`, k that answer, draws a random
    index of it, needs the entry there to be an array, and looks its triple up
    through `GetUniqueRepoStruct`.
  - A definition with field 40 or 41 set sends it back to draw again. The
    loop's counter starts at 500, so one call can read up to about 500
    entries. What a call does when the counter runs out was not read.
  - The definition's rarity then picks one of four branches: 6 (Satanic), 9
    (Heroic), 7 or 10 (Angelic or Unholy), and any other value. In the
    rarity-6 branch an entry whose tier (field 32) is 5 meets one more test,
    on a protected value. Whether each branch keeps the entry or draws again
    was not read branch by branch, so the model carries an entry's acceptance
    a as an input.
  - After the draw, one `CreateDefaultParams` call and one placement call
    build the item, in that order in the call list.
  - Whether the loop keeps the first entry it accepts or weighs the accepted
    ones by a computed value was not read; a local that starts very large and
    is lowered inside the loop hints at a weighing. Mod live 7 measured it
    (`first-kept`, Measured below).
- **The draw is apart from every named unique roll** (RDM § 13.12, static
  reading). `DropItem` reaches `DropUniqueItems` only through `LoadDrops`' drop
  type 45, and calls `DropItemAngelicChance` once. A second draw of the same
  shape reads a list passed as `DropItem`'s argument 7; it is not modelled
  here, because no kill's unique was built through it (Measured).
- **So, on the draw, an entry listed r times on list k with acceptance a comes
  out r * a / W_k of the draw's builds from that list**, if the draw keeps the
  first entry it accepts: it throws back what it does not keep and reads
  again, so each entry is kept in proportion to its acceptance. That share
  holds given that the draw kept an entry within its counter; the chance it
  keeps none in 500 reads is (1 - W_k / L_k) ** 500, which the model gives
  apart (`draw_runs_out_chance`). Arithmetic on the readings above.

## Measured

- **#74's stand-in picks with nothing pushed** (RDM § 13.4, Live 1 to Live 3 of
  the list injection, all on 2026-10-02, with the Angelic roll's chance raised
  by a research lever). The counter is `standinPicks=` over the roll's hits.
  - Live 1: 1 of 57 hits.
  - Live 2: 2 of 46 hits (p0 = 0.043).
  - Live 3: 2 of 47 hits.
- **#74's stand-in picks at 200 copies** (same sessions, Headhunter's switch
  forced on and 200 copies of Liquor Holster's entry `{8, 0, 51}` pushed onto
  `lootListUnique[5]` per roll, the held read-back never failing).
  - Live 2: 65 of the next 80 hits (p1 = 0.81), with 22,800 entries pushed
    over 114 rolls.
  - Live 3: 46 of the next 62 hits (p1 = 0.742), with 18,000 entries pushed
    over 90 rolls.
- **What `standinPicks=` counts** (ForgePact's
  `angelic-roll-hook-research.md`, § "Session 3: list injection (issue #74)";
  a reading of ForgePact's own research code). A hit counts when the sub and
  `b` its `CreateDefaultParams` call receives equal either validated stand-in's
  pair, whatever the type. It is keyed on the pair, not the triple. Its
  vanilla share is therefore m / T, and with Headhunter alone at c copies it
  is (m + c) / (T + c). The two pairs are:
  - Liquor Holster's 0/51, which a type 10 unique also carries (RDM § 13.4);
  - the crown's stand-in, Mask of the Celestial, 0/86.
- **The sub-list lengths** (RDM § 13.4, Live 2 of the list injection,
  2026-10-02; repeated in § 23.8). `lootListUnique[0]` to `[5]` held 50, 61,
  79, 152, 221 and 380 entries, every one a triple. The sizes were the same
  after a zone change and at the end of the session. Liquor Holster's triple
  appears on `[5]` once, so its n there is 1.
- **ForgePact's validated Angelic pool** read 47 candidates (RDM § 13.4,
  Live 1 of 2026-10-02). These are distinct triples that pass the Angelic
  roll's two tests, not a count of list entries.
- **T and the stand-ins' n** (RDM § 13.4, the flight charms' Mod live 2 of
  2026-10-13, `flightprobe pool`, read in `Town_01_rm` and again in
  `Act_01_01`, the same both times, nothing pushed; ForgePact's
  `flight-charms-research.md`, "Mod live 2 results").
  - `lootListUnique[5]` held 380 entries, 48 of them droppable, counted with
    repeats: **T = 48**.
  - Water Melon `{10, 0, 47}` and Soul Collector `{10, 0, 91}`, the Wings'
    and the Broomstick's stand-ins, are each listed once there: n = 1.
  - `[0]` to `[4]` held 50, 61, 79, 152 and 221 entries again, and Pocket
    Elf's stand-in, Aimbot.exe, is on none of them: n = 0, so the coin hands
    every pick of its pushed entry to Pocket Elf.
- **The flight charms at 200 copies** (Mod live 1, 2026-10-12, ForgePact's
  "Mod live 1 results"; the Angelic roll's chance raised by a research lever,
  the ordinary roll called by name with the player as `self`).
  - Pocket Elf, 200 copies on each of `[0]` to `[4]`: 11 of 20 calls, 19 of
    them placing an item.
  - Gabriel Wings and Witch's Broomstick, 200 copies each on `[5]`: 21 and 22
    of 44 hits (13 and 13 of the first 26).
- **The flight charms at one copy, the player build's** (Mod live 2,
  2026-10-13, ForgePact's "Mod live 2 results"; the same levers).
  - Pocket Elf (`rate-elf`): 1 of 100 calls, 97 of them placing an item.
  - Gabriel Wings and Witch's Broomstick (`rate-angelic`): 0 and 2 of 102
    hits, over 114 rolls.
  - Every count, in both sessions, lies within the 3-sigma band of the share
    the model gives with the push and the coin (The model, below). Counts
    this small cannot tell one entry's share from one a few times larger or
    smaller.
- **The Heroic roll called by name** (RDM § 23.4; the flight charms' Live 1 of
  2026-10-12, ForgePact's `flight-charms-research.md`, "Live 1 results", and
  `heroic_route` in `hs-game-sdk/curated/flight_charms_measurements.json`).
  Ten calls of `DropItemHeroic` with the local player as `self` placed ten
  items (which `self` the game's own callers, `VaultUse` and a Chaos Tower
  NPC, pass is not read): seven Heroic (9) and three Satanic (6), none
  Angelic or Unholy, and no charm. Nothing was pushed.
  Every call placed one item, as the re-draw predicts.
- **The draw is a kill's unique route** (ForgePact#166, Mod live procedure 7:
  Live 1 on 2026-10-20 and Live 1b and Live 1c on 2026-10-21, slot 14, Hell;
  RDM § 13.12 and ForgePact's "Mod live 7 results", UP15). In Live 1's owner
  window all 4 natural uniques were built in the draw's scope, while
  `DropUniqueItems`, `ReturnRandomSatanic` and the builds outside `DropItem`
  each rose by 0 (`unique-route: satanic-draw`). Live 1b built 9 that way and
  Live 1c 105. A debugger logpoint on the draw's own `CreateDefaultParams`
  call hit once per draw build (4 of 4, and 105 of 105).
- **List k holds the tier-k uniques** (`tier-k: matches`, UP15). Every natural
  draw build's triple sat on list k and its tier equalled k: 4 of 4, 8 of 8
  and 103 of 103. Live 1c's came at k = 1 to 5 as 22, 5, 14, 59 and 3; the
  three at k = 5 were rarity 7 and 9, so list 5 holds those rarities too and
  the draw builds them itself.
- **`LoadSatanicDropTier`'s answers** (UP16). In Live 1c (magic find x10) the
  answers 0 to 5 counted 0, 405, 401, 410, 3449 and 3432 over 8146 `DropItem`
  calls, and in Live 1b (x1) 0, 179, 193, 169, 1530 and 1432 over 3544: about
  one a call, and k = 0 never came up. In Live 1 the answers outnumbered the
  calls (867 against 497), which is not explained.
- **The draw keeps the first entry it accepts** (`draw-mode: first-kept`, UP17
  and UP18). The reads since the last build over Live 1's and Live 1b's 12
  natural draw builds had a median of 4 (Live 1c's 103: a median of 3, up to
  249), within the rule's 10. Live 1b's below-SS lever, 25 copies of each of 4
  below-SS stand-ins on every list, built 1 stand-in in 3 typed draw builds,
  against the rule's 0.13, half of 100 / (274 + 100) at the mean list length.
  The lever half rests on 3 builds, so the reading is thin.
- **Entries pushed onto lists 0 to 5 during a `DropItem` call reach the draw**
  (`push-route: seen`, UP18). The draw read them 1943 times over 971 calls in
  Live 1b's below half, and built the gloves stand-in at k = 5, where no
  natural copy sits. The lists read 50, 61, 79, 152, 221 and 380 again after
  the lever was off.
- **A pushed SS entry the draw reads is rarely built** (`ss-build: seen`,
  UP19). With 25 copies of each of 4 SS stand-ins (rarity 6, tier 5, each on
  list 5 only), Live 1c (x10, about 28 minutes) built 2 stand-ins among 105
  draw builds, the helmet at k = 2 and the boots at k = 4; Live 1b's SS half
  (x1) built none among 6. Kept as read, they would have taken at least
  100 / (L_k + 100) of the builds on any list. Why they are not is not
  established: the tier-5 test's reads were reached on every call, but what
  they compare was not logged. No natural rarity-6, tier-5 unique was built
  through the draw in that window. The probe's `picks=` count is an
  instrument count, not the draw's picks, and the model does not use it.
- **T_H and the Heroic roll's stand-ins** (ForgePact#166, Mod live 4,
  2026-10-20, slot 14, the roll called by name with the player as `self`;
  RDM § 23.4 and ForgePact's "Mod live 4 results", UP21). `mark1probe pool`,
  nothing pushed: `lootListUnique[5]` held 380 entries, of which the Heroic
  roll keeps **T_H = 203** (93 of rarity 6, 110 of rarity 9, counted with
  repeats); 48 are rarity 7 or 10, the T = 48 the Angelic roll keeps, and 129
  are flagged hidden. `[4]` held 221, of which it keeps 218. Each of the four
  pieces' classes had a stand-in on both lists, listed once (n = 1).
  - `reach`: at 200 copies of each stand-in, 40 calls placed 40 items, 32 of
    them pieces (helmet 10, body 13, boots 6, gloves 3).
  - `rate`: at the player build's one copy, 100 calls gave 2 pieces, inside
    the 3-sigma band for 4 / (203 + 4).
- **The ordinary roll's lists and the pieces' stand-ins on them**
  (ForgePact#166, Mod live 5, 2026-10-20, slot 14, `DropUniqueItems` called
  by name; RDM § 23.4 and ForgePact's "Mod live 5 results", UP22).
  `mark1probe pool kill` read lists 0 to 4 at 50, 61, 79, 152 and 221
  entries, UP6's lengths again, and each class's stand-in held 0 times on
  every one of them (n = 0). At 200 copies of each stand-in, 40 calls placed
  40 items, 35 of them pieces (helmet 5, body 8, boots 10, gloves 12).
  Neither session ran either roll from a kill or a vault. Mod live 6 saw no
  kill enter `DropUniqueItems` in Act 1 on Hell (type 45's chance 0 on all
  1831 arrays), while Mod live 7 and Mod live 8 saw it run inside a kill's
  `DropItem` call a few times (RDM § 13.1), so the model does not predict
  that route's share per kill.

## Our code

ForgePact's levers. The model leaves them out; the test file applies them as
input transforms, and pins them to ForgePact's source.

- **The push.** For the length of one roll, ForgePact adds one stand-in entry
  per switched-on item to the list that roll reads, and takes them off its tail
  after the roll. A stand-in is a real unique whose triple the roll keeps.
  - Headhunter and Tyrant's Crown (#74) and Gabriel Wings and Witch's
    Broomstick (#158) push onto `lootListUnique[5]`, for the Angelic roll.
    The flight charms' stand-ins are Water Melon `{10, 0, 47}` and Soul
    Collector `{10, 0, 91}`.
  - Pocket Elf (#158) pushes onto each of `lootListUnique[0]` to `[4]`, for the
    ordinary unique roll, and adds nothing inside the Angelic roll. Its
    stand-in is the first of five Satanic charm candidates that the ordinary
    roll keeps and that each of the five sub-lists holds the same number of
    times, so n is the same whichever sub-list the roll chooses.
  - The number of copies c is a `constexpr` 1 in the player build, for both
    #74 (`g_SigCopies`) and the flight charms (`g_FlightDropCopies`). Only the
    research build's copies lever changes it (`angelicprobe inject copies`,
    `flightprobe copies`, 1 to 400).
- **The coin.** A hit whose whole triple is a pushed stand-in's goes to the
  item with probability c / (n + c), and otherwise stays the game's own
  (`CoinShare` in ForgePact's `FlightCharms.hpp`; #74's coin is the same
  arithmetic). The game then builds the item from a rewritten record.
- **What that gives** (arithmetic on the readings above, not measured):
  - On the Angelic roll, a pushed item's stand-in triple is kept with
    probability (n + c) / (T + e), and the coin then gives the item
    c / (n + c) of that. So each item takes c / (T + e) of the roll's drops,
    and the stand-in itself keeps n / (T + e). At c = 1 that is one entry's
    share, the same as Headhunter, Tyrant's Crown, or a vanilla unique listed
    once.
  - On the ordinary roll, with sub-list k chosen, Pocket Elf takes
    c / (L_k + c) of the calls. At c = 1 that is one call in L_k + 1: between
    1 in 51 and 1 in 222.
  - The ordinary roll drops anything at all with chance (D_k + c) / (L_k + c)
    while Pocket Elf is pushed, and D_k / L_k otherwise.
- **Mark 1's push onto the Heroic roll** (ForgePact#166, `Mark1Drops.hpp`
  and its adapter in ForgePact's `ModuleMain.cpp`). While the "Mark 1 drops"
  switch is on, for the length of one `DropItemHeroic` call, ForgePact adds
  c copies of one stand-in entry per Mark 1 piece to the sub-list that call
  reads, and takes them off its tail after the call.
  - The sub-list is the call's third argument when it is a whole number from
    0 to 5, and 5 when it is absent or undefined, as the roll itself reads it.
  - A piece's stand-in is a triple of the piece's own class (helmet 0, body
    armor 1, boots 2, gloves 4) that the Heroic roll keeps, chosen from the
    live list: a Heroic (9) one first, then any other kept rarity, ties broken
    by the lowest sub-type and base. A class with no such triple on the list
    has no stand-in there, and that piece is not pushed; the others still are.
  - c is a `constexpr` 1 in the player build (`g_Mark1DropCopies`); only the
    research build's copies lever changes it.
  - Mark 1 pushes nothing inside the Angelic roll, and #74's items and the
    flight charms push nothing inside the Heroic roll. On the ordinary roll
    Mark 1 pushes too, by the kill route below.
- **Mark 1's push onto the ordinary roll, the kill route** (ForgePact#166,
  the owner's 2026-10-20 route, `Mark1Drops.hpp` and the shared
  `DropUniqueItems` detour in ForgePact's `ModuleMain.cpp`). While the "Mark 1
  drops" switch is on, for the length of one `DropUniqueItems` call,
  ForgePact adds c copies of one stand-in entry per Mark 1 piece onto each of
  `lootListUnique[0]` to `[4]`, beside Pocket Elf's, and takes them off the
  tail after the call.
  - The ordinary roll keeps only rarities below 7, so the Heroic route's
    rarity-9 stand-ins would be refused there. A kill-route stand-in is a
    triple of the piece's own class that the ordinary roll keeps (a Satanic
    one, as the lists hold) and that each of the five sub-lists holds the same
    number of times n: the equal-count rule Pocket Elf's stand-in follows,
    because the roll cannot say which sub-list it read, so the coin is exact
    only when n is the same on all five. n = 0 is preferred, then the smaller
    n, ties by the lowest sub-type and base. A class with no such triple has
    no stand-in on the kill route; the other pieces still drop, and the
    Heroic route is untouched.
  - The coin is the same: a hit whose whole triple is a pushed stand-in's goes
    to that piece with probability c / (n + c), and the record is rewritten to
    the piece's definition. Pocket Elf's stand-in is a charm (type 10) and
    the pieces' types are 0, 1, 2 and 4, so one hit never matches both.
  - One detour on `DropUniqueItems` serves both features; each pushes its
    entries only with its own switch on. With the Mark 1 switch off the
    ordinary roll behaves exactly as it did with Pocket Elf alone.
- **What that gives on the ordinary roll** (arithmetic on the readings above,
  not measured; the model's `kill_share`):
  - With p entries pushed onto list k in all (the pieces' and any other
    mod's), each piece is c / (L_k + p) of the calls that read list k, each
    stand-in keeps n / (L_k + p), and each of the game's own entries is
    1 / (L_k + p) per listing. A call that draws an entry the roll refuses
    still drops nothing, as before.
  - With all four pieces at c copies, p = 4c, so each piece is
    c / (L_k + 4c); with Pocket Elf's e copies too, c / (L_k + 4c + e).
  - At c = 1 with the measured lengths of 50, 61, 79, 152 and 221 (Measured),
    each piece is between 1 call in 225 and 1 in 54 of list k's calls: the
    share of any single unique listed once on that list, which is what a set
    piece listed there gets. Per kill it is that times the chance that the
    kill runs drop type 45, which is not established.
- **Mark 1's coin and rewrite.** A hit whose whole triple is a pushed
  stand-in's goes to that piece with probability c / (n + c), the same coin
  as above, and otherwise stays the game's own. The record is then rewritten
  to the piece's own definition, the game builds that base item, and the
  Mark 1 dressing makes it the piece.
- **What that gives on the Heroic roll** (arithmetic on the readings above,
  not measured):
  - With e pieces pushed at c copies, a piece's stand-in triple is kept with
    probability (n + c) / (T_H + e), and the coin gives the piece c / (n + c)
    of that. So each piece takes c / (T_H + e) of the Heroic roll's drops, and
    each stand-in keeps n / (T_H + e).
  - At c = 1 with all four pieces pushed, e = 4: each piece takes
    1 / (T_H + 4), one entry's share, as Headhunter and the flight charms get.
  - With the switch off nothing is pushed: no piece drops, and each stand-in
    keeps its own n / T_H.
  - On `lootListUnique[5]` the 380 entries, every one a triple, split into the
    T = 48 the Angelic roll keeps, the T_H the Heroic roll keeps, and the
    entries flagged hidden. So, if the Heroic roll reads list 5, T_H is at most
    380 - 48 = 332.
- **The draw push** (ForgePact#166 under `move: go`; `Mark1Drops.hpp`,
  `FlightCharms.hpp` and the adapter in ForgePact's `ModuleMain.cpp`, UP20).
  With "Mark 1 drops" or Pocket Elf's switch on, for the length of each
  outermost `DropItem` call, every resolved draw stand-in goes onto each of
  `lootListUnique[0]` to `[5]`, c times, and comes off its tail afterwards.
  - The stand-ins are pushed through DropManager's one `DropItem` detour, and
    k is recorded through raredrop's one `LoadSatanicDropTier` detour (after
    raredrop's lift, if any) for the innermost `DropItem` call in progress.
  - A draw stand-in is a triple of the item's own class on any of lists 0 to 5
    that the draw keeps as read: rarity 6 with fields 40 and 41 clear. Mark 1
    prefers an SS (tier 5) one and falls back below SS only for a class with
    none (`kDrawPrefersSs`); Pocket Elf takes tier 5 only (`kElfDrawTier`),
    the rarity and tier of Aimbot.exe. Then the smallest largest count over
    the six lists, then the lowest sub-type and base. There is no
    equal-count rule.
  - c is a `constexpr` 1 in the player build (`kPlayerCopies` through
    `g_Mark1DropCopies`, and `g_FlightDropCopies`); only the research build's
    copies levers change it, up to 400.
  - A roll nested in the call (#74's Angelic roll, `DropUniqueItems`, the
    Heroic hook) sees the lists without the call's entries.
- **The draw's coin.** A typed hit on a stand-in's whole triple is the item's
  with probability c / (n_k + c), k the call's recorded tier and n_k the
  stand-in's own count on list k; with no tier recorded the hit is refused
  (`tier-unread=`). Each hit in a call is settled before the next.
- **What that gives on the draw** (arithmetic on the readings above, not
  measured; the model's `draw_share` with the coin as a test transform):
  - The stand-in triple is kept with (n_k + c) * a / (W_k + p), and the coin
    hands the item c / (n_k + c) of that, so each item takes c * a / (W_k + p)
    of the draw's builds from list k, whichever k it was, and the stand-in
    keeps n_k * a / (W_k + p).
  - Kept as read (a = 1), with all four pieces and Pocket Elf on at c = 1,
    p = 5 and each item takes 1 / (W_k + 5): one entry's share of that list.
  - A pushed SS entry is kept far less often than that (Measured), so a
    piece's or Pocket Elf's SS share is c * a / (W_k + p) with a well below 1.
    The rate the player text states comes from ForgePact#166's Live 2, not
    from this arithmetic.
  - Switched off nothing is pushed, and each entry keeps its r * a / W_k.

## Not established

- **T at the time of #74's counts, and T elsewhere.** The flight charms'
  Mod live 2 measured T = 48 on 2026-10-13 (Measured). #74's counts of
  2026-10-02 came before that reading, so their replays still accept any T
  from 40 to 60, and 48 is among the values that fit them all; the flight
  charms' replays use 48. Whether T differs by difficulty, season or a game
  patch is not measured, so the model keeps T a parameter.
- **m**, the exact number of droppable vanilla entries sharing either stand-in's
  pair. It is 2 or 3: Liquor Holster's own entry, Mask of the Celestial's, and
  the type 10 unique that shares 0/51 if that one is droppable.
- **Whether the ordinary roll's random index can equal the sub-list's length.**
  If it can, that index reads no triple and the call drops nothing, so every
  share above becomes r / (L_k + 1) instead of r / L_k.
- **How k is chosen for each ordinary unique-roll call.** RDM § 23.4 names a
  protected zone value with a random chance of stepping up; its distribution is
  not measured.
- **D_k**, how many entries of each sub-list the ordinary roll keeps.
- **The Angelic roll's natural chance per kill.** A hit at the natural chance
  has not been observed (RDM § 13.4); every measured hit used the research
  chance lever.
- **Indirect calls.** A routine can also be called by index, which the direct
  call-site scans cannot see. None has been observed.
- **Which sub-list a vault's Heroic roll reads**, so which T_H applies. T_H
  was measured as 203 on list 5 and 218 on list 4 (Mod live 4, UP21, above),
  but a vault starts at list 4 and moves to 5 on a check whose bound was not
  read. The model keeps T_H a parameter; one piece is about one Heroic roll
  in two hundred either way.
- **The index `VaultUse` passes**, and the Chaos Tower NPC's, and the calling
  instance each passes. Its body was not read (RDM § 23.4).
- **Which Heroic uniques of classes 0, 1, 2 and 4 the list holds**, by name.
  Each stand-in's n and whether every piece has a stand-in are measured on
  this game build (Mod live 4: a stand-in for every class on lists 5 and 4,
  n = 1), not on another. The Item Editor's catalog lists 13, 15, 17 and 17
  Heroic uniques of those classes, which is not a reading of the game's list.
- **How often a player opens a vault or uses that NPC**, so how often the
  Heroic roll runs in play.
- **How often a kill runs drop type 45**, so how often a kill reaches the
  ordinary unique roll. Its gate (RDM § 13.1) was neither read nor measured
  for type 45, so the kill route's shares are per call, not per kill.
- **k's distribution** on the kill route, as above: which sub-list a call
  reads is not measured, so a piece's share is given for each list.
- **Which lists hold set items**, Sacred's and Zealot's Prophecy's pieces
  among them, and so whether each piece class has a kill-route stand-in with
  the same n on all five lists. ForgePact#166's Live procedure 2
  (`pool-kill`) reads it.
- **Each entry's acceptance a on the draw**, and so W_k. Which rarity branch
  keeps an entry was not read, nor what the tier-5 test compares. A pushed SS
  stand-in's a is well below 1 (Measured) and its value is not measured; at
  W_k = L_k an a of 1/100 fits Live 1c's count. The model keeps both inputs.
- **Whether the draw weighs its entries.** Measured `first-kept` rests on 12
  natural builds' reads and 3 lever builds. If a later session reads
  `weighed`, the share has no formula here: `draw_share` then takes a measured
  pick rate as its input, and the coin still applies on top, because a
  stand-in's copies and its natural copies are one triple.
- **What the draw does when its counter of about 500 runs out.**
- **How often a kill runs the draw, and k's distribution per kill.** The
  answers counted in Mod live 7 are per `DropItem` call, in Hell at zone
  levels 243 to 245, and Live 1's surplus of answers over calls is not
  explained.
- **Why Aimbot.exe was built outside `DropItem`** (8 times in Live 1c, scope
  `outside`), which is a route this spec does not cover.

## The model

Pure functions of numbers, stdlib only, with exact fractions
([`unique_pick_model.py`](../../hs-game-sdk/python/hs_game_sdk/unique_pick_model.py)).
It is not exported from `hs_game_sdk/__init__.py`, which the SDK generator owns.

- **The Angelic share**: an entry's share of the Angelic roll's drops is its
  copies over the droppable entries, r / T. The test passes T + e and the
  pushed copies in as transforms.
- **The ordinary pick**: the chance that one ordinary unique-roll call drops a
  given droppable entry is its copies over the sub-list's length, r / L_k.
- **The ordinary drop chance**: the chance that one call drops anything is the
  droppable entries over the length, D_k / L_k.
- **The Heroic keep test** (`heroic_keeps`): an entry not flagged hidden whose
  rarity is neither 7 nor 10.
- **The Heroic share** (`heroic_share`): an entry's share of the Heroic roll's
  drops is its copies over the entries the roll keeps, r / T_H. The test
  passes T_H + e and the pushed copies in as transforms.
- **The kill share** (`kill_share`): a pushed item's share of one ordinary
  unique-roll call on sub-list k, c / (L_k + p), with p the entries pushed onto
  that list in all; c / (L_k + p + 1) when the index can reach the length. It
  is the one draw over the lengthened list; the test checks that the push and
  the coin give the same number for any n.
- **The draw's redraw test** (`draw_redraws`): field 40 or 41 set. The lists
  it can read are `DRAW_LIST_INDICES`, 0 to 5, and its counter
  `DRAW_LOOP_BUDGET`, 500.
- **The draw share** (`draw_share`): under `first-kept`, an entry's share of
  the draw's builds from list k is r * a / (W_k + p), with r its entries on
  the list, a their acceptance and p the kept weight pushed for the call;
  r * a / W_k with nothing pushed. Under `weighed` or `not-observed` the
  formula is not established, and it returns the measured pick rate it is
  given, which it then requires.
- **The draw's empty chance** (`draw_runs_out_chance`): (1 - W / L) ** 500,
  the chance a call keeps nothing within its counter, apart from the share.
- **Agreement with a count**: the binomial helpers come from
  [`drop_roll_model`](../../hs-game-sdk/python/hs_game_sdk/drop_roll_model.py)
  (`binomial_band`, `observation_within`), imported and not copied.

The baseline (switches off) is the stand-in's own share n / T and no mod item.
The target applies the push and the coin: each item takes c / (T + e), the
stand-in keeps n / (T + e), and Pocket Elf takes c / (L_k + c). Each of #74's
measured entries in the fixture is replayed within the 3-sigma band for one T
in 40..60, with `standinPicks=` read as m / T and (m + c) / (T + c). The flight
charms' entries are replayed at the measured T = 48 and their measured n, with
Pocket Elf's band taken over the five lengths L_k, since which sub-list a call
reads is not established; each keeps a negative control (the other copies
setting, or no push).

For the Heroic roll the baseline (the "Mark 1 drops" switch off) is no piece
and each stand-in at n / T_H, and the target is each piece at c / (T_H + e),
1 / (T_H + 4) in the player build. T_H stays a parameter, so the tests run
over several values, and Mod live 4's counts (UP21) are replayed at the
measured T_H = 203, with the other copies setting and the switch off as
negative controls; Mod live 5's (UP22) are replayed on the kill route's
share over UP6's five lengths. The flight charms' ten by-name calls (UP14) are replayed:
every call placed one item, and every rarity measured is one the Heroic test
keeps. Their negative control is the Angelic test, which rejects every one of
those rarities.

For the kill route the baseline (the switch off) is no piece and every entry
of list k at 1 / L_k, and Pocket Elf alone unchanged at c / (L_k + c). The
target is each piece at c / (L_k + 4c), and c / (L_k + 4c + e) with Pocket Elf
on too, the shares and the empty draws adding up to every call. The measured
lengths give each piece between 1 in 225 and 1 in 54 at c = 1. k and how often
a kill runs drop type 45 stay parameters.

For the draw inside `DropItem` the baseline (every switch off,
`test_draw_baseline_*`) is the draw from list k with nothing pushed: an entry
r times among the kept weight W_k comes out r * a / W_k, the draw redraws on
fields 40 and 41, and the counter does not change the share. The target
(`test_draw_target_*`) applies the push onto lists 0 to 5 and the coin: the
coin c / (n_k + c) is exact for every k from 0 to 5 and refuses a hit with no
tier, each item takes c * a / (W_k + p), the shares add up to every build, and
switched off is the baseline; under `weighed` the measured pick rate is the
input. Mod live 7's counts are replayed (UP15 to UP19): the route and k, the
tier answers, the reads that read `first-kept`, Live 1b's below-SS lever
within the 3-sigma band at a = 1 with no push as the negative control, and
Live 1c's 2 SS stand-ins in 105 builds, which a = 1 cannot give and an
acceptance well below 1 can. `LeverParityTests` pins the push onto lists 0 to
5, the player build's one copy, the coin's k from the recorded tier and the
stand-in rule to ForgePact's source.

## What the model cannot catch

- **Whether a hook attaches.** The push, the typing and the rewrite need inline
  detours on `DropItemAngelicChance`, `DropUniqueItems`, `DropItemHeroic`,
  `CreateDefaultParams`, `GetUniqueRepoStruct` and `CreateItemNew`. Only a live
  positive control shows that they fired.
- **Typing.** The model assumes a hit is attributed to the entry that was
  picked. That rests on the typing hook reading the right definition, which
  Live 1 to Live 3 of #74 measured for the game's own entries.
- **The RNG sequence.** The model gives shares; the game's own random sequence,
  and whether successive picks are independent, are a live question.
- **How a rate feels in play.** One entry's share is a rate per roll; how often
  a player sees a charm also depends on how often each roll runs, which the
  model does not cover. For the Mark 1 pieces that is how often a kill runs
  drop type 45, and how often a player opens a vault, neither of which any
  session has measured. On the draw it is how often a kill's `DropItem` call
  builds a unique at all, and the SS acceptance a, which only ForgePact#166's
  Live 2 kill counts measure.
- **The draw's hooks.** The draw push needs DropManager's `DropItem` detour
  and raredrop's `LoadSatanicDropTier` detour to be inline, and the tier to be
  recorded for the right call; only a live positive control shows that.

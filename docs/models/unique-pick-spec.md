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

It was written from the shared references only:
[`docs/RUNTIME_DATA_MODELS.md`](../RUNTIME_DATA_MODELS.md) (RDM) § 13.4, § 23.4
and § 23.8, and ForgePact's own source for the Our code section.

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
- **L_k**: the length of `lootListUnique[k]`, for k from 0 to 4, the ordinary
  unique roll's sub-lists. **k is always a sub-list index in this spec.**
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
- **The two rolls read different sub-lists.** The Angelic roll reads index 5;
  the ordinary unique roll reads 0 to 4. Other routines read the same lists
  (RDM § 13.4, "Other readers of the list"), which is why ForgePact takes its
  entries off again after each roll.

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

## What the model cannot catch

- **Whether a hook attaches.** The push, the typing and the rewrite need inline
  detours on `DropItemAngelicChance`, `DropUniqueItems`, `CreateDefaultParams`,
  `GetUniqueRepoStruct` and `CreateItemNew`. Only a live positive control shows
  that they fired.
- **Typing.** The model assumes a hit is attributed to the entry that was
  picked. That rests on the typing hook reading the right definition, which
  Live 1 to Live 3 of #74 measured for the game's own entries.
- **The RNG sequence.** The model gives shares; the game's own random sequence,
  and whether successive picks are independent, are a live question.
- **How a rate feels in play.** One entry's share is a rate per roll; how often
  a player sees a charm also depends on how often each roll runs, which the
  model does not cover.

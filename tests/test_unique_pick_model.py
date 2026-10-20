"""Which unique a unique roll yields, modelled from a written spec and checked
against numbers ForgePact already measured (ForgePact#158, hub #500).

`hs_game_sdk.unique_pick_model` models the game only: the Angelic roll's
re-drawing pick, the ordinary unique roll's one draw, and the Heroic roll's
re-drawing pick (`DropItemHeroic`, added for the Mark 1 pieces of ForgePact#166,
hub #518; the `test_heroic_*` and `test_up14_*` tests). The Mark 1 pieces join
the ordinary unique roll too, the kill route (`kill_share`, the `test_kill_*`
tests). ForgePact's levers
(the stand-in entries pushed for the length of one roll, and the coin that
hands a stand-in hit to the mod's item) are our own code, so they are written
here as input transforms and never enter the SDK. `LeverParityTests` pins these
transforms to ForgePact's source when ForgePact is checked out.

Baseline: what the game does with no mod. Target: what the levers must turn it
into, one entry's share of each roll per switched-on item. That is the order
`AGENTS.md` § "Mod Development Workflow" asks for.

Each entry of `hs-game-sdk/curated/unique_pick_measurements.json` names the
test that reproduces it (`reproduced_by`), or says why it cannot be reproduced
(`not_reproduced`). The mechanism, in our own words, is
`docs/models/unique-pick-spec.md`.

Run from the hub root: `py -3 -m unittest tests.test_unique_pick_model -v`.
"""

import functools
import json
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
FIXTURE = ROOT / "hs-game-sdk" / "curated" / "unique_pick_measurements.json"
ANGELIC_LIST_FIXTURE = ROOT / "hs-game-sdk" / "curated" / "angelic_list_measurements.json"
FLIGHT_FIXTURE = ROOT / "hs-game-sdk" / "curated" / "flight_charms_measurements.json"
MODEL_FILE = SDK_PY / "hs_game_sdk" / "unique_pick_model.py"
SPEC_DOC = ROOT / "docs" / "models" / "unique-pick-spec.md"
HOOKS_DIR = ROOT / ".claude" / "hooks"
FORGEPACT = ROOT / "ForgePact"
FORGEPACT_PLUGIN = FORGEPACT / "plugin" / "ModuleMain.cpp"
FORGEPACT_FLIGHT = FORGEPACT / "plugin" / "include" / "ForgePact" / "FlightCharms.hpp"
FORGEPACT_MARK1_DROPS = FORGEPACT / "plugin" / "include" / "ForgePact" / "Mark1Drops.hpp"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import drop_roll_model  # noqa: E402
from hs_game_sdk import unique_pick_model as model  # noqa: E402

# T, the droppable entries on the Angelic list, was not established when #74's
# counts were made. A claim about those has to hold across this range, and a
# replay has to fit one T in it. The flight charms' Mod live 2 `pool` (UP11)
# measured T at 48; the flight charms' own replays use that value.
T_RANGE = range(40, 61)
# m, the droppable vanilla entries sharing either #74 stand-in's sub and b, is
# 2 or 3 (spec "Not established"): a replay accepts any share between the two.
M_LOW, M_HIGH = 2, 3
# n of Liquor Holster's triple on lootListUnique[5] (spec "Measured").
LIQUOR_HOLSTER_N = 1


@functools.lru_cache(maxsize=None)
def _fixture():
    # Parsed once per run; no test writes to it.
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _entries():
    return {entry["id"]: entry for entry in _fixture()["measurements"]}


def _measured_t():
    """T as Mod live 2's `flightprobe pool` read it (UP11)."""
    return _entries()["UP11"]["values"]["droppable"]


def _ordinary_lengths():
    """L_k for the ordinary roll's sub-lists [0] to [4], as #74 Live 2 read them (UP6)."""
    return _entries()["UP6"]["values"]["sub_list_lengths"][:5]


# ---- ForgePact's levers, as input transforms (our code, not the game's) ----

# Which list each switched-on item pushes its stand-in onto: #74's two
# signature items and #158's two Angelic charms onto the Angelic list, Pocket
# Elf onto each of the ordinary roll's lists and never inside the Angelic roll.
ANGELIC_ITEMS = ("headhunter", "tyrants_crown", "gabriel_wings", "witchs_broomstick")
ORDINARY_ITEMS = ("pocket_elf",)
PLAYER_COPIES = 1        # `g_SigCopies` and `g_FlightDropCopies` under FORGEPACT_RELEASE


def pushed(list_index, switched_on, copies=PLAYER_COPIES):
    """e: how many entries ForgePact adds to `lootListUnique[list_index]` for
    one roll, `copies` per switched-on item that pushes onto that list."""
    if list_index == model.ANGELIC_LIST_INDEX:
        owners = ANGELIC_ITEMS
    elif list_index in model.UNIQUE_SUB_LISTS:
        # Pocket Elf and, on the kill route, each Mark 1 piece that has a
        # stand-in there (`MARK1_PIECES`, below).
        owners = ORDINARY_ITEMS + MARK1_PIECES
    else:
        return 0
    return sum(copies for item in switched_on if item in owners)


def coin(n, c):
    """The share of a hit on a pushed stand-in's whole triple that goes to the
    mod's item: c / (n + c), n the vanilla entries carrying that triple."""
    if n < 0 or c <= 0:
        return Fraction(0)
    return Fraction(c, n + c)


def item_angelic_share(droppable, n, c, e):
    """A pushed item's share of the Angelic roll's drops: its stand-in triple
    is kept with (n + c) / (T + e), and the coin hands c / (n + c) of that over."""
    return model.angelic_share(n + c, droppable + e) * coin(n, c)


def stand_in_angelic_share(droppable, n, c, e):
    """What the stand-in itself keeps of the Angelic roll's drops."""
    return model.angelic_share(n + c, droppable + e) * (1 - coin(n, c))


def elf_ordinary_chance(length, n, c, **kwargs):
    """Pocket Elf's chance per ordinary unique-roll call on a list of `length`."""
    return model.ordinary_pick_chance(n + c, length + c, **kwargs) * coin(n, c)


# Mark 1 (#166): while the "Mark 1 drops" switch is on, one stand-in per piece
# that has one on the list is pushed for the length of one `DropItemHeroic`
# call, onto the list that call reads, and nothing inside the Angelic or the
# ordinary roll.
MARK1_PIECES = ("mark1_helmet", "mark1_body", "mark1_boots", "mark1_gloves")
# T_H, the entries the Heroic roll keeps, is not measured (spec "Not
# established"), so a claim about it has to hold across these values. The
# largest is the 380 - 48 entries of list 5 the Angelic roll does not keep
# (spec "Our code", "What that gives on the Heroic roll").
T_H_VALUES = (40, 150, 300, 332)


def heroic_pushed(drops_on, resolved=MARK1_PIECES, copies=PLAYER_COPIES):
    """e for one Heroic roll: `copies` per Mark 1 piece that has a stand-in on
    the list the call reads (`resolved`), and nothing with the switch off."""
    if not drops_on:
        return 0
    return sum(copies for piece in resolved if piece in MARK1_PIECES)


def piece_heroic_share(droppable, n, c, e):
    """A pushed piece's share of the Heroic roll's drops: its stand-in triple
    is kept with (n + c) / (T_H + e), and the coin hands c / (n + c) of that over."""
    return model.heroic_share(n + c, droppable + e) * coin(n, c)


def stand_in_heroic_share(droppable, n, c, e):
    """What a piece's stand-in itself keeps of the Heroic roll's drops."""
    return model.heroic_share(n + c, droppable + e) * (1 - coin(n, c))


# The kill route (#166, the owner's 2026-10-20 route): with the switch on, one
# stand-in per piece that has one is pushed onto each of the ordinary roll's
# lists for the length of one `DropUniqueItems` call, beside Pocket Elf's, in
# the one detour both features share. Each feature pushes only with its own
# switch on.
def kill_pushed(drops_on, elf_on=False, resolved=MARK1_PIECES, copies=PLAYER_COPIES,
                elf_copies=PLAYER_COPIES):
    """p for one ordinary unique-roll call: what `pushed` gives on one of
    lists 0..4 for the switched-on items, the pieces at `copies` each and
    Pocket Elf at `elf_copies`."""
    pieces = pushed(0, resolved if drops_on else (), copies=copies)
    elf =pushed(0, ORDINARY_ITEMS if elf_on else (), copies=elf_copies)
    return pieces + elf


def piece_kill_share(length, n, c, p, **kwargs):
    """A pushed piece's share of one ordinary unique-roll call on a list of
    `length`: its stand-in triple is drawn with (n + c) / (L_k + p), and the
    coin hands c / (n + c) of that over."""
    if c == 0:
        return Fraction(0)
    return model.ordinary_pick_chance(n + c, length + p, **kwargs) * coin(n, c)


def stand_in_kill_share(length, n, c, p, **kwargs):
    """What a piece's kill-route stand-in itself keeps of those calls."""
    return model.ordinary_pick_chance(n + c, length + p, **kwargs) * (1 - coin(n, c))


class BaselineTests(unittest.TestCase):
    """The game with no mod: the spec's static reading, as numbers."""

    def test_the_stand_in_keeps_its_own_share_and_no_mod_item_drops(self):
        for droppable in T_RANGE:
            with self.subTest(T=droppable):
                self.assertEqual(model.angelic_share(LIQUOR_HOLSTER_N, droppable),
                                 Fraction(LIQUOR_HOLSTER_N, droppable))
                e = pushed(model.ANGELIC_LIST_INDEX, ())
                self.assertEqual(e, 0)
                self.assertEqual(stand_in_angelic_share(droppable, LIQUOR_HOLSTER_N, 0, e),
                                 Fraction(LIQUOR_HOLSTER_N, droppable))
                self.assertEqual(item_angelic_share(droppable, LIQUOR_HOLSTER_N, 0, e), 0)

    def test_an_entry_listed_r_times_comes_out_r_in_t(self):
        self.assertEqual(model.angelic_share(3, 47), Fraction(3, 47))
        # Shares over a whole list's droppable entries add up to every drop.
        listing = [1] * 44 + [3]
        self.assertEqual(sum(model.angelic_share(r, sum(listing)) for r in listing), 1)

    def test_the_angelic_roll_keeps_only_angelic_and_unholy_entries_that_are_not_hidden(self):
        self.assertEqual(model.ANGELIC_RARITIES, frozenset({7, 10}))
        for rarity in range(0, 17):
            with self.subTest(rarity=rarity):
                self.assertEqual(model.angelic_keeps(rarity, False), rarity in (7, 10))
                self.assertFalse(model.angelic_keeps(rarity, True))

    def test_the_ordinary_roll_keeps_only_rarities_below_seven_that_are_not_hidden(self):
        for rarity in range(0, 17):
            with self.subTest(rarity=rarity):
                self.assertEqual(model.ordinary_keeps(rarity, False), rarity < 7)
                self.assertFalse(model.ordinary_keeps(rarity, True))

    def test_the_two_rolls_read_different_lists(self):
        self.assertEqual(model.ANGELIC_LIST_INDEX, 5)
        self.assertEqual(model.UNIQUE_SUB_LISTS, (0, 1, 2, 3, 4))
        self.assertNotIn(model.ANGELIC_LIST_INDEX, model.UNIQUE_SUB_LISTS)

    def test_the_ordinary_roll_makes_one_draw(self):
        # No re-draw: an entry it does not keep is a call that drops nothing.
        self.assertEqual(model.ordinary_pick_chance(1, 50), Fraction(1, 50))
        self.assertEqual(model.ordinary_drop_chance(40, 50), Fraction(4, 5))
        self.assertEqual(1 - model.ordinary_drop_chance(40, 50), Fraction(1, 5))
        self.assertEqual(model.ordinary_drop_chance(0, 50), 0)
        self.assertEqual(model.ordinary_drop_chance(50, 50), 1)

    def test_an_index_past_the_end_is_a_parameter_not_a_guess(self):
        # Not established: whether the random index can equal the length.
        self.assertEqual(model.ordinary_pick_chance(1, 50, index_can_reach_length=True), Fraction(1, 51))
        self.assertEqual(model.ordinary_drop_chance(50, 50, index_can_reach_length=True), Fraction(50, 51))

    def test_an_angelic_list_with_nothing_droppable_refuses(self):
        # The roll would draw again for ever.
        with self.assertRaises(ValueError):
            model.angelic_share(0, 0)

    def test_bad_inputs_are_refused(self):
        for call in (lambda: model.angelic_share(-1, 47),
                     lambda: model.angelic_share(48, 47),
                     lambda: model.ordinary_pick_chance(1, 0),
                     lambda: model.ordinary_pick_chance(51, 50),
                     lambda: model.ordinary_drop_chance(-1, 50),
                     lambda: model.ordinary_drop_chance(51, 50)):
            with self.assertRaises(ValueError):
                call()
        with self.assertRaises(TypeError):
            model.angelic_share(1.5, 47)
        with self.assertRaises(TypeError):
            model.ordinary_pick_chance(True, 50)

    def test_every_share_is_exact(self):
        self.assertIsInstance(model.angelic_share(1, 47), Fraction)
        self.assertIsInstance(model.ordinary_pick_chance(1, 50), Fraction)
        self.assertIsInstance(model.ordinary_drop_chance(1, 50), Fraction)

    def test_the_binomial_helpers_are_drop_roll_models_own(self):
        # Imported, not copied (spec "The model").
        self.assertIs(model.binomial_band, drop_roll_model.binomial_band)
        self.assertIs(model.observation_within, drop_roll_model.observation_within)

    # ---- The Heroic roll (`DropItemHeroic`), Mark 1's "Mark 1 drops" switch off ----

    def test_heroic_baseline_the_switch_off_drops_no_piece(self):
        e = heroic_pushed(False)
        self.assertEqual(e, 0)
        for droppable in T_H_VALUES:
            for n in (0, 1, 2):
                with self.subTest(T_H=droppable, n=n):
                    self.assertEqual(piece_heroic_share(droppable, n, 0, e), 0)

    def test_heroic_baseline_each_stand_in_keeps_n_over_t_h(self):
        e = heroic_pushed(False)
        for droppable in T_H_VALUES:
            for n in (1, 2, 3):
                with self.subTest(T_H=droppable, n=n):
                    self.assertEqual(model.heroic_share(n, droppable), Fraction(n, droppable))
                    self.assertEqual(stand_in_heroic_share(droppable, n, 0, e), Fraction(n, droppable))

    def test_heroic_baseline_the_roll_keeps_satanic_and_heroic_and_refuses_angelic_unholy_and_hidden(self):
        self.assertTrue(model.heroic_keeps(6, False))
        self.assertTrue(model.heroic_keeps(9, False))
        for rarity in (7, 10):
            with self.subTest(rarity=rarity):
                self.assertFalse(model.heroic_keeps(rarity, False))
        for rarity in range(0, 17):
            with self.subTest(rarity=rarity):
                self.assertEqual(model.heroic_keeps(rarity, False), rarity not in (7, 10))
                self.assertFalse(model.heroic_keeps(rarity, True))

    def test_heroic_baseline_the_two_re_drawing_rolls_split_a_list_between_them(self):
        # An entry not flagged hidden is kept by exactly one of the two rolls.
        for rarity in range(0, 17):
            for hidden in (False, True):
                with self.subTest(rarity=rarity, hidden=hidden):
                    kept_by = int(model.angelic_keeps(rarity, hidden)) + int(model.heroic_keeps(rarity, hidden))
                    self.assertEqual(kept_by, 0 if hidden else 1)

    def test_heroic_baseline_the_default_list_is_five_and_t_h_fits_on_it(self):
        self.assertEqual(model.HEROIC_DEFAULT_LIST_INDEX, 5)
        # On list 5 the entries the Angelic roll does not keep bound T_H (UP11).
        pool = _entries()["UP11"]["values"]
        self.assertEqual(pool["angelic_list_size"] - pool["droppable"], max(T_H_VALUES))

    def test_heroic_baseline_a_list_with_nothing_kept_and_bad_inputs_refuse(self):
        # The roll would draw again for ever.
        with self.assertRaises(ValueError):
            model.heroic_share(0, 0)
        for call in (lambda: model.heroic_share(-1, 300), lambda: model.heroic_share(301, 300)):
            with self.assertRaises(ValueError):
                call()
        for call in (lambda: model.heroic_share(1.5, 300), lambda: model.heroic_share(True, 300),
                     lambda: model.heroic_share(1, 300.0)):
            with self.assertRaises(TypeError):
                call()
        self.assertIsInstance(model.heroic_share(1, 300), Fraction)

    # ---- The kill route (`DropUniqueItems`), Mark 1's "Mark 1 drops" switch off ----

    def test_kill_baseline_the_switch_off_drops_no_piece(self):
        for elf_on in (False, True):
            p = kill_pushed(False, elf_on=elf_on)
            self.assertEqual(p, 1 if elf_on else 0)
            for length in _ordinary_lengths():
                for n in (0, 1, 2):
                    with self.subTest(elf=elf_on, L=length, n=n):
                        self.assertEqual(piece_kill_share(length, n, 0, p), 0)
                        self.assertEqual(model.kill_share(0, length, p), 0)

    def test_kill_baseline_every_entry_keeps_one_over_l_k(self):
        p = kill_pushed(False)
        for length in _ordinary_lengths():
            for n in (1, 2, 3):
                with self.subTest(L=length, n=n):
                    self.assertEqual(model.ordinary_pick_chance(1, length + p), Fraction(1, length))
                    # A would-be stand-in keeps its own n / L_k.
                    self.assertEqual(stand_in_kill_share(length, n, 0, p), Fraction(n, length))

    def test_kill_baseline_pocket_elf_alone_is_unchanged(self):
        p = kill_pushed(False, elf_on=True)
        self.assertEqual(p, pushed(0, ORDINARY_ITEMS))
        for length in _ordinary_lengths():
            for n in (0, 1, 3):
                with self.subTest(L=length, n=n):
                    self.assertEqual(model.kill_share(PLAYER_COPIES, length, p), Fraction(1, length + 1))
                    self.assertEqual(model.kill_share(PLAYER_COPIES, length, p),
                                     elf_ordinary_chance(length, n, PLAYER_COPIES))
        # Mark 1 adds nothing to the Angelic list, on or off.
        self.assertEqual(pushed(model.ANGELIC_LIST_INDEX, MARK1_PIECES), 0)

    def test_kill_baseline_bad_inputs_refuse(self):
        for call in (lambda: model.kill_share(-1, 50, 4),
                     lambda: model.kill_share(1, -1, 4),
                     lambda: model.kill_share(1, 50, -1),
                     lambda: model.kill_share(5, 50, 4),        # more copies than were pushed
                     lambda: model.kill_share(0, 0, 0)):        # an empty list: no draw to read
            with self.assertRaises(ValueError):
                call()
        for call in (lambda: model.kill_share(1.5, 50, 4), lambda: model.kill_share(True, 50, 4),
                     lambda: model.kill_share(1, 50.0, 4), lambda: model.kill_share(1, 50, 4.0)):
            with self.assertRaises(TypeError):
                call()
        self.assertIsInstance(model.kill_share(1, 50, 4), Fraction)


class TargetTests(unittest.TestCase):
    """What the push and the coin must give: one entry's share per item."""

    def test_each_flight_charm_takes_one_entrys_share_of_the_angelic_roll(self):
        switched_on = ("gabriel_wings", "witchs_broomstick")
        for droppable in T_RANGE:
            e = pushed(model.ANGELIC_LIST_INDEX, switched_on)
            self.assertEqual(e, 2)
            for n in (0, 1, 2):
                with self.subTest(T=droppable, n=n):
                    share = item_angelic_share(droppable, n, PLAYER_COPIES, e)
                    self.assertEqual(share, Fraction(1, droppable + 2))
                    # The same share as a vanilla unique listed once.
                    self.assertEqual(share, model.angelic_share(1, droppable + e))
        # At the measured T of 48 (UP11), one drop in 50.
        self.assertEqual(item_angelic_share(_measured_t(), 1, 1, 2), Fraction(1, 50))

    def test_the_stand_in_keeps_its_own_entries_share(self):
        for droppable in T_RANGE:
            for n in (1, 2, 3):
                with self.subTest(T=droppable, n=n):
                    self.assertEqual(stand_in_angelic_share(droppable, n, 1, 2), Fraction(n, droppable + 2))

    def test_headhunter_the_crown_and_both_charms_each_take_one_entrys_share(self):
        e = pushed(model.ANGELIC_LIST_INDEX, ANGELIC_ITEMS + ORDINARY_ITEMS)
        self.assertEqual(e, 4)
        for droppable in T_RANGE:
            with self.subTest(T=droppable):
                self.assertEqual(item_angelic_share(droppable, LIQUOR_HOLSTER_N, 1, e),
                                 Fraction(1, droppable + 4))

    def test_the_shares_still_add_up_to_every_drop(self):
        droppable, n, e = 47, 1, 2
        vanilla_elsewhere = model.angelic_share(droppable - 2 * n, droppable + e)
        stand_ins = 2 * stand_in_angelic_share(droppable, n, 1, e)
        items = 2 * item_angelic_share(droppable, n, 1, e)
        self.assertEqual(vanilla_elsewhere + stand_ins + items, 1)

    def test_pocket_elf_takes_one_call_in_l_plus_one(self):
        for length in _ordinary_lengths():
            for n in (0, 1, 3):
                with self.subTest(L=length, n=n):
                    self.assertEqual(elf_ordinary_chance(length, n, PLAYER_COPIES), Fraction(1, length + 1))

    def test_pocket_elf_adds_nothing_to_the_angelic_roll(self):
        self.assertEqual(pushed(model.ANGELIC_LIST_INDEX, ORDINARY_ITEMS), 0)
        for index in model.UNIQUE_SUB_LISTS:
            self.assertEqual(pushed(index, ORDINARY_ITEMS), 1)
            self.assertEqual(pushed(index, ANGELIC_ITEMS), 0)

    def test_the_ordinary_roll_drops_more_often_only_by_the_elfs_entry(self):
        for length, kept in ((50, 40), (221, 200)):
            with self.subTest(L=length):
                c = pushed(0, ORDINARY_ITEMS)
                self.assertEqual(model.ordinary_drop_chance(kept + c, length + c), Fraction(kept + 1, length + 1))
                self.assertEqual(model.ordinary_drop_chance(kept + c, length + c) - model.ordinary_drop_chance(kept, length + c),
                                 elf_ordinary_chance(length, 1, c))

    def test_the_copies_lever_multiplies_both_shares(self):
        # `flightprobe copies 200`: c / (T + 2c) on the Angelic roll with both
        # charms on, and c / (L_k + c) on the ordinary one.
        c = 200
        for droppable in T_RANGE:
            e = pushed(model.ANGELIC_LIST_INDEX, ("gabriel_wings", "witchs_broomstick"), copies=c)
            share = item_angelic_share(droppable, 1, c, e)
            self.assertEqual(share, Fraction(c, droppable + 2 * c))
            self.assertTrue(0.43 < share < 0.46, (droppable, float(share)))
        for length in _ordinary_lengths():
            share = elf_ordinary_chance(length, 1, c)
            self.assertEqual(share, Fraction(c, length + c))
            self.assertTrue(0.47 < share <= 0.8, (length, float(share)))

    def test_switched_off_is_the_baseline(self):
        for index in (model.ANGELIC_LIST_INDEX,) + model.UNIQUE_SUB_LISTS:
            self.assertEqual(pushed(index, ()), 0)
        self.assertEqual(coin(1, 0), 0)
        self.assertEqual(stand_in_angelic_share(47, 1, 0, 0), model.angelic_share(1, 47))
        self.assertEqual(elf_ordinary_chance(50, 1, 0), 0)

    # ---- The Heroic roll with "Mark 1 drops" on: one entry's share per piece ----

    def test_heroic_target_each_piece_takes_one_entrys_share(self):
        e = heroic_pushed(True)
        self.assertEqual(e, 4)
        for droppable in T_H_VALUES:
            for n in (0, 1, 2):
                with self.subTest(T_H=droppable, n=n):
                    share = piece_heroic_share(droppable, n, PLAYER_COPIES, e)
                    self.assertEqual(share, Fraction(1, droppable + 4))
                    # The same share as a vanilla unique listed once.
                    self.assertEqual(share, model.heroic_share(1, droppable + e))

    def test_heroic_target_each_stand_in_keeps_n_over_t_h_plus_four(self):
        e = heroic_pushed(True)
        for droppable in T_H_VALUES:
            for n in (0, 1, 2, 3):
                with self.subTest(T_H=droppable, n=n):
                    self.assertEqual(stand_in_heroic_share(droppable, n, PLAYER_COPIES, e), Fraction(n, droppable + 4))

    def test_heroic_target_the_shares_add_up_to_every_drop(self):
        e = heroic_pushed(True)
        ns = (1, 2, 0, 3)   # each piece's stand-in, listed a different number of times
        for droppable in T_H_VALUES:
            with self.subTest(T_H=droppable):
                vanilla_elsewhere = model.heroic_share(droppable - sum(ns), droppable + e)
                stand_ins = sum(stand_in_heroic_share(droppable, n, PLAYER_COPIES, e) for n in ns)
                pieces = sum(piece_heroic_share(droppable, n, PLAYER_COPIES, e) for n in ns)
                self.assertEqual(pieces, Fraction(4, droppable + 4))
                self.assertEqual(vanilla_elsewhere + stand_ins + pieces, 1)

    def test_heroic_target_the_copies_lever_scales_both_shares(self):
        # The research build's copies lever: c / (T_H + 4c) per piece.
        for c in (1, 7, 200, 400):
            e = heroic_pushed(True, copies=c)
            self.assertEqual(e, 4 * c)
            for droppable in T_H_VALUES:
                with self.subTest(c=c, T_H=droppable):
                    self.assertEqual(piece_heroic_share(droppable, 1, c, e), Fraction(c, droppable + 4 * c))
                    self.assertEqual(stand_in_heroic_share(droppable, 1, c, e), Fraction(1, droppable + 4 * c))
        # More copies, a larger share for each piece; never more than a quarter.
        at_one = piece_heroic_share(300, 1, 1, heroic_pushed(True))
        at_200 = piece_heroic_share(300, 1, 200, heroic_pushed(True, copies=200))
        self.assertGreater(at_200, at_one)
        self.assertLess(at_200, Fraction(1, 4))

    def test_heroic_target_a_class_with_no_stand_in_leaves_the_other_three(self):
        resolved = ("mark1_helmet", "mark1_body", "mark1_boots")   # no gloves stand-in on the list
        e = heroic_pushed(True, resolved=resolved)
        self.assertEqual(e, 3)
        for droppable in T_H_VALUES:
            with self.subTest(T_H=droppable):
                self.assertEqual(piece_heroic_share(droppable, 1, PLAYER_COPIES, e), Fraction(1, droppable + 3))
                # The gloves are not pushed, so they take nothing.
                self.assertEqual(piece_heroic_share(droppable, 1, 0, e), 0)

    def test_heroic_target_mark1_pushes_onto_the_heroic_and_the_ordinary_roll(self):
        # Mark 1 adds nothing to the Angelic roll ...
        self.assertEqual(pushed(model.ANGELIC_LIST_INDEX, MARK1_PIECES), 0)
        # ... pushes each piece onto every one of the ordinary roll's lists (the
        # kill route, owner 2026-10-20) ...
        for index in model.UNIQUE_SUB_LISTS:
            with self.subTest(k=index):
                self.assertEqual(pushed(index, MARK1_PIECES), len(MARK1_PIECES) * PLAYER_COPIES)
        # ... and #74's items and the flight charms add nothing to the Heroic roll.
        self.assertEqual(heroic_pushed(True, resolved=ANGELIC_ITEMS + ORDINARY_ITEMS), 0)
        self.assertEqual(heroic_pushed(True, resolved=MARK1_PIECES + ANGELIC_ITEMS), 4)

    # ---- The kill route with "Mark 1 drops" on: one entry's share per piece ----

    def test_kill_target_each_piece_takes_c_over_l_plus_4c_on_every_list(self):
        p = kill_pushed(True)
        self.assertEqual(p, 4)
        for length in _ordinary_lengths():
            for n in (0, 1, 2):
                with self.subTest(L=length, n=n):
                    share = piece_kill_share(length, n, PLAYER_COPIES, p)
                    self.assertEqual(share, Fraction(1, length + 4))
                    self.assertEqual(share, model.kill_share(PLAYER_COPIES, length, p))
                    # The same share as a vanilla unique listed once on the lengthened list.
                    self.assertEqual(share, model.ordinary_pick_chance(1, length + p))
                    self.assertEqual(stand_in_kill_share(length, n, PLAYER_COPIES, p), Fraction(n, length + 4))

    def test_kill_target_with_pocket_elf_each_piece_takes_c_over_l_plus_4c_plus_e(self):
        for c, e in ((1, 1), (1, 200), (200, 1), (7, 3)):
            p = kill_pushed(True, elf_on=True, copies=c, elf_copies=e)
            self.assertEqual(p, 4 * c + e)
            for length in _ordinary_lengths():
                with self.subTest(c=c, e=e, L=length):
                    for n in (0, 1, 2):
                        self.assertEqual(piece_kill_share(length, n, c, p), Fraction(c, length + 4 * c + e))
                    self.assertEqual(model.kill_share(c, length, p), Fraction(c, length + 4 * c + e))
                    # Pocket Elf keeps its own entry's share of the lengthened list.
                    self.assertEqual(model.kill_share(e, length, p), Fraction(e, length + 4 * c + e))
                    self.assertEqual(elf_ordinary_chance(length + 4 * c, 0, e), Fraction(e, length + 4 * c + e))

    def test_kill_target_the_shares_and_the_empty_draws_add_up_to_every_call(self):
        ns = (1, 0, 2, 0)   # each piece's stand-in, listed a different number of times
        for elf_on in (False, True):
            p = kill_pushed(True, elf_on=elf_on)
            for length, kept in ((50, 40), (61, 61), (221, 200)):
                with self.subTest(elf=elf_on, L=length, D=kept):
                    pieces = sum(piece_kill_share(length, n, PLAYER_COPIES, p) for n in ns)
                    stand_ins = sum(stand_in_kill_share(length, n, PLAYER_COPIES, p) for n in ns)
                    elf = model.kill_share(PLAYER_COPIES, length, p) if elf_on else 0
                    # The stand-ins are among the D_k entries the roll keeps.
                    vanilla_elsewhere = model.ordinary_pick_chance(kept - sum(ns), length + p)
                    empty = 1 - model.ordinary_drop_chance(kept + p, length + p)
                    self.assertEqual(pieces, Fraction(4, length + p))
                    self.assertEqual(empty, Fraction(length - kept, length + p))
                    self.assertEqual(pieces + stand_ins + elf + vanilla_elsewhere + empty, 1)

    def test_kill_target_the_copies_lever_scales_the_shares(self):
        for c in (1, 7, 200, 400):
            p = kill_pushed(True, copies=c)
            self.assertEqual(p, 4 * c)
            for length in _ordinary_lengths():
                with self.subTest(c=c, L=length):
                    self.assertEqual(piece_kill_share(length, 1, c, p), Fraction(c, length + 4 * c))
                    self.assertEqual(stand_in_kill_share(length, 1, c, p), Fraction(1, length + 4 * c))
                    self.assertEqual(model.kill_share(c, length, p), Fraction(c, length + 4 * c))
        # More copies, a larger share for each piece; never more than a quarter.
        at_one = model.kill_share(1, 50, kill_pushed(True))
        at_200 = model.kill_share(200, 50, kill_pushed(True, copies=200))
        self.assertGreater(at_200, at_one)
        self.assertLess(at_200, Fraction(1, 4))

    def test_kill_target_a_class_with_no_stand_in_leaves_the_other_three(self):
        resolved = ("mark1_helmet", "mark1_body", "mark1_gloves")   # no boots stand-in on the lists
        p = kill_pushed(True, resolved=resolved)
        self.assertEqual(p, 3)
        for length in _ordinary_lengths():
            with self.subTest(L=length):
                self.assertEqual(piece_kill_share(length, 0, PLAYER_COPIES, p), Fraction(1, length + 3))
                # The boots are not pushed, so they take nothing.
                self.assertEqual(piece_kill_share(length, 0, 0, p), 0)
        # The Heroic roll's push is its own: the boots' Heroic stand-in, if any, still counts there.
        self.assertEqual(heroic_pushed(True), 4)

    def test_kill_target_up6_lengths_give_a_piece_between_1_in_225_and_1_in_54(self):
        lengths = _ordinary_lengths()
        self.assertEqual(lengths, [50, 61, 79, 152, 221])
        p = kill_pushed(True)
        shares = [model.kill_share(PLAYER_COPIES, length, p) for length in lengths]
        self.assertEqual(max(shares), Fraction(1, 54))
        self.assertEqual(min(shares), Fraction(1, 225))
        # Negative control: the switch off gives no piece on any list.
        self.assertEqual({model.kill_share(0, length, kill_pushed(False)) for length in lengths}, {0})
        # With an index that can reach the length, one more empty draw per list.
        self.assertEqual(model.kill_share(PLAYER_COPIES, 50, p, index_can_reach_length=True), Fraction(1, 55))
        self.assertEqual(piece_kill_share(50, 1, PLAYER_COPIES, p, index_can_reach_length=True), Fraction(1, 55))


class MeasuredTests(unittest.TestCase):
    """The model against #74's counts, for one T in 40..60."""

    @classmethod
    def setUpClass(cls):
        cls.entries = _entries()

    def _band(self, entry, droppable):
        """The share range `standinPicks=` grows at for this entry and T: m / T
        with nothing pushed, (m + c) / (T + c) with Headhunter alone at c."""
        values = entry["values"]
        c = values.get("copies", 0)
        low = model.angelic_share(M_LOW + c, droppable + c)
        high = model.angelic_share(M_HIGH + c, droppable + c)
        return float(low), float(high)

    def _within(self, entry, droppable, band=None):
        values = entry["values"]
        low, high = band or self._band(entry, droppable)
        return model.observation_within(values["standin_picks"], values["hits"], low, high)

    def _fitting_ts(self, *ids):
        return [t for t in T_RANGE if all(self._within(self.entries[i], t) for i in ids)]

    def test_one_t_in_40_to_60_fits_every_measured_count(self):
        fitting = self._fitting_ts("UP1", "UP2", "UP3", "UP4", "UP5")
        self.assertTrue(fitting)
        # T as Mod live 2's `flightprobe pool` measured it (UP11).
        self.assertIn(_measured_t(), fitting)
        self.assertEqual(_measured_t(), 48)

    def test_up1_live1_nothing_pushed(self):
        self.assertEqual(self.entries["UP1"]["values"]["pushed"], 0)
        self.assertTrue(self._fitting_ts("UP1"))

    def test_up2_live2_nothing_pushed(self):
        self.assertEqual(self.entries["UP2"]["values"]["pushed"], 0)
        self.assertTrue(self._fitting_ts("UP2"))

    def test_up3_live3_nothing_pushed(self):
        self.assertEqual(self.entries["UP3"]["values"]["pushed"], 0)
        self.assertTrue(self._fitting_ts("UP3"))

    def _pushed_and_drawn(self, key):
        entry = self.entries[key]
        values = entry["values"]
        self.assertEqual(values["copies"], 200)
        self.assertEqual(values["items_pushed"], 1)
        self.assertEqual(values["held_miss"], 0)
        self.assertEqual(values["injected"], values["copies"] * values["rolls"])
        self.assertTrue(self._fitting_ts(key))
        # Negative control: a push the roll did not draw leaves the vanilla share.
        for droppable in T_RANGE:
            vanilla = (float(model.angelic_share(M_LOW, droppable)), float(model.angelic_share(M_HIGH, droppable)))
            self.assertFalse(self._within(entry, droppable, vanilla), droppable)

    def test_up4_live2_headhunter_at_200_copies(self):
        self._pushed_and_drawn("UP4")

    def test_up5_live3_headhunter_at_200_copies(self):
        self._pushed_and_drawn("UP5")

    def test_the_baselines_reject_a_push_that_was_never_made(self):
        # The other way round: 1 to 2 picks in about 50 hits cannot be a 200-copy push.
        for key in ("UP1", "UP2", "UP3"):
            entry = self.entries[key]
            for droppable in T_RANGE:
                pushed_band = (float(model.angelic_share(M_LOW + 200, droppable + 200)),
                               float(model.angelic_share(M_HIGH + 200, droppable + 200)))
                self.assertFalse(self._within(entry, droppable, pushed_band), (key, droppable))

    def test_up6_the_sub_list_lengths(self):
        values = self.entries["UP6"]["values"]
        lengths = values["sub_list_lengths"]
        self.assertEqual(len(lengths), 6)
        self.assertEqual(values["angelic_sub_list"], model.ANGELIC_LIST_INDEX)
        self.assertEqual(tuple(values["unique_roll_sub_lists"]), model.UNIQUE_SUB_LISTS)
        self.assertEqual(values["liquor_holster_count_on_5"], LIQUOR_HOLSTER_N)
        # Every T the replays accept fits on the Angelic list.
        self.assertLessEqual(max(T_RANGE), lengths[model.ANGELIC_LIST_INDEX])
        ordinary = [lengths[k] for k in model.UNIQUE_SUB_LISTS]
        chances = [model.ordinary_pick_chance(1, length + 1) for length in ordinary]
        self.assertEqual(max(chances), Fraction(1, 51))
        self.assertEqual(min(chances), Fraction(1, 222))
        for length in ordinary:
            self.assertEqual(model.ordinary_pick_chance(200, length + 200), Fraction(200, length + 200))

    # ---- #158's own counts (Mod live 1 and Mod live 2) ----

    def _elf_band(self, copies, n):
        """Pocket Elf's chance per call, over the five lists the roll may read."""
        chances = [elf_ordinary_chance(length, n, copies) for length in _ordinary_lengths()]
        return float(min(chances)), float(max(chances))

    def _elf_within(self, values, band):
        return model.observation_within(values["elf"], values["calls"], *band)

    def _angelic_within(self, count, hits, share):
        return model.observation_within(count, hits, float(share), float(share))

    def test_up11_mod_live2_pool_pins_t(self):
        values = self.entries["UP11"]["values"]
        droppable = _measured_t()
        self.assertEqual(droppable, 48)
        self.assertIn(droppable, T_RANGE)
        self.assertLessEqual(droppable, values["angelic_list_size"])
        # The list layout is #74's, unchanged.
        lengths = self.entries["UP6"]["values"]["sub_list_lengths"]
        self.assertEqual(values["angelic_list_size"], lengths[model.ANGELIC_LIST_INDEX])
        self.assertEqual(values["unique_sizes"], lengths[:5])
        # Every #74 count still fits at the measured T.
        self.assertIn(droppable, self._fitting_ts("UP1", "UP2", "UP3", "UP4", "UP5"))
        # n: once each for the Angelic stand-ins, nowhere for Pocket Elf's.
        self.assertEqual((values["water_melon"], values["soul_collector"]), (1, 1))
        self.assertEqual(values["aimbot_counts"], [0] * len(model.UNIQUE_SUB_LISTS))
        self.assertEqual(coin(1, PLAYER_COPIES), Fraction(1, 2))
        self.assertEqual(coin(0, PLAYER_COPIES), 1)
        # So each flight charm takes one entry's share: 1 in 50 with both on.
        e = pushed(model.ANGELIC_LIST_INDEX, ("gabriel_wings", "witchs_broomstick"))
        self.assertEqual(item_angelic_share(droppable, 1, PLAYER_COPIES, e), Fraction(1, 50))

    def test_up9_mod_live1_elf_at_200_copies(self):
        values = self.entries["UP9"]["values"]
        c, n = values["copies"], values["standin_n"]
        self.assertEqual((c, n), (200, 0))
        self.assertEqual(values["injected"], values["calls"] * pushed(0, ORDINARY_ITEMS, copies=c) * values["sub_lists_pushed"])
        self.assertEqual(values["elf_ours"], values["elf_built"])
        self.assertEqual((values["refused"], values["anomalies"]), (0, 0))
        self.assertLessEqual(values["elf"], values["placed"])
        band = self._elf_band(c, n)
        self.assertEqual(band, (200 / 421, 200 / 250))
        self.assertTrue(self._elf_within(values, band))
        # Negative controls: the player build's one copy, and no push at all.
        self.assertFalse(self._elf_within(values, self._elf_band(PLAYER_COPIES, n)))
        self.assertFalse(self._elf_within(values, (0.0, 0.0)))

    def test_up10_mod_live1_angelic_at_200_copies(self):
        values = self.entries["UP10"]["values"]
        c, n = values["copies"], values["standin_n"]
        e = pushed(model.ANGELIC_LIST_INDEX, ("gabriel_wings", "witchs_broomstick", "pocket_elf"), copies=c)
        self.assertEqual(e, 400)   # Pocket Elf's switch was on too, and adds nothing here
        self.assertEqual(values["injected"], values["rolls"] * e)
        share = item_angelic_share(_measured_t(), n, c, e)
        self.assertEqual(share, Fraction(200, 448))
        for key in ("wings", "broom"):
            with self.subTest(item=key):
                self.assertTrue(self._angelic_within(values[key], values["hits"], share))
                self.assertTrue(self._angelic_within(values["first_read"][key], values["first_read"]["hits"], share))
                # Negative control: the player build's one copy each.
                one = item_angelic_share(_measured_t(), n, PLAYER_COPIES, 2)
                self.assertFalse(self._angelic_within(values[key], values["hits"], one))
        self.assertEqual((values["refused"], values["anomalies"]), (0, 0))

    def test_up12_mod_live2_rate_elf(self):
        values = self.entries["UP12"]["values"]
        c, n = values["copies"], values["standin_n"]
        self.assertEqual((c, n), (PLAYER_COPIES, 0))
        self.assertEqual(values["injected"], values["calls"] * pushed(0, ORDINARY_ITEMS) * values["sub_lists_pushed"])
        self.assertEqual(values["elf_ours"], values["elf_built"])
        self.assertEqual((values["refused"], values["anomalies"]), (0, 0))
        self.assertGreaterEqual(values["placed"], 50)
        self.assertEqual(values["control_elf"], 0)
        band = self._elf_band(c, n)
        self.assertEqual(band, (1 / 222, 1 / 51))
        self.assertTrue(self._elf_within(values, band))
        # Negative control: Mod live 1's 200 copies.
        self.assertFalse(self._elf_within(values, self._elf_band(200, n)))
        # The "appeared at all" check, not a share control: without the push
        # Pocket Elf's share is 0, a zero-width band any non-zero count fails.
        self.assertFalse(self._elf_within(values, (0.0, 0.0)))

    def test_up13_mod_live2_rate_angelic(self):
        values = self.entries["UP13"]["values"]
        c, n = values["copies"], values["standin_n"]
        self.assertEqual(values["droppable"], _measured_t())
        e = pushed(model.ANGELIC_LIST_INDEX, ("gabriel_wings", "witchs_broomstick"), copies=c)
        self.assertEqual(e, values["items_pushed"] * c)
        self.assertEqual(values["injected"], values["rolls"] * e)
        share = item_angelic_share(values["droppable"], n, c, e)
        self.assertEqual(share, Fraction(1, 50))
        low, high = model.binomial_band(values["hits"], float(share))
        self.assertAlmostEqual(low, -2.2018, places=3)
        self.assertAlmostEqual(high, 6.2818, places=3)
        for key in ("wings", "broom"):
            with self.subTest(item=key):
                self.assertTrue(self._angelic_within(values[key], values["hits"], share))
                # Negative control: Mod live 1's 200 copies each.
                flood = item_angelic_share(values["droppable"], n, 200, 400)
                self.assertFalse(self._angelic_within(values[key], values["hits"], flood))
        # The "appeared at all" check, not a share control: without the push
        # the Broomstick's share is 0, a zero-width band that any non-zero
        # count fails, so this shows only that the Broomstick push reached a
        # drop. It runs for the Broomstick alone; 0 Wings cannot tell a Wings
        # push from none (UP13's `model`).
        self.assertFalse(self._angelic_within(values["broom"], values["hits"], 0))
        self.assertEqual((values["refused"], values["anomalies"]), (0, 0))

    # ---- The Heroic roll called by name (#158 Live 1, for #166) ----

    def test_up14_heroic_route_by_name(self):
        entry = self.entries["UP14"]
        values = entry["values"]
        # Copied from the flight charms' fixture; the two copies must not drift apart.
        route = json.loads(FLIGHT_FIXTURE.read_text(encoding="utf-8"))["heroic_route"]
        for key in ("calls", "placed", "rarity_histogram", "charms"):
            with self.subTest(key=key):
                self.assertEqual(values[key], route[key])
        self.assertEqual(entry["date"], route["date"])
        self.assertEqual(values["pushed"], 0)
        # The roll draws again until it keeps an entry, so every call places one item.
        self.assertEqual(values["placed"], values["calls"])
        histogram = {int(rarity): count for rarity, count in values["rarity_histogram"].items()}
        self.assertEqual(sum(histogram.values()), values["placed"])
        self.assertEqual(set(histogram), {6, 9})
        for rarity in histogram:
            with self.subTest(rarity=rarity):
                self.assertTrue(model.heroic_keeps(rarity, False))
                # Negative control: an Angelic-only filter rejects every measured rarity.
                self.assertFalse(model.angelic_keeps(rarity, False))
        # The control can fire: the Angelic filter keeps what the Heroic roll refuses.
        for rarity in model.ANGELIC_RARITIES:
            self.assertTrue(model.angelic_keeps(rarity, False))
            self.assertFalse(model.heroic_keeps(rarity, False))
        # Only this roll keeps a Heroic (9) unique; the ordinary roll's test refuses it.
        self.assertFalse(model.ordinary_keeps(9, False))


class OurCodeTests(unittest.TestCase):
    """The fixture's two our-code contracts, through the transforms above."""

    @classmethod
    def setUpClass(cls):
        cls.entries = _entries()

    def test_up7_the_push(self):
        values = self.entries["UP7"]["values"]
        self.assertEqual(values["player_copies"], PLAYER_COPIES)
        self.assertEqual((values["research_copies_min"], values["research_copies_max"]), (1, 400))
        self.assertEqual(values["angelic_list_index"], model.ANGELIC_LIST_INDEX)
        self.assertEqual(tuple(values["unique_sub_lists"]), model.UNIQUE_SUB_LISTS)
        # One stand-in per item that pushes, on either roll.
        self.assertEqual(set(values["stand_ins"]), set(ANGELIC_ITEMS + ORDINARY_ITEMS))
        for c in (values["player_copies"], values["research_copies_max"]):
            with self.subTest(c=c):
                self.assertEqual(pushed(model.ANGELIC_LIST_INDEX, ANGELIC_ITEMS, copies=c), 4 * c)
                for index in model.UNIQUE_SUB_LISTS:
                    self.assertEqual(pushed(index, ORDINARY_ITEMS, copies=c), c)
        # Switched off, nothing is added to any list.
        for index in range(6):
            self.assertEqual(pushed(index, ()), 0)

    def test_up8_the_coin(self):
        values = self.entries["UP8"]["values"]
        self.assertEqual(values["share"], "c / (n + c)")
        examples = values["examples"]
        self.assertEqual(float(coin(1, 1)), examples["n1_c1"])
        self.assertAlmostEqual(float(coin(1, 200)), examples["n1_c200"], places=15)
        self.assertEqual(float(coin(0, 1)), examples["n0_c1"])
        for droppable in (40, 47, 60):
            for n in (0, 1, 3):
                for c in (1, 7, 200):
                    e = c + 1
                    with self.subTest(T=droppable, n=n, c=c):
                        self.assertEqual(item_angelic_share(droppable, n, c, e), Fraction(c, droppable + e))
                        self.assertEqual(stand_in_angelic_share(droppable, n, c, e), Fraction(n, droppable + e))
                        self.assertEqual(elf_ordinary_chance(152, n, c), Fraction(c, 152 + c))


class FixtureShapeTests(unittest.TestCase):
    """`hs-game-sdk/curated/unique_pick_measurements.json` stays checkable."""

    REQUIRED = ("id", "kind", "status", "date", "source", "scripts", "what", "values", "model")

    @classmethod
    def setUpClass(cls):
        cls.data = _fixture()
        cls.entries = cls.data["measurements"]

    def test_every_entry_has_the_required_fields(self):
        self.assertIn("$schema_note", self.data)
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({f"UP{i}" for i in range(1, 15)} <= set(ids))
        for entry in self.entries:
            for field in self.REQUIRED:
                self.assertIn(field, entry, entry.get("id"))
            self.assertIn(entry["kind"], ("baseline", "target", "our_code"), entry["id"])
            self.assertIn(entry["status"], ("measured", "our_code"), entry["id"])
            self.assertEqual(entry["kind"] == "our_code", entry["status"] == "our_code", entry["id"])
            self.assertRegex(entry["date"], r"^\d{4}-\d{2}-\d{2}$", entry["id"])
            self.assertEqual(("reproduced_by" in entry) + ("not_reproduced" in entry), 1,
                             f"{entry['id']} needs exactly one of reproduced_by / not_reproduced")

    def test_sub_list_lengths_agree_with_the_angelic_list_fixture(self):
        # UP6 and UP11 retype the lengths angelic_list_measurements.json
        # recorded first (#74 Live 2); the two copies must not drift apart.
        layout = json.loads(ANGELIC_LIST_FIXTURE.read_text(encoding="utf-8"))["list_layout"]
        sizes = layout["other_elements"]["sizes"]
        ordinary = [sizes[str(k)] for k in model.UNIQUE_SUB_LISTS]
        by_id = {e["id"]: e for e in self.entries}
        self.assertEqual(by_id["UP6"]["values"]["sub_list_lengths"], ordinary + [layout["sub_list_size"]])
        self.assertEqual(by_id["UP11"]["values"]["unique_sizes"], ordinary)
        self.assertEqual(by_id["UP11"]["values"]["angelic_list_size"], layout["sub_list_size"])

    def test_every_named_test_exists_in_this_module(self):
        prefix = "tests.test_unique_pick_model."
        for entry in self.entries:
            if "reproduced_by" not in entry:
                continue
            dotted = entry["reproduced_by"]
            self.assertTrue(dotted.startswith(prefix), dotted)
            class_name, method = dotted[len(prefix):].split(".")
            cls = globals().get(class_name)
            self.assertIsNotNone(cls, dotted)
            self.assertTrue(callable(getattr(cls, method, None)), dotted)
            self.assertTrue(method.startswith("test_"), dotted)
            # A replay that skips without ForgePact would leave the entry unchecked in hub CI.
            self.assertIsNot(cls, LeverParityTests, dotted)

    def test_every_script_is_bound_in_the_sdk(self):
        from hs_game_sdk.scripts import GameScript
        for entry in self.entries:
            self.assertTrue(entry["scripts"], entry["id"])
            for name in entry["scripts"]:
                self.assertIn(name, GameScript.__members__, f"{entry['id']}: {name}")

    def test_sources_are_paths_or_commits(self):
        for entry in self.entries:
            self.assertTrue(entry["source"], entry["id"])
            for source in entry["source"]:
                self.assertTrue(("path" in source) != ("commit" in source), (entry["id"], source))
                if "commit" in source:
                    self.assertRegex(source["commit"], r"^[0-9a-f]{7,40}$", entry["id"])
                if "path" in source:
                    # The live captures are gitignored; the fixture never cites them.
                    self.assertNotIn(".claude/workorders/", source["path"], entry["id"])

    def test_source_paths_exist_where_they_can_be_checked(self):
        # Hub CI checks out without submodules, so a ForgePact path is only
        # checked where ForgePact is initialised.
        forgepact_present = (FORGEPACT / "docs").is_dir()
        checked = 0
        for entry in self.entries:
            for source in entry["source"]:
                if "path" not in source:
                    continue
                if source["path"].startswith("ForgePact/") and not forgepact_present:
                    continue
                path = ROOT / source["path"]
                self.assertTrue(path.is_file(), f"{entry['id']}: {source['path']}")
                if "section" in source:
                    self.assertIn(source["section"], path.read_text(encoding="utf-8"),
                                  f"{entry['id']}: {source['path']}")
                checked += 1
        self.assertGreater(checked, 0)


class NoDecompilerOutputTests(unittest.TestCase):
    """The model was built clean-room from the spec; nothing it ships may carry listing text."""

    FILES = (MODEL_FILE, FIXTURE, SPEC_DOC, Path(__file__).resolve())

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(HOOKS_DIR))
        from decompiled_output import SIGNATURES
        cls.signatures = SIGNATURES

    def _matches(self, text):
        return [what for pattern, what in self.signatures
                for line in text.splitlines() if pattern.search(line)]

    def test_the_instrument_can_fire(self):
        # Positive control, built at runtime so this file carries no sample.
        ghidra_like = "call " + "FUN" + "_" + "0041a2b3" + "();"
        positional = "x = " + "argu" + "ment" + str(3) + ";"
        self.assertTrue(self._matches(ghidra_like))
        self.assertTrue(self._matches(positional))
        self.assertFalse(self._matches("the roll draws again until it keeps a droppable entry"))

    def test_no_signature_in_the_model_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), path)
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [])

    def test_no_local_decompiler_paths_in_the_model_files(self):
        forbidden = ("hs-" + "decomp", "ghidra" + "_projects")
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                self.assertNotIn(word, text, path)


class SpecTests(unittest.TestCase):
    def test_the_spec_labels_its_claims_and_names_the_model(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        for heading in ("## Static reading", "## Measured", "## Our code", "## Not established",
                        "## The model", "## What the model cannot catch"):
            self.assertIn("\n" + heading + "\n", spec)
        for name in ("unique_pick_model.py", "test_unique_pick_model.py", "unique_pick_measurements.json",
                     "DropItemAngelicChance", "DropUniqueItems", "lootListUnique",
                     "DropItemHeroic", "T_H", "Mark 1", "VaultUse"):
            self.assertIn(name, spec)

    def test_the_model_is_not_exported_from_the_generated_init(self):
        init = (SDK_PY / "hs_game_sdk" / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn("unique_pick_model", init)


def _function_body(source, signature):
    """The brace-balanced body of the definition (not a declaration) that
    starts with `signature` in C++ source."""
    match = re.search(re.escape(signature) + r"[^;{]*\{", source)
    if match is None:
        raise AssertionError(f"no definition: {signature}")
    depth = 0
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1]
    raise AssertionError(f"unterminated: {signature}")


@unittest.skipUnless(FORGEPACT_PLUGIN.is_file() and FORGEPACT_FLIGHT.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "so there is no lever source to compare the test transforms with")
class LeverParityTests(unittest.TestCase):
    """`pushed` and `coin` above are ForgePact's levers; pin them to its source."""

    @classmethod
    def setUpClass(cls):
        cls.plugin = FORGEPACT_PLUGIN.read_text(encoding="utf-8", errors="replace")
        cls.header = FORGEPACT_FLIGHT.read_text(encoding="utf-8", errors="replace")

    def test_both_copies_are_a_constexpr_one_in_the_player_build(self):
        for name in ("g_SigCopies", "g_FlightDropCopies"):
            with self.subTest(name=name):
                self.assertRegex(self.plugin,
                                 r"#ifdef FORGEPACT_RELEASE\s*\n\s*static constexpr int "
                                 + name + rf"\s*=\s*{PLAYER_COPIES}\s*;")

    def test_the_angelic_list_index_is_five_in_the_player_build(self):
        self.assertRegex(self.plugin, rf"static const int kAngelicListIndex\s*=\s*{model.ANGELIC_LIST_INDEX}\s*;")
        self.assertRegex(self.plugin,
                         r"#ifdef FORGEPACT_RELEASE\s*\n\s*static constexpr int g_SigListIndex\s*=\s*kAngelicListIndex\s*;")

    def test_74s_push_is_g_sig_copies_per_switched_on_item(self):
        body = _function_body(self.plugin, "static void SignatureInjectPush(")
        self.assertRegex(body, r"if\s*\(\s*!SignatureSwitchOn\(\s*w\s*\)\s*\)\s*continue\s*;")
        self.assertRegex(body, r"for\s*\(\s*int\s+c\s*=\s*0\s*;\s*c\s*<\s*g_SigCopies\b")

    def test_the_angelic_charms_push_onto_the_angelic_list_and_the_elf_does_not(self):
        body = _function_body(self.plugin, "static void FlightDropAngelicPush(")
        self.assertRegex(body, r"\{\s*FcNs::Charm::Wings\s*,\s*FcNs::Charm::Broom\s*\}")
        self.assertRegex(body, r"=\s*g_FlightDropCopies\s*;")
        self.assertRegex(body, r"const int indices\[1\]\s*=\s*\{\s*g_SigListIndex\s*\}\s*;")
        self.assertNotIn("Charm::Elf", body)

    def test_the_elf_pushes_onto_each_of_the_ordinary_lists(self):
        body = _function_body(self.plugin, "static void FlightDropUniquePush(")
        indices = ", ".join(str(k) for k in model.UNIQUE_SUB_LISTS)
        self.assertRegex(body, r"const int indices\[FcNs::kUniqueSubLists\]\s*=\s*\{\s*"
                         + re.escape(indices) + r"\s*\}\s*;")
        self.assertRegex(body, r"d\.rollCopies\[elf\]\s*=\s*g_FlightDropCopies\s*;")
        self.assertRegex(self.header, rf"constexpr int kUniqueSubLists\s*=\s*{len(model.UNIQUE_SUB_LISTS)}\s*;")

    def test_every_list_gets_the_copies_of_each_charm(self):
        body = _function_body(self.plugin, "static void FlightDropPushOnto(")
        self.assertRegex(body, r"for\s*\(\s*int\s+k\s*=\s*0\s*;\s*k\s*<\s*lists\b")
        self.assertRegex(body, r"for\s*\(\s*int\s+n\s*=\s*0\s*;\s*n\s*<\s*d\.rollCopies\[i\]")

    def test_the_coin_is_c_over_n_plus_c(self):
        body = _function_body(self.header, "inline double CoinShare(")
        self.assertRegex(body, r"if\s*\(\s*n\s*<\s*0\s*\|\|\s*c\s*<=\s*0\s*\)\s*return\s+0\.0\s*;")
        self.assertRegex(body, r"return\s+static_cast<double>\(\s*c\s*\)\s*/\s*static_cast<double>\(\s*n\s*\+\s*c\s*\)\s*;")

    # ---- Mark 1 (#166): `heroic_pushed` and the coin, against Mark1Drops.hpp ----

    def test_mark1_the_default_list_index_is_the_heroic_rolls(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        self.assertRegex(mark1, r"inline constexpr int kHeroicDefaultListIndex\s*=\s*"
                         + str(model.HEROIC_DEFAULT_LIST_INDEX) + r"\s*;")
        # Absent or undefined, the call reads that list.
        body = _function_body(mark1, "inline int ListIndexOf(")
        self.assertRegex(body, r"if\s*\(\s*kind\s*==\s*ArgKind::Absent\s*\|\|\s*kind\s*==\s*ArgKind::Undefined\s*\)"
                         r"\s*return\s+kHeroicDefaultListIndex\s*;")

    def test_mark1_the_player_builds_copies_are_one(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        self.assertRegex(mark1, rf"inline constexpr int kPlayerCopies\s*=\s*{PLAYER_COPIES}\s*;")
        self.assertEqual(heroic_pushed(True), PLAYER_COPIES * len(MARK1_PIECES))

    def test_mark1_the_roll_refuses_what_the_model_refuses(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"inline constexpr int kRefusedRarities\[kRefusedRarityCount\]\s*=\s*\{([^}]*)\}\s*;", mark1)
        self.assertIsNotNone(match)
        self.assertEqual({int(v) for v in match.group(1).split(",")}, set(model.HEROIC_REFUSED_RARITIES))
        self.assertRegex(_function_body(mark1, "inline bool HeroicKeeps("), r"if\s*\(\s*hidden\s*\)\s*return\s+false\s*;")

    def test_mark1_each_piece_pushes_its_copies_and_the_coin_is_c_over_n_plus_c(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        body = _function_body(mark1, "inline PushPlan PlanPush(")
        self.assertRegex(body, r"for\s*\(\s*int\s+i\s*=\s*0\s*;\s*i\s*<\s*kPieceCount\b")
        self.assertRegex(body, r"PushEntry\{\s*kPieces\[i\]\.piece\s*,\s*s\.triple\s*,\s*s\.n\s*,\s*copies\s*\}")
        coin_body = _function_body(mark1, "inline double CoinShare(")
        self.assertRegex(coin_body, r"if\s*\(\s*n\s*<\s*0\s*\|\|\s*c\s*<=\s*0\s*\)\s*return\s+0\.0\s*;")
        self.assertRegex(coin_body,
                         r"return\s+static_cast<double>\(\s*c\s*\)\s*/\s*static_cast<double>\(\s*n\s*\+\s*c\s*\)\s*;")
        self.assertEqual(coin(1, PLAYER_COPIES), Fraction(1, 2))

    # ---- Mark 1's kill route (#166): `kill_pushed` and the coin, against Mark1Drops.hpp ----

    def test_mark1_kill_pushes_onto_lists_0_to_4(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        self.assertRegex(mark1, rf"inline constexpr int kKillListCount\s*=\s*{len(model.UNIQUE_SUB_LISTS)}\s*;")
        match = re.search(r"inline constexpr int kKillLists\[kKillListCount\]\s*=\s*\{([^}]*)\}\s*;", mark1)
        self.assertIsNotNone(match)
        self.assertEqual(tuple(int(v) for v in match.group(1).split(",")), model.UNIQUE_SUB_LISTS)
        # Every pushed entry goes onto each of those lists.
        body = _function_body(mark1, "struct KillPushPlan")
        self.assertRegex(body, r"int EntryCount\(\) const \{\s*return\s+PerListCount\(\)\s*\*\s*kKillListCount\s*;\s*\}")

    def test_mark1_kill_filter_refuses_what_ordinary_keeps_refuses(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        self.assertRegex(mark1, rf"inline constexpr int kOrdinaryRarityBelow\s*=\s*{model.ORDINARY_RARITY_BELOW}\s*;")
        body = _function_body(mark1, "inline bool OrdinaryKeeps(")
        self.assertRegex(body, r"if\s*\(\s*hidden\s*\)\s*return\s+false\s*;\s*return\s+rarity\s*<\s*kOrdinaryRarityBelow\s*;")
        # The kill route's stand-in rule asks that filter, not the Heroic roll's.
        resolve = _function_body(mark1, "inline KillResolution ResolveKillStandIns(")
        self.assertIn("if (!OrdinaryKeeps(rarity, hidden)) continue;", resolve)
        self.assertNotIn("HeroicKeeps", resolve)
        # The model and that filter agree on every rarity a definition carries.
        below = int(re.search(r"kOrdinaryRarityBelow\s*=\s*(\d+)", mark1).group(1))
        for rarity in range(0, 12):
            for hidden in (False, True):
                with self.subTest(rarity=rarity, hidden=hidden):
                    self.assertEqual(model.ordinary_keeps(rarity, hidden), not hidden and rarity < below)

    def test_mark1_kill_the_player_builds_copies_are_one(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        self.assertRegex(mark1, rf"inline constexpr int kPlayerCopies\s*=\s*{PLAYER_COPIES}\s*;")
        # The kill route's plan takes the same copies the Heroic roll's does.
        body = _function_body(mark1, "inline KillPushPlan PlanKillPush(")
        self.assertRegex(body, r"if\s*\(\s*copies\s*<\s*1\s*\)\s*return\s+plan\s*;")
        self.assertEqual(kill_pushed(True), PLAYER_COPIES * len(MARK1_PIECES))
        self.assertEqual(kill_pushed(False), 0)

    def test_mark1_kill_coin_is_c_over_n_plus_c(self):
        mark1 = FORGEPACT_MARK1_DROPS.read_text(encoding="utf-8", errors="replace")
        body = _function_body(mark1, "inline KillPushPlan PlanKillPush(")
        self.assertRegex(body, r"for\s*\(\s*int\s+i\s*=\s*0\s*;\s*i\s*<\s*kPieceCount\b")
        self.assertRegex(body, r"PushEntry\{\s*kPieces\[i\]\.piece\s*,\s*s\.triple\s*,\s*s\.n\s*,\s*copies\s*\}")
        # n is the stand-in's count, the same on each of lists 0..4.
        resolve = _function_body(mark1, "inline KillResolution ResolveKillStandIns(")
        self.assertRegex(resolve, r"if\s*\(\s*n\s*!=\s*c\[0\]\s*\)\s*equal\s*=\s*false\s*;")
        self.assertRegex(resolve, r"if\s*\(\s*!equal\s*\)\s*continue\s*;")
        self.assertRegex(resolve, r"s\.n\s*=\s*c\[0\]\s*;")
        attribute = _function_body(mark1, "inline bool AttributeHit(const KillPushPlan& plan,")
        self.assertIn("AttributeHitAmong(plan.entries", attribute)
        among = _function_body(mark1, "inline bool AttributeHitAmong(")
        self.assertRegex(among, r"CoinOurs\(\s*e\.n\s*,\s*e\.copies\s*,\s*u\s*\)")
        coin_body = _function_body(mark1, "inline double CoinShare(")
        self.assertRegex(coin_body,
                         r"return\s+static_cast<double>\(\s*c\s*\)\s*/\s*static_cast<double>\(\s*n\s*\+\s*c\s*\)\s*;")
        # With the common count n on every list, each piece is c / (L_k + p) of
        # the calls that read list k: the model's kill_share.
        for length in (50, 61, 79, 152, 221):
            for n in (0, 1, 2):
                with self.subTest(length=length, n=n):
                    p = kill_pushed(True)
                    self.assertEqual(piece_kill_share(length, n, PLAYER_COPIES, p),
                                     model.kill_share(PLAYER_COPIES, length, p))
                    self.assertEqual(coin(n, PLAYER_COPIES), Fraction(PLAYER_COPIES, n + PLAYER_COPIES))


if __name__ == "__main__":
    unittest.main()

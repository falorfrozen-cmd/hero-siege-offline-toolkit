"""Checks for `hs_game_sdk.soul_piece_model` (ForgePact#197, boss soul pieces).

The model is written from `docs/models/soul-piece-spec.md` and covers the game
only: `RoomActIndex` gives a room its act, the pickup merges an item into a
stack by class, `b` and `c` (an incoming class outside 12 to 15 refused before
anything is compared, a stack capped at 999), `DropGems` rolls the Gem of
Incarnation against its rate once per dying source whose drop type 6 gate
passed, and a backpack use clears the item only when `PotionUse` answers true.
ForgePact's boss soul pieces are our code, so they live here as input
transforms (`piece_denominator`, `decide_drop`, `decide_use`,
`transfer_target` and the seed helpers): a piece is an Edible PAS Logo marked
by its seed, rolls inside that same gem roll at five quarters of the gem's
chance, in an act's ordinary rooms, from an ordinary monster, and its use moves
the player straight into the act's boss room (no portal: Live procedure 3's
portal failed and its direct `NetworkRoomGoto` passed). `ParityTests` pins
those transforms' constants, the act table, the room rules and the verdict
words to `SoulPieceMod.hpp` through the curated file, when ForgePact carries
the mod.

Baseline: what the game does with the mod off, including Live procedure 1's
measured merge of a key-base piece into the real key. Target: what the mod must
turn it into, including a consumable piece that never stacks. That is the order
`AGENTS.md` § "Mod Development Workflow" asks for. `CuratedTests` checks
`hs-game-sdk/curated/room_acts.json` and `hs-game-sdk/curated/boss_soul_pieces.json`
against the SDK's own tables.

Run from the hub root: `py -3 -m unittest tests.test_soul_piece_model -v`.
"""
import ast
import json
import math
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
CURATED = ROOT / "hs-game-sdk" / "curated" / "boss_soul_pieces.json"
ROOM_ACTS = ROOT / "hs-game-sdk" / "curated" / "room_acts.json"
MODEL_FILE = SDK_PY / "hs_game_sdk" / "soul_piece_model.py"
SPEC_DOC = ROOT / "docs" / "models" / "soul-piece-spec.md"
RUNTIME_DOC = ROOT / "docs" / "RUNTIME_DATA_MODELS.md"
HOOKS_DIR = ROOT / ".claude" / "hooks"
FORGEPACT_HEADER = ROOT / "ForgePact" / "plugin" / "include" / "ForgePact" / "SoulPieceMod.hpp"
LIVE_1 = "forgepact-197-boss-soul-pieces-live-1"
LIVE_3 = "forgepact-197-boss-soul-pieces-live-3"
LIVE_2 = "forgepact-197-boss-soul-pieces-live-2"
LIVE_4 = "forgepact-197-boss-soul-pieces-live-4"
#: The follow-up's research session (the key piece, its stack and its icon).
ICON_LIVE_1 = "forgepact-197-piece-icon-stack-live-1"
#: The follow-up's bag-stack session (the merge, the count drawn, the confirm on a stack).
ICON_LIVE_2 = "forgepact-197-piece-icon-stack-live-2"
#: The follow-up's save round trip (the stash's close saves the bag; counts kept).
ICON_LIVE_4 = "forgepact-197-piece-icon-stack-live-4"
#: The follow-up's player-build session.
ICON_LIVE_3 = "forgepact-197-piece-icon-stack-live-3"
#: Every session's capture a measured entry may name.
LIVE_CAPTURES = (LIVE_1, LIVE_2, LIVE_3, LIVE_4, ICON_LIVE_1, ICON_LIVE_2, ICON_LIVE_4, ICON_LIVE_3)
#: The rooms a session read RoomActIndex in, with the act and the capture.
MEASURED_ROOMS = {
    "Town_01_rm": (1, LIVE_1), "Act_01_01": (1, LIVE_1), "Act_02_01": (2, LIVE_1),
    "Town_02_rm": (2, LIVE_3), "Act_02_Boss": (2, LIVE_3), "Act_02_02": (2, LIVE_2),
}

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import soul_piece_model as model  # noqa: E402
from hs_game_sdk.objects import OBJECT_NAME_TO_INDEX, is_descendant_of  # noqa: E402
from hs_game_sdk.rooms import ROOM_NAME_TO_INDEX  # noqa: E402
from hs_game_sdk.scripts import GameScript  # noqa: E402
from hs_game_sdk.sprites import SPRITE_NAME_TO_INDEX  # noqa: E402

DATA = json.loads(CURATED.read_text(encoding="utf-8"))
ROOMS = json.loads(ROOM_ACTS.read_text(encoding="utf-8"))

# ---- ForgePact's boss soul pieces, as input transforms (our code, not the game's) ----

RATIO_NUMERATOR = 4
RATIO_DENOMINATOR = 5
SEED_BASE = 777100
ACT_COUNT = 9
#: A piece's base: the Edible PAS Logo (class 11; `b` 12 measured in Live procedure 1).
BASE_CLASS = 11
BASE_B = 12
DROP_VERDICTS = ("off", "no-act", "town", "boss-room", "not-monster", "boss-kill",
                 "unnamed", "no-rate", "hit", "miss")
USE_VERDICTS = ("off", "not-piece", "no-act", "boss-room", "unnamed", "transfer")
#: act -> (boss object, named); every shipped act is named.
ACTS = {row["act"]: (row["boss_object"], row["named"]) for row in DATA["acts"]}
#: act -> the boss room its piece takes the player to.
BOSS_ROOMS = {row["act"]: row["boss_room"] for row in DATA["acts"]}
#: A key piece's base: the Bifröst Key (class 12; index 2 measured in #197's
#: Live procedure 3, resolved by name at run time).
KEY_BASE_CLASS = 12
KEY_BASE_INDEX = 2
#: A key piece's `b` is the base's index + act / this.
ACT_FRACTION_DIVISOR = 10
#: How far a key piece's `b` (and its `c` from 0) may sit from the exact value.
KEY_PIECE_TOLERANCE = Fraction(1, 100)
#: The owner's own Bifröst Key, as the game holds it.
REAL_KEY = model.Item(KEY_BASE_CLASS, KEY_BASE_INDEX, 0, 767593635)


def piece_denominator(gem_rate):
    """D = max(1, floor(G x 4 / 5)); 0 (no piece) when G is unknown, zero or negative."""
    if gem_rate is None or gem_rate <= 0:
        return 0
    return max(1, math.floor(Fraction(gem_rate) * RATIO_NUMERATOR / RATIO_DENOMINATOR))


def piece_chance(gem_rate):
    """The piece's chance on one `DropGems` call: 1 in D, 0 without a rate."""
    d = piece_denominator(gem_rate)
    return Fraction(1, d) if d else Fraction(0)


def is_town(room):
    return room.startswith("Town_")


def is_boss_room(room):
    return "_Boss" in room or room.startswith("Uber_") or room.startswith("Dev_")


def room_refusal(room, act):
    """The word that refuses a room for drops, `None` when it is eligible."""
    if not 1 <= act <= ACT_COUNT:
        return "no-act"
    if is_town(room):
        return "town"
    if is_boss_room(room):
        return "boss-room"
    return None


def decide_drop(mod_on, forced, room, act, monster, boss, gem_rate, roll):
    """One `DropGems` call for a dying source; `roll` is uniform in [0, 1)."""
    if not mod_on:
        return "off"
    refusal = room_refusal(room, act)
    if refusal:
        return refusal
    if not monster:
        return "not-monster"
    if boss:
        return "boss-kill"
    if not ACTS.get(act, (None, False))[1]:
        return "unnamed"
    if forced:
        return "hit"
    d = piece_denominator(gem_rate)
    if not d:
        return "no-rate"
    return "hit" if Fraction(roll) < Fraction(1, d) else "miss"


def seed_of_act(act):
    return SEED_BASE + act if 1 <= act <= ACT_COUNT else 0


def act_of_seed(seed):
    act = seed - SEED_BASE
    return act if 1 <= act <= ACT_COUNT else 0


def piece_item(act, base_b=BASE_B):
    """A piece of `act` as the game holds it: an Edible PAS Logo with its seed."""
    return model.Item(BASE_CLASS, base_b, 0, seed_of_act(act))


def key_piece_b(act, base_index=KEY_BASE_INDEX):
    """A key piece's `b`: the key base's index + act/10 (2.1 .. 2.9 on index 2)."""
    return base_index + Fraction(act, ACT_FRACTION_DIVISOR)


def key_piece_item(act, base_index=KEY_BASE_INDEX):
    """A key piece of `act` as the game holds it: the key base's class, a `b`
    whose tenths are the act, `c` 0 and the act's seed."""
    return model.Item(KEY_BASE_CLASS, key_piece_b(act, base_index), 0, seed_of_act(act))


def key_piece_act(item, base_index=KEY_BASE_INDEX):
    """The act of an item that is a key piece, 0 otherwise: the key base's
    class, `c` within the tolerance of 0, a `b` that truncates to the base's
    index, is not whole, and sits within the tolerance of its seed's act."""
    if item.item_type != KEY_BASE_CLASS or abs(item.c) > KEY_PIECE_TOLERANCE:
        return 0
    if model.repository_index(item.b) != base_index or item.b - base_index <= KEY_PIECE_TOLERANCE:
        return 0
    act = act_of_seed(item.a)
    if not act or abs(item.b - key_piece_b(act, base_index)) > KEY_PIECE_TOLERANCE:
        return 0
    return act


def saved(item):
    """`item` after a save and reload: its `b` and `c` as the save writes them."""
    return item._replace(b=model.saved_number(item.b), c=model.saved_number(item.c))


def decide_use(mod_on, room, room_act, piece_act):
    """A confirmed right-click on an item in the backpack. Every word but
    `transfer` is a refusal, and the detour then answers `PotionUse` false."""
    if not mod_on:
        return "off"
    if not 1 <= piece_act <= ACT_COUNT:
        return "not-piece"
    if not 1 <= room_act <= ACT_COUNT:
        return "no-act"
    if is_boss_room(room):
        return "boss-room"
    if not ACTS.get(piece_act, (None, False))[1]:
        return "unnamed"
    return "transfer"


def transfer_target(piece_act):
    """The room a piece takes the player to: its act's boss room."""
    return BOSS_ROOMS.get(piece_act)


def _roll(value):
    """A case's roll as an exact fraction of its written decimal."""
    return Fraction(str(value))


def _cases(kind):
    return [c for c in DATA["cases"] if c["kind"] == kind]


def _drop(case, **override):
    c = dict(case, **override)
    return decide_drop(c["mod_on"], c["forced"], c["room"], c["act"], c["monster"], c["boss"],
                       c["gem_rate"], _roll(c["roll"]))


def _real(value):
    """A JSON number as the model takes it: whole, or an exact fraction of its
    written decimal."""
    return value if isinstance(value, int) else Fraction(str(value))


def _item(fields):
    return model.Item(fields["t"], _real(fields["b"]), _real(fields["c"]), fields["a"], fields.get("o", 1))


def _table_rooms():
    return {row["room"]: row["act"] for row in ROOMS["rooms"]}


class BaselineTests(unittest.TestCase):
    """The game with the mod off: acts, the stack rule, the gem roll, the
    backpack's use, and no piece at all."""

    def test_mod_off_never_drops(self):
        for room, act in _table_rooms().items():
            for forced in (False, True):
                for roll in (Fraction(0), Fraction(1, 10 ** 6), Fraction(1, 2)):
                    with self.subTest(room=room, forced=forced, roll=roll):
                        self.assertEqual(decide_drop(False, forced, room, act, True, False, 9000, roll), "off")
        for case in _cases("drop"):
            with self.subTest(case=case["id"]):
                self.assertEqual(_drop(case, mod_on=False), "off")

    def test_mod_off_never_transfers(self):
        for room, room_act in _table_rooms().items():
            for act in range(1, ACT_COUNT + 1):
                with self.subTest(room=room, act=act):
                    self.assertEqual(decide_use(False, room, room_act, act), "off")
        # A refusal answers PotionUse false, and the game then keeps the piece.
        self.assertFalse(model.item_used_up(False))

    def test_room_act_index_answers_the_act(self):
        self.assertEqual([model.act_of_room(i) for i in range(1, ACT_COUNT + 1)], list(range(1, 10)))
        self.assertIsNone(model.act_of_room(None))
        # Live procedure 3 read `bool:false` outside the switch (Act_01_Boss,
        # Act_01_Pregame): no act, the same as undefined.
        self.assertIsNone(model.act_of_room(False))
        self.assertIs(model.HYPOTHESES["room_outside_the_switch_is_undefined"], False)
        for bad in (0, -1, 10, True):
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError, TypeError)):
                    model.act_of_room(bad)
        # The sessions' readings: the answer is the room's act itself.
        measured = {r["room"]: r["act"] for r in ROOMS["rooms"] if r["status"] == "measured"}
        self.assertEqual(measured, {room: act for room, (act, _) in MEASURED_ROOMS.items()})
        for room, answer in measured.items():
            with self.subTest(room=room):
                self.assertEqual(model.act_of_room(answer), _table_rooms()[room])

    def test_a_key_piece_merges_with_the_real_key(self):
        # Live procedure 1: pieces built on a key definition merged on pickup into
        # the owner's own key stack. The seed is not compared, so marking a piece
        # by its seed cannot keep it apart on the Key tab.
        case = next(c for c in _cases("stack") if c["status"] == "measured")
        self.assertEqual(case["capture"], LIVE_1)
        self.assertTrue(case["stacks"])
        self.assertTrue(model.stacks(_item(case["held"]), _item(case["picked"])))
        real_key = model.Item(12, 30, 0, 767593635)
        for act in range(1, ACT_COUNT + 1):
            with self.subTest(act=act):
                key_piece = model.Item(12, 30, 0, seed_of_act(act))
                self.assertTrue(model.stacks(real_key, key_piece))
                self.assertTrue(model.stacks(key_piece, model.Item(12, 30, 0, seed_of_act(act % ACT_COUNT + 1))))
        # A whole `c` of 1 picks the unique repository, so it cannot mark a piece either.
        self.assertFalse(model.stacks(real_key, model.Item(12, 30, 1, seed_of_act(1))))
        self.assertTrue(model.uses_unique_repository(1))

    def test_reals_compare_within_the_epsilon(self):
        self.assertEqual(model.EPSILON, Fraction(1, 100000))
        two_one = Fraction(21, 10)
        # The double the runtime holds for 2.1 is the same value as 2.1.
        self.assertTrue(model.same_value(Fraction(2.1), two_one))
        self.assertTrue(model.same_value(two_one, two_one + model.EPSILON))
        self.assertFalse(model.same_value(two_one, two_one + 2 * model.EPSILON))
        self.assertFalse(model.same_value(two_one, 2))
        for bad in (2.1, True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    model.same_value(bad, 2)

    def test_the_repository_index_truncates_b(self):
        for b, index in ((2, 2), (Fraction(21, 10), 2), (Fraction(29, 10), 2), (Fraction(2.9), 2),
                         (Fraction(3), 3), (Fraction(-21, 10), -2)):
            with self.subTest(b=b):
                self.assertEqual(model.repository_index(b), index)
        for bad in (2.1, True):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    model.repository_index(bad)

    def test_the_save_keeps_two_decimals(self):
        # The assumption is open until the follow-up's Live procedure 1 reloads a piece.
        self.assertIsNone(model.HYPOTHESES["string_keeps_two_decimals"])
        self.assertEqual(model.saved_number(2), 2)
        self.assertIsInstance(model.saved_number(2), int)
        self.assertEqual(model.saved_number(767593635), 767593635)
        for act in range(1, ACT_COUNT + 1):
            exact = Fraction(20 + act, 10)
            with self.subTest(act=act):
                self.assertEqual(model.saved_number(exact), exact)
                self.assertEqual(model.saved_number(Fraction(float(exact))), exact)
        self.assertEqual(model.saved_number(Fraction(2123, 1000)), Fraction(212, 100))
        self.assertEqual(model.saved_number(Fraction(2127, 1000)), Fraction(213, 100))
        self.assertEqual(model.saved_number(Fraction(-2127, 1000)), Fraction(-213, 100))
        # A finer step than hundredths does not survive: 2.001 comes back whole.
        self.assertEqual(model.saved_number(Fraction(2001, 1000)), 2)
        with self.assertRaises(TypeError):
            model.saved_number(2.1)

    def test_a_truthy_c_picks_the_unique_repository(self):
        for c, unique in ((0, False), (1, True), (Fraction(1, 2), False), (Fraction(51, 100), True),
                          (Fraction(45, 100), False), (Fraction(1, 20), False)):
            with self.subTest(c=c):
                self.assertIs(model.uses_unique_repository(c), unique)
        # The `cfrac` candidate's c (act/20, 0.05 .. 0.45) stays in the normal repository.
        for act in range(1, ACT_COUNT + 1):
            with self.subTest(act=act):
                self.assertFalse(model.uses_unique_repository(Fraction(act, 20)))

    def test_only_classes_12_to_15_stack(self):
        self.assertEqual(model.STACKABLE_CLASSES, frozenset({12, 13, 14, 15}))
        self.assertEqual(model.STACKABLE_CLASSES, frozenset(DATA["bag_stack"]["classes"]))
        for item_type in range(0, 20):
            with self.subTest(item_type=item_type):
                same = model.Item(item_type, 4, 0, 1)
                self.assertEqual(model.stacks(same, same._replace(a=2)), item_type in model.STACKABLE_CLASSES)
        self.assertFalse(model.stacks(model.Item(12, 4, 0), model.Item(13, 4, 0)))
        self.assertFalse(model.stacks(model.Item(12, 4, 0), model.Item(12, 5, 0)))
        # The incoming item's class is refused before anything else is read: a
        # field the compare could not take is never reached for class 11.
        unread = object()
        self.assertFalse(model.stacks(model.Item(11, unread, unread, 1, unread),
                                      model.Item(11, unread, unread, 2, unread)))
        self.assertFalse(model.stacks(model.Item(12, unread, 0), model.Item(11, 4, 0)))
        # Positive control: the same unreadable field on a class that passes is read, and refused.
        with self.assertRaises(TypeError):
            model.stacks(model.Item(12, unread, 0), model.Item(12, 4, 0))
        with self.assertRaises(TypeError):
            model.stacks(model.Item(True, 4, 0), model.Item(12, 4, 0))
        with self.assertRaises(TypeError):
            model.stacks(model.Item(12, 4.0, 0), model.Item(12, 4, 0))
        with self.assertRaises(TypeError):
            model.stacks(model.Item(12, 4, 0), model.Item(True, 4, 0))

    def test_a_stack_holds_at_most_999(self):
        self.assertEqual(model.BAG_STACK_CAP, 999)
        self.assertEqual(DATA["bag_stack"]["cap"], model.BAG_STACK_CAP)
        held = model.Item(13, 4, 0, 1)
        for have, adding, merges in ((1, 1, True), (998, 1, True), (990, 9, True), (999, 1, False),
                                     (990, 10, False), (1, 999, False)):
            with self.subTest(have=have, adding=adding):
                self.assertIs(model.stacks(held._replace(o=have), held._replace(a=2, o=adding)), merges)
        with self.assertRaises(TypeError):
            model.stacks(held._replace(o=1.0), held)

    def test_the_logo_is_used_up_only_when_potion_use_answers_true(self):
        self.assertTrue(model.HYPOTHESES["potion_use_true_clears_the_item"])
        self.assertTrue(model.item_used_up(True))
        self.assertFalse(model.item_used_up(False))
        with self.assertRaises(TypeError):
            model.item_used_up(1)

    def test_the_gem_is_one_in_its_rate(self):
        for rate in (9000, 10000, 11000):
            with self.subTest(rate=rate):
                self.assertEqual(model.gem_chance(rate), Fraction(1, rate))
        for unknown in (None, 0, -5):
            with self.subTest(unknown=unknown):
                self.assertIsNone(model.gem_chance(unknown))
        with self.assertRaises(TypeError):
            model.gem_chance(9000.0)

    def test_expected_gems_are_linear_in_the_rolls(self):
        chance = model.gem_chance(9000)
        self.assertEqual(model.expected_drops(0, chance), 0)
        self.assertEqual(model.expected_drops(9000, chance), 1)
        self.assertEqual(model.expected_drops(27000, chance), 3 * model.expected_drops(9000, chance))
        self.assertEqual(model.expected_drops(50, None), 0)
        with self.assertRaises(ValueError):
            model.expected_drops(-1, chance)

    def test_every_hypothesis_is_none_until_measured(self):
        questions = DATA["open_questions"]
        keyed = {q["hypothesis"]: q for q in questions if q["hypothesis"]}
        self.assertEqual(set(keyed), set(model.HYPOTHESES))
        self.assertEqual(len({q["question"] for q in questions}), len(questions))
        for key, value in model.HYPOTHESES.items():
            with self.subTest(key=key):
                if keyed[key]["status"] == "measured":
                    self.assertIsNotNone(value)
                    self.assertIn(keyed[key]["capture"], LIVE_CAPTURES)
                    # Where the entry records its answer, the model carries it.
                    if isinstance(keyed[key].get("answer"), bool):
                        self.assertIs(value, keyed[key]["answer"])
                else:
                    self.assertIsNone(value)


class TargetTests(unittest.TestCase):
    """What the mod turns it into: a piece rolled inside the gem roll, kept in
    its own bag cell, whose use moves the player into its act's boss room."""

    def test_a_consumable_piece_never_stacks(self):
        logo = model.Item(BASE_CLASS, BASE_B, 0, 542155217)
        for act in range(1, ACT_COUNT + 1):
            piece = piece_item(act)
            with self.subTest(act=act):
                self.assertFalse(model.stacks(logo, piece))
                self.assertFalse(model.stacks(piece, logo))
                self.assertFalse(model.stacks(piece, piece))
                for other in range(1, ACT_COUNT + 1):
                    self.assertFalse(model.stacks(piece, piece_item(other)))
                # Nor does a count of its own, far under the cap, get it past the class rule.
                self.assertFalse(model.stacks(piece._replace(o=2), piece._replace(o=1)))
        self.assertNotIn(DATA["base"]["item_type"], model.STACKABLE_CLASSES)
        # Negative control: the same rule does merge two items of a stackable class.
        self.assertTrue(model.stacks(model.Item(12, BASE_B, 0, 1), model.Item(12, BASE_B, 0, 2)))

    def test_a_saved_consumable_keeps_its_count(self):
        # Measured by the follow-up's Live procedure 4 (`reload-stack-kept`):
        # piece stacks at o=3 and o=2 came back at the same counts after a relaunch.
        self.assertIs(model.HYPOTHESES["saved_count_is_kept"], True)
        for count in (1, 2, 3, 998, model.BAG_STACK_CAP):
            with self.subTest(count=count):
                self.assertEqual(model.saved_number(count), count)
                self.assertIsInstance(model.saved_number(count), int)
                # A reloaded piece stack is still its act's piece, and still stacks with nothing.
                stack = piece_item(1)._replace(o=count)
                reloaded = saved(stack)._replace(o=model.saved_number(stack.o))
                self.assertEqual(reloaded, stack)
                self.assertEqual(act_of_seed(reloaded.a), 1)
                self.assertFalse(model.stacks(reloaded, piece_item(1)))
        # Negative control: a count that were not whole would not come back as written.
        self.assertNotEqual(model.saved_number(Fraction(10001, 10000)), Fraction(10001, 10000))

    def test_a_fractional_key_piece_stays_apart_from_the_real_key(self):
        for act in range(1, ACT_COUNT + 1):
            piece = key_piece_item(act)
            with self.subTest(act=act):
                for shape in (piece, piece._replace(b=Fraction(float(piece.b)))):
                    self.assertFalse(model.stacks(REAL_KEY, shape))
                    self.assertFalse(model.stacks(shape, REAL_KEY))
                self.assertEqual(key_piece_act(piece), act)
                self.assertEqual(key_piece_act(REAL_KEY), 0)
        # Positive control: the same piece with a whole `b` (Live procedure 1's
        # design) merges into the real key, seed or not.
        self.assertTrue(model.stacks(REAL_KEY, key_piece_item(1)._replace(b=KEY_BASE_INDEX)))

    def test_key_pieces_stack_per_act(self):
        for act in range(1, ACT_COUNT + 1):
            piece = key_piece_item(act)
            with self.subTest(act=act):
                self.assertTrue(model.stacks(piece, piece))
                self.assertTrue(model.stacks(piece, piece._replace(b=Fraction(float(piece.b)))))
                for other in range(1, ACT_COUNT + 1):
                    if other != act:
                        self.assertFalse(model.stacks(piece, key_piece_item(other)))
        # Neither the legacy bag piece nor a piece on another key joins them.
        self.assertFalse(model.stacks(key_piece_item(1), piece_item(1)))
        self.assertFalse(model.stacks(key_piece_item(1), key_piece_item(1, KEY_BASE_INDEX + 1)))

    def test_a_saved_key_piece_still_stacks_with_a_fresh_one(self):
        for act in range(1, ACT_COUNT + 1):
            fresh = key_piece_item(act)
            reloaded = saved(fresh._replace(b=Fraction(float(fresh.b))))
            with self.subTest(act=act):
                self.assertTrue(model.stacks(reloaded, fresh))
                self.assertTrue(model.stacks(fresh, reloaded))
                self.assertFalse(model.stacks(reloaded, saved(REAL_KEY)))
                self.assertEqual(key_piece_act(reloaded), act)
                for other in range(1, ACT_COUNT + 1):
                    if other != act:
                        self.assertFalse(model.stacks(reloaded, saved(key_piece_item(other))))
        # The real key reloads whole and still merges with a fresh real key.
        self.assertTrue(model.stacks(saved(REAL_KEY), REAL_KEY._replace(a=1)))
        # The tolerance takes what a two-decimal round trip returns (at most
        # 0.005 off) and stays under half the 0.1 between two acts.
        self.assertGreaterEqual(KEY_PIECE_TOLERANCE, Fraction(5, 1000))
        self.assertLess(KEY_PIECE_TOLERANCE, Fraction(1, 2 * ACT_FRACTION_DIVISOR))
        self.assertEqual(key_piece_act(key_piece_item(1)._replace(b=Fraction(2105, 1000))), 1)
        self.assertEqual(key_piece_act(key_piece_item(1)._replace(b=Fraction(215, 100))), 0)

    def test_crafting_never_counts_a_key_piece(self):
        for act in range(1, ACT_COUNT + 1):
            for piece in (key_piece_item(act), saved(key_piece_item(act))):
                with self.subTest(act=act, b=piece.b):
                    self.assertFalse(model.counted_by_crafting(piece, KEY_BASE_CLASS, KEY_BASE_INDEX))
                    self.assertFalse(model.find_matches(piece, KEY_BASE_INDEX, 0))
        # Control: the real key is counted and found.
        self.assertTrue(model.counted_by_crafting(REAL_KEY, KEY_BASE_CLASS, KEY_BASE_INDEX))
        self.assertTrue(model.find_matches(REAL_KEY, KEY_BASE_INDEX, 0))
        # Why the `cfrac` candidate stays research: crafting ignores `c`, so it
        # would count a piece marked only by `c` as the key, while the find does not.
        cfrac = model.Item(KEY_BASE_CLASS, KEY_BASE_INDEX, Fraction(1, 20), seed_of_act(1))
        self.assertFalse(model.stacks(REAL_KEY, cfrac))
        self.assertTrue(model.counted_by_crafting(cfrac, KEY_BASE_CLASS, KEY_BASE_INDEX))
        self.assertFalse(model.find_matches(cfrac, KEY_BASE_INDEX, 0))

    def test_a_key_piece_loads_as_its_base(self):
        # Without ForgePact the repository lookup still finds the key base, in the
        # normal repository, before and after a save.
        for act in range(1, ACT_COUNT + 1):
            for piece in (key_piece_item(act), saved(key_piece_item(act))):
                with self.subTest(act=act, b=piece.b):
                    self.assertEqual(model.repository_index(piece.b), KEY_BASE_INDEX)
                    self.assertFalse(model.uses_unique_repository(piece.c))
        self.assertEqual(model.repository_index(key_piece_b(9)), KEY_BASE_INDEX)
        self.assertEqual(model.repository_index(REAL_KEY.b), KEY_BASE_INDEX)

    def test_piece_is_a_quarter_more_common_than_the_gem(self):
        for rate in (9000, 10000, 11000, 9001, 10003, 2, 7):
            with self.subTest(rate=rate):
                gem = model.gem_chance(rate)
                piece = piece_chance(rate)
                self.assertGreater(piece, gem)
                d = piece_denominator(rate)
                if rate % RATIO_DENOMINATOR == 0:
                    self.assertEqual(piece / gem, Fraction(RATIO_DENOMINATOR, RATIO_NUMERATOR))
                elif rate >= RATIO_DENOMINATOR:
                    # floor() only rounds D down: the ratio overshoots 5/4 by under 5/(4D),
                    # and the piece's chance stays within 1/G of five quarters of the gem's.
                    over = piece / gem - Fraction(RATIO_DENOMINATOR, RATIO_NUMERATOR)
                    self.assertGreaterEqual(over, 0)
                    self.assertLess(over, Fraction(RATIO_DENOMINATOR, RATIO_NUMERATOR * d))
                    self.assertLess(abs(piece - gem * Fraction(5, 4)), gem)
        self.assertEqual(piece_denominator(DATA["gem"]["expected_rate"]), 7200)
        self.assertEqual(piece_denominator(1), 1)

    def test_more_gem_rolls_give_more_pieces(self):
        chance = piece_chance(9000)
        expected = [model.expected_drops(n, chance) for n in (0, 7200, 14400, 72000)]
        self.assertEqual(expected, [0, 1, 2, 10])
        # A lever that lowers the gem's rate lowers D with it: more pieces per roll.
        self.assertGreater(piece_chance(4500), piece_chance(9000))
        # The share of pieces to gems is the same whatever the number of rolls.
        for n in (1000, 123457):
            with self.subTest(rolls=n):
                self.assertEqual(model.expected_drops(n, chance) / model.expected_drops(n, model.gem_chance(9000)),
                                 Fraction(5, 4))

    def test_boss_kill_town_and_boss_room_never_drop(self):
        for room, act in _table_rooms().items():
            for forced in (False, True):
                with self.subTest(room=room, forced=forced):
                    verdict = decide_drop(True, forced, room, act, True, False, 9000, Fraction(0))
                    if is_town(room):
                        self.assertEqual(verdict, "town")
                    elif is_boss_room(room):
                        self.assertEqual(verdict, "boss-room")
                    else:
                        self.assertEqual(verdict, "hit")
                        self.assertEqual(decide_drop(True, forced, room, act, True, True, 9000, Fraction(0)),
                                         "boss-kill")
        for room in (r["room"] for r in ROOMS["not_in_table"]):
            with self.subTest(room=room):
                self.assertEqual(decide_drop(True, True, room, 0, True, False, 9000, Fraction(0)), "no-act")

    def test_non_monster_source_never_drops(self):
        for forced in (False, True):
            for boss in (False, True):
                with self.subTest(forced=forced, boss=boss):
                    self.assertEqual(decide_drop(True, forced, "Act_01_01", 1, False, boss, 9000, Fraction(0)),
                                     "not-monster")

    def test_unknown_gem_rate_never_drops(self):
        for rate in (None, 0, -1, Fraction(-1, 2)):
            for roll in (Fraction(0), Fraction(1, 10 ** 9)):
                with self.subTest(rate=rate, roll=roll):
                    self.assertEqual(piece_denominator(rate), 0)
                    self.assertEqual(decide_drop(True, False, "Act_02_01", 2, True, False, rate, roll), "no-rate")
        # Forcing replaces the chance, never the rules before it.
        self.assertEqual(decide_drop(True, True, "Act_02_01", 2, True, False, None, Fraction(0)), "hit")

    def test_force_overrides_only_the_chance(self):
        self.assertEqual(DATA["force_overrides"], ["no-rate", "hit", "miss"])
        for case in _cases("drop"):
            plain = _drop(case, forced=False)
            forced = _drop(case, forced=True)
            with self.subTest(case=case["id"]):
                if plain in DATA["force_overrides"]:
                    self.assertEqual(forced, "hit")
                else:
                    self.assertEqual(forced, plain)

    def test_the_roll_hits_below_one_in_d_only(self):
        d = piece_denominator(9000)
        self.assertEqual(decide_drop(True, False, "Act_01_01", 1, True, False, 9000, Fraction(1, d) - Fraction(1, 10 ** 12)), "hit")
        self.assertEqual(decide_drop(True, False, "Act_01_01", 1, True, False, 9000, Fraction(1, d)), "miss")

    def test_use_transfers_from_towns_and_zones(self):
        rooms = _table_rooms()
        towns = [r for r in rooms if is_town(r)]
        self.assertEqual(len(towns), 8)
        for room, room_act in rooms.items():
            for act in range(1, ACT_COUNT + 1):
                with self.subTest(room=room, act=act):
                    verdict = decide_use(True, room, room_act, act)
                    if is_boss_room(room):
                        self.assertEqual(verdict, "boss-room")
                        # A refusal answers PotionUse false: the piece is kept.
                        self.assertFalse(model.item_used_up(verdict == "transfer"))
                    else:
                        self.assertEqual(verdict, "transfer")
                        self.assertEqual(transfer_target(act), "Act_%02d_Boss" % act)
                        # The game clears the piece only on the transfer's true answer.
                        self.assertTrue(model.item_used_up(verdict == "transfer"))
        for room in (r["room"] for r in ROOMS["not_in_table"]):
            with self.subTest(room=room):
                self.assertEqual(decide_use(True, room, 0, 1), "no-act")
        self.assertEqual(decide_use(True, "Act_01_01", 1, 0), "not-piece")
        self.assertIsNone(transfer_target(0))

    def test_every_act_drops_and_transfers(self):
        rooms = _table_rooms()
        for act in range(1, ACT_COUNT + 1):
            eligible = [r for r, a in rooms.items() if a == act and room_refusal(r, a) is None]
            with self.subTest(act=act):
                self.assertTrue(eligible)
                self.assertEqual(decide_use(True, eligible[0], act, act), "transfer")

    def test_a_transfer_never_targets_the_room_it_starts_from(self):
        # The transfer drops its target's saved zone state, so it must never be
        # the room the player stands in: every room a use is allowed from is
        # not a boss room, and every target is one.
        rooms = _table_rooms()
        transfers = 0
        for room, room_act in rooms.items():
            for act in range(1, ACT_COUNT + 1):
                if decide_use(True, room, room_act, act) == "transfer":
                    transfers += 1
                    with self.subTest(room=room, act=act):
                        self.assertNotEqual(transfer_target(act), room)
                        self.assertFalse(is_boss_room(room))
                        self.assertTrue(is_boss_room(transfer_target(act)))
        self.assertGreater(transfers, 0)
        # Inside a boss room, with an act or not, the use is refused.
        self.assertEqual(decide_use(True, "Act_02_Boss", 2, 2), "boss-room")
        self.assertEqual(decide_use(True, "Act_01_Boss", 0, 1), "no-act")

    def test_seeds_round_trip_and_stay_clear_of_other_items(self):
        for act in range(1, ACT_COUNT + 1):
            with self.subTest(act=act):
                self.assertEqual(act_of_seed(seed_of_act(act)), act)
        for seed in (SEED_BASE, SEED_BASE + ACT_COUNT + 1, *DATA["reserved_seeds"]):
            with self.subTest(seed=seed):
                self.assertEqual(act_of_seed(seed), 0)
        self.assertEqual(seed_of_act(0), 0)
        self.assertEqual(seed_of_act(ACT_COUNT + 1), 0)

    def test_the_shared_cases(self):
        rooms = _table_rooms()
        for case in DATA["cases"]:
            with self.subTest(case=case["id"]):
                if case["kind"] in ("drop", "use"):
                    self.assertEqual(case["act"], rooms.get(case["room"], 0))
                if case["kind"] == "drop":
                    self.assertEqual(_drop(case), case["verdict"])
                elif case["kind"] == "use":
                    piece_act = act_of_seed(case["seed"])
                    self.assertEqual(decide_use(case["mod_on"], case["room"], case["act"], piece_act),
                                     case["verdict"])
                    if case["verdict"] == "transfer":
                        self.assertEqual(transfer_target(piece_act), case["boss_room"])
                    if "boss_object" in case:
                        self.assertEqual(ACTS[piece_act][0], case["boss_object"])
                else:
                    self.assertEqual(case["kind"], "stack")
                    self.assertEqual(model.stacks(_item(case["held"]), _item(case["picked"])), case["stacks"])
        # Every verdict but `unnamed` (unreachable with the shipped table) has a case.
        self.assertEqual(set(DROP_VERDICTS) - {c["verdict"] for c in _cases("drop")}, {"unnamed"})
        self.assertEqual(set(USE_VERDICTS) - {c["verdict"] for c in _cases("use")}, {"unnamed"})
        self.assertEqual({c["stacks"] for c in _cases("stack")}, {True, False})


class CuratedTests(unittest.TestCase):
    """The two curated files agree with the SDK's tables and with each other."""

    def test_schema_note_comes_first(self):
        for path in (CURATED, ROOM_ACTS):
            with self.subTest(path=path.name):
                self.assertEqual(next(iter(json.loads(path.read_text(encoding="utf-8")))), "$schema_note")

    def test_room_acts_match_the_sdk_rooms(self):
        rows = ROOMS["rooms"]
        self.assertEqual(len(rows), 175)
        self.assertEqual(len({r["room"] for r in rows}), 175)
        for row in rows:
            with self.subTest(room=row["room"]):
                self.assertEqual(ROOM_NAME_TO_INDEX.get(row["room"]), row["index"])
                self.assertIn(row["act"], range(1, ACT_COUNT + 1))
                self.assertIn(row["status"], ("static_reading", "measured"))
                if row["status"] == "measured":
                    self.assertEqual(row["capture"], MEASURED_ROOMS[row["room"]][1])
        self.assertEqual(sorted(r["room"] for r in rows if r["status"] == "measured"),
                         sorted(MEASURED_ROOMS))
        # § 21.1's rows per act, 1 to 9.
        per_act = [sum(1 for r in rows if r["act"] == act) for act in range(1, ACT_COUNT + 1)]
        self.assertEqual(per_act, [21, 24, 16, 15, 14, 20, 17, 19, 29])
        # A room's name does not always give its act.
        self.assertEqual(_table_rooms()["Act_08_Orres_Lair_rm"], 4)
        self.assertNotIn("Town_08_rm", _table_rooms())
        self.assertNotIn("Unstable_Rift_08_04", ROOM_NAME_TO_INDEX)
        for row in ROOMS["not_in_table"]:
            with self.subTest(not_in_table=row["room"]):
                self.assertEqual(ROOM_NAME_TO_INDEX.get(row["room"]), row["index"])
                self.assertNotIn(row["room"], _table_rooms())
        self.assertTrue(hasattr(GameScript, ROOMS["script"]))
        self.assertNotIn("minus one", ROOMS["$schema_note"])

    def test_bosses_descend_from_the_boss_parent(self):
        boss_parent = OBJECT_NAME_TO_INDEX[DATA["boss_parent"]]
        monster_parent = OBJECT_NAME_TO_INDEX[DATA["monster_parent"]]
        self.assertEqual([row["act"] for row in DATA["acts"]], list(range(1, ACT_COUNT + 1)))
        for row in DATA["acts"]:
            with self.subTest(act=row["act"], boss=row["boss_object"]):
                index = OBJECT_NAME_TO_INDEX.get(row["boss_object"])
                self.assertEqual(index, row["object_index"])
                self.assertTrue(is_descendant_of(index, boss_parent))
                self.assertTrue(is_descendant_of(index, monster_parent))
                self.assertTrue(row["named"])
                self.assertTrue(row["piece_name"].startswith("Piece of "))
                self.assertEqual(row["seed"], DATA["seed_base"] + row["act"])
        self.assertEqual(DATA["acts"][6]["boss_object"], "Mevius_obj")

    def test_boss_rooms_are_the_sdk_rooms(self):
        rooms = _table_rooms()
        outside = {r["room"] for r in ROOMS["not_in_table"]}
        for row in DATA["acts"]:
            room = row["boss_room"]
            with self.subTest(act=row["act"], room=room):
                self.assertEqual(room, "Act_%02d_Boss" % row["act"])
                self.assertEqual(ROOM_NAME_TO_INDEX.get(room), row["boss_room_index"])
                # No piece drops there and no piece is used there.
                self.assertTrue(is_boss_room(room))
                # The room is either outside RoomActIndex's switch or in its own act.
                if room in outside:
                    self.assertNotIn(room, rooms)
                else:
                    self.assertEqual(rooms[room], row["act"])
        self.assertEqual(outside, {"Act_01_Boss", "Act_03_Boss", "Act_04_Boss", "Act_05_Boss", "Act_07_Boss"})
        self.assertIn(DATA["boss_room_object"], OBJECT_NAME_TO_INDEX)

    def test_the_transfer_is_the_game_s_own_scripts(self):
        # Live procedure 3: the portal failed and NetworkRoomGoto passed, and the
        # owner chose the direct transfer; the portal block and its offset are gone.
        self.assertNotIn("portal", DATA)
        transfer = DATA["transfer"]
        self.assertEqual(transfer["scripts"], ["gml_Script_ZoneStateExists", "gml_Script_ZoneStateResetSingle",
                                               "gml_Script_NetworkRoomGoto"])
        for name in transfer["scripts"]:
            with self.subTest(name=name):
                self.assertTrue(hasattr(GameScript, name))
        self.assertNotIn("offset_px", transfer)
        self.assertEqual((transfer["status"], transfer["capture"], transfer["live_check"]),
                         ("measured", LIVE_3, "goto-travel"))
        # Live procedure 2 attempt 2: the second transfer after a kill read
        # fresh=1 cleared=1, and Gurag came out again.
        self.assertEqual((transfer["reset_status"], transfer["reset_capture"], transfer["reset_live_check"]),
                         ("measured", LIVE_2, "on-reentry-reset"))
        for key in ("travel_source", "reset_source"):
            path, _, section = transfer[key].partition(" § ")
            with self.subTest(source=key):
                self.assertIn(section, (ROOT / path).read_text(encoding="utf-8"))

    def test_live_3_answered_its_questions(self):
        questions = {q["question"]: q for q in DATA["open_questions"]}
        answered = {name: q["answer"] for name, q in questions.items() if q.get("capture") == LIVE_3}
        self.assertEqual(answered, {
            "base_repository_name": "passed", "use_reaches_potion_use_with_the_piece": "passed",
            "portal_obj_travels_to_its_room": "failed", "pentagram_brings_out_the_boss": "passed",
            "boss_dies_in_its_own_room": "passed", "zone_revisit_after_a_portal": "passed",
            "class_11_never_stacks": True, "room_outside_the_switch_is_undefined": False,
        })
        for name in answered:
            with self.subTest(name=name):
                self.assertEqual(questions[name]["status"], "measured")
        # The fresh boss was Live procedure 2's to measure (attempt 2, on-reentry-boss).
        reentry = questions["boss_returns_on_reentry"]
        self.assertEqual((reentry["live_check"], reentry["status"], reentry["capture"], reentry["answer"]),
                         ("on-reentry-boss", "measured", LIVE_2, "passed"))

    def test_each_act_says_what_its_boss_rests_on(self):
        statuses = {row["act"]: row["status"] for row in DATA["acts"]}
        self.assertEqual(statuses[7], "owner_named")
        self.assertEqual({statuses[a] for a in (4, 5)}, {"inference"})
        for act in (1, 2, 3, 6, 8, 9):
            with self.subTest(act=act):
                self.assertIn(statuses[act], ("static_reading", "measured"))
        runtime = RUNTIME_DOC.read_text(encoding="utf-8")
        for row in DATA["acts"]:
            path, _, section = row["source"].partition(" § ")
            with self.subTest(act=row["act"]):
                self.assertTrue((ROOT / path).is_file())
                self.assertIn(section, runtime)

    def test_the_gem_rate_is_the_measured_one(self):
        gem = DATA["gem"]
        self.assertEqual(gem["repository_name"], "socketable_gem_of_incarnation")
        self.assertEqual((gem["category"], gem["item_type"], gem["b"]), (15, 15, 136))
        self.assertEqual(gem["expected_rate"], 9000)
        self.assertEqual(gem["rate_status"], "measured")
        self.assertEqual(gem["capture"], LIVE_1)
        path, _, section = gem["rate_source"].partition(" § ")
        self.assertIn(section, (ROOT / path).read_text(encoding="utf-8"))
        self.assertEqual((DATA["ratio"]["numerator"], DATA["ratio"]["denominator"]),
                         (RATIO_NUMERATOR, RATIO_DENOMINATOR))
        self.assertEqual(piece_denominator(gem["expected_rate"]), 7200)

    def test_the_base_is_the_edible_pas_logo(self):
        base = DATA["base"]
        self.assertEqual(base["repository_name"], "consumable_edible_pas_logo")
        self.assertEqual((base["category"], base["item_type"], base["b"], base["c"], base["j"]),
                         (11, BASE_CLASS, BASE_B, 0, 0))
        self.assertEqual((base["b_status"], base["capture"]), ("measured", LIVE_1))
        self.assertEqual((base["name_status"], base["name_live_check"], base["name_capture"]),
                         ("measured", "base-consumable", LIVE_3))
        path, _, section = base["source"].partition(" § ")
        self.assertIn(section, (ROOT / path).read_text(encoding="utf-8"))
        for gone in ("key_category", "spawn_offset_px"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, DATA)

    def test_the_key_base_is_the_bifrost_key(self):
        key = DATA["key_base"]
        self.assertEqual(key["repository_name"], "keys_bifrost_key")
        self.assertEqual((key["category"], key["item_type"], key["c"]), (12, KEY_BASE_CLASS, 0))
        self.assertEqual((key["index"], key["index_status"], key["index_capture"]),
                         (KEY_BASE_INDEX, "measured", LIVE_3))
        self.assertEqual(Fraction(str(key["act_step"])), Fraction(1, ACT_FRACTION_DIVISOR))
        self.assertEqual(Fraction(str(key["tolerance"])), KEY_PIECE_TOLERANCE)
        # Measured in session by the follow-up's Live procedure 1, and not shipped:
        # the Key tab's right-click never reached the use (keyuse-route: not-reached).
        self.assertEqual((key["status"], key["capture"], key["shipped"]),
                         ("measured_in_session", ICON_LIVE_1, False))
        self.assertEqual(key["choice_status"], "our_code")
        self.assertTrue(set(key["live_checks"]) >= {"merge-control", "frac-apart-key", "frac-stack",
                                                    "frac-apart-act", "reload-frac-kept"})
        path, _, section = key["source"].partition(" § ")
        self.assertIn(section, (ROOT / path).read_text(encoding="utf-8"))
        # The legacy bag piece's base stays as it was.
        self.assertEqual(DATA["base"]["repository_name"], "consumable_edible_pas_logo")

    def test_the_piece_sprite_is_the_gems_and_has_a_pickup_companion(self):
        icon = DATA["icon"]
        self.assertEqual(icon["info_key"], "11")
        self.assertEqual(icon["sprite"], "Gem_Incarnation_spr")
        self.assertEqual(icon["ground_sprite"], "Pickup_" + icon["sprite"])
        for name in (icon["sprite"], icon["ground_sprite"]):
            with self.subTest(name=name):
                self.assertIn(name, SPRITE_NAME_TO_INDEX)
        # Negative control: a sprite with no ground companion is caught.
        self.assertNotIn("Pickup_" + "Pickup_" + icon["sprite"], SPRITE_NAME_TO_INDEX)
        # Measured by the follow-up's Live procedure 1: the bag draws it, the ground does not.
        self.assertEqual((icon["status"], icon["capture"], icon["route"]), ("measured", ICON_LIVE_1, "bag-only"))
        self.assertIn("gem-sprite", icon["live_checks"])
        self.assertIn("icon-ground", icon["live_checks"])
        path, _, section = icon["source"].partition(" § ")
        self.assertIn(section, (ROOT / path).read_text(encoding="utf-8"))

    def test_the_follow_up_s_questions_wait_for_its_session(self):
        questions = {q["question"]: q for q in DATA["open_questions"]}
        # question -> (its live check, the session that answered it, or None while open)
        checks = {"key_piece_survives_a_save": ("reload-frac-kept", None),
                  "key_tab_right_click_reaches_the_use": ("keyuse-prompt", ICON_LIVE_1),
                  "confirm_takes_one_from_a_stack": ("stackuse-all", ICON_LIVE_2),
                  "ground_shows_the_gems_pickup_sprite": ("icon-ground", ICON_LIVE_1)}
        for name, (check, capture) in checks.items():
            with self.subTest(name=name):
                entry = questions[name]
                self.assertEqual(entry["live_check"], check)
                if capture:
                    self.assertEqual((entry["status"], entry["capture"]), ("measured", capture))
                else:
                    self.assertEqual(entry["status"], "pending")
        # Each answered no: the Key tab's right-click is not a use, the confirm clears
        # a whole stack, and the ground keeps the base's pickup sprite.
        for name in ("key_tab_right_click_reaches_the_use", "confirm_takes_one_from_a_stack",
                     "ground_shows_the_gems_pickup_sprite"):
            with self.subTest(answer=name):
                self.assertIs(questions[name]["answer"], False)
        self.assertEqual(questions["key_piece_survives_a_save"]["hypothesis"], "string_keeps_two_decimals")

    def test_the_bag_stack_is_the_game_s_own_script(self):
        stack = DATA["bag_stack"]
        for key in ("script", "class_script", "result_script"):
            with self.subTest(key=key):
                self.assertTrue(hasattr(GameScript, stack[key]), stack[key])
        self.assertEqual(stack["script"], "gml_Script_InventoryGridAddToStack")
        self.assertEqual(stack["item_argument"], 2)
        self.assertEqual(sorted(stack["classes"]), sorted(model.STACKABLE_CLASSES))
        self.assertNotIn(BASE_CLASS, stack["classes"])
        self.assertEqual((stack["cap"], stack["result_field"]), (model.BAG_STACK_CAP, "success"))
        # Measured by the follow-up's Live procedures 2 and 4, and on the player build by 3.
        self.assertEqual(stack["status"], "measured")
        self.assertEqual(stack["captures"], [ICON_LIVE_2, ICON_LIVE_4, ICON_LIVE_3])
        self.assertEqual(stack["routes"], {"merge-route": "detour", "bagstackuse-route": "take-one",
                                           "stackdraw-route": "game", "save-route": "kept",
                                           "save-trigger": "stash-close"})
        self.assertTrue(set(stack["live_checks"]) >= {"bag-no-stack-control", "merge-stack", "merge-no-duplicate",
                                                      "stack-draw", "stackuse-all", "reload-stack-kept"})
        path, _, section = stack["source"].partition(" § ")
        self.assertIn(section, (ROOT / path).read_text(encoding="utf-8"))

    def test_the_bag_stack_s_questions_wait_for_live_procedure_2(self):
        questions = {q["question"]: q for q in DATA["open_questions"]}
        # question -> (its live check, the session whose capture answers it)
        checks = {"merged_pickup_leaves_no_copy": ("merge-no-duplicate", ICON_LIVE_2),
                  "bag_draws_a_consumable_stack_count": ("stack-draw", ICON_LIVE_2),
                  "confirm_on_a_bag_stack": ("stackuse-all", ICON_LIVE_2),
                  "bag_file_written_during_play": ("save-written", ICON_LIVE_4),
                  "consumable_count_survives_a_save": ("reload-stack-kept", ICON_LIVE_4)}
        for name, (check, capture) in checks.items():
            with self.subTest(name=name):
                entry = questions[name]
                self.assertEqual(entry["live_check"], check)
                self.assertIn(check, DATA["bag_stack"]["live_checks"])
                if entry["status"] == "measured":
                    self.assertEqual(entry["capture"], capture)
                else:
                    self.assertEqual(entry["status"], "pending")
        self.assertEqual(questions["consumable_count_survives_a_save"]["hypothesis"], "saved_count_is_kept")

    def test_the_rules_and_words_are_the_transforms(self):
        self.assertEqual(tuple(DATA["drop_verdicts"]), DROP_VERDICTS)
        self.assertEqual(tuple(DATA["use_verdicts"]), USE_VERDICTS)
        self.assertEqual(DATA["seed_base"], SEED_BASE)
        rules = DATA["room_rules"]
        self.assertEqual(rules["town_prefixes"], {"Town_": "town"})
        self.assertEqual(rules["boss_room_prefixes"], {"Uber_": "boss-room", "Dev_": "boss-room"})
        self.assertEqual(rules["boss_room_substrings"], {"_Boss": "boss-room"})
        self.assertEqual(rules["no_act"], "no-act")
        self.assertTrue(DATA["use_rules"]["towns_allowed"])
        self.assertTrue(hasattr(GameScript, DATA["use_rules"]["use_script"]))

    def test_the_game_scripts_are_the_sdks(self):
        for name in ("gml_Script_RoomActIndex", "gml_Script_DropGems", "gml_Script_LoadDrops",
                     "gml_Script_ItemsAreStackable", "gml_Script_GetNormalRepoStruct",
                     "gml_Script_AddToInventory", "gml_Script_InventoryGridAddToStack",
                     "gml_Script_GridAddToStack", "gml_Script_IsItemTypeStackable",
                     "gml_Script_UiAInventoryConsumeItemConfirm", "gml_Script_CanUsePotion",
                     "gml_Script_PotionUse", "gml_Script_InvGridClearItemNode",
                     "gml_Script_NetworkRoomGoto", "gml_Script_RoomGoto",
                     "gml_Script_ZoneStateExists", "gml_Script_ZoneStateResetSingle",
                     "gml_Script_GetDropRate_anon_55737_s_ItemBaseDefinition_DefineStructs"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(GameScript, name))


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec, the model and the curated files were written clean-room."""

    FILES = (SPEC_DOC, MODEL_FILE, CURATED, ROOM_ACTS, Path(__file__).resolve())

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
        positional = "x = " + "argu" + "ment" + str(2) + ";"
        self.assertTrue(self._matches(ghidra_like))
        self.assertTrue(self._matches(positional))
        self.assertFalse(self._matches("a piece rolls inside the gem roll"))

    def test_no_signature_in_the_new_files(self):
        for path in self.FILES:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), path)
                self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [], path)

    def test_no_local_decompiler_paths_in_the_new_files(self):
        forbidden = ("hs-" + "decomp", "ghidra" + "_projects")
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                with self.subTest(path=path.name, word=word):
                    self.assertNotIn(word, text, path)
        # Positive control: the same check does see the words when they are there.
        self.assertIn(forbidden[1], "C:/Users/x/" + forbidden[1] + "/HeroSiege")


class SpecTests(unittest.TestCase):
    def test_the_spec_labels_its_claims_and_names_the_model(self):
        spec = SPEC_DOC.read_text(encoding="utf-8")
        positions = [spec.find("\n## " + heading + "\n") for heading in
                     ("Static reading", "Measured", "Not established", "Our code",
                      "The model", "What the model cannot catch")]
        self.assertTrue(min(positions) >= 0 and positions == sorted(positions), positions)
        for name in ("RoomActIndex", "DropGems", "GetDropRate", "LoadDrops",
                     "socketable_gem_of_incarnation", "Enemy_Child_Boss_obj", "Enemy_Parent_obj",
                     "Mevius_obj", "Pentagram_Boss_obj", "InventoryGridAddToStack", "GridAddToStack",
                     "IsItemTypeStackable", "IsStackable", "s_ItemOperation", "BAG_STACK_CAP", "999",
                     "consumable_edible_pas_logo", "PotionUse", "Portal_obj", "NetworkRoomGoto",
                     LIVE_1, "soul_piece_model", "boss_soul_pieces.json", "room_acts.json",
                     "max(1, floor(G × 4 / 5))", *model.HYPOTHESES):
            with self.subTest(name=name):
                self.assertIn(name, spec)

    def test_the_act_is_the_answer_everywhere(self):
        for path in (SPEC_DOC, MODEL_FILE):
            with self.subTest(path=path.name):
                self.assertFalse("minus one" in path.read_text(encoding="utf-8"), path.name)

    def test_the_model_stays_small_and_stdlib_only(self):
        source = MODEL_FILE.read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 240)
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "fractions", "typing"})
        # The game's stack rule only: ForgePact ships no stack hook.
        self.assertNotIn("veto", source.lower())


@unittest.skipUnless(FORGEPACT_HEADER.is_file(),
                     "ForgePact does not carry SoulPieceMod.hpp (hub CI checks out without "
                     "submodules, or the mod has not landed), so there is no source to compare "
                     "the curated file and the test transforms with")
class ParityTests(unittest.TestCase):
    """The curated file and the transforms above are SoulPieceMod.hpp's; pin them to it."""

    @classmethod
    def setUpClass(cls):
        header = FORGEPACT_HEADER.read_text(encoding="utf-8", errors="replace")
        cls.code = re.sub(r"//[^\n]*", "", header)

    def _constant(self, name):
        found = re.search(r"\b%s(?:\[\])?\s*=\s*([^;]+);" % re.escape(name), self.code)
        self.assertIsNotNone(found, name)
        return found.group(1).strip()

    def _words(self, name):
        found = re.search(r"\b%s\[\]\s*=\s*\{(.*?)\};" % re.escape(name), self.code, re.S)
        self.assertIsNotNone(found, name)
        return re.findall(r'"([^"]*)"', found.group(1))

    def _body(self, signature):
        found = re.search(re.escape(signature) + r"\([^)]*\)\s*\{(.*?)\n\}", self.code, re.S)
        self.assertIsNotNone(found, signature)
        return found.group(1)

    def test_header_matches_the_curated_file(self):
        self.assertEqual(int(self._constant("kActCount")), ACT_COUNT)
        self.assertEqual(int(self._constant("kSeedBase")), DATA["seed_base"])
        self.assertEqual(int(self._constant("kRatioNumerator")), DATA["ratio"]["numerator"])
        self.assertEqual(int(self._constant("kRatioDenominator")), DATA["ratio"]["denominator"])
        self.assertEqual(int(self._constant("kExpectedGemRate")), DATA["gem"]["expected_rate"])
        self.assertEqual(int(self._constant("kGemCategory")), DATA["gem"]["category"])
        self.assertEqual(self._constant("kGemRepoName"), '"%s"' % DATA["gem"]["repository_name"])
        self.assertEqual(int(self._constant("kBaseCategory")), DATA["base"]["category"])
        self.assertEqual(int(self._constant("kBaseItemType")), DATA["base"]["item_type"])
        self.assertEqual(self._constant("kBaseRepoName"), '"%s"' % DATA["base"]["repository_name"])
        self.assertEqual(self._constant("kMechanicTag"), '"%s"' % DATA["mechanic_tag"])
        # The first design's key base, spawn and stack veto are gone, and so is
        # Replan 1's portal (Amendment 2: a direct transfer).
        for gone in ("kKeyCategory", "kSpawnOffsetPx", "VetoStack", "Summon", "kPortalOffsetPx", "PortalX",
                     "PortalTarget", "UseVerdict::Portal"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, self.code)

    def test_the_act_table_is_the_header_s(self):
        table = re.search(r"kActs\[kActCount\]\s*=\s*\{(.*?)\n\};", self.code, re.S)
        self.assertIsNotNone(table)
        rows = re.findall(r'\{\s*(\d+)\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(true|false)\s*\}',
                          table.group(1))
        self.assertEqual(
            [(int(a), boss, name, room, named == "true") for a, boss, name, room, named in rows],
            [(r["act"], r["boss_object"], r["piece_name"], r["boss_room"], r["named"]) for r in DATA["acts"]])

    def test_the_verdict_words_are_the_header_s(self):
        self.assertEqual(self._words("kDropVerdictWords"), DATA["drop_verdicts"])
        self.assertEqual(self._words("kUseVerdictWords"), DATA["use_verdicts"])
        # DecideUse asks them in the words' order.
        returns = re.findall(r"return UseVerdict::(\w+);", self._body("inline UseVerdict DecideUse"))
        kebab = [re.sub(r"(?<!^)([A-Z])", r"-\1", word).lower() for word in returns]
        self.assertEqual(kebab, DATA["use_verdicts"])

    def test_the_act_is_the_room_act_index_answer(self):
        body = self._body("inline int ActOfRoomActIndex")
        self.assertRegex(body, r"answer\s*>=\s*1\.0")
        self.assertRegex(body, r"return static_cast<int>\(answer\);")
        self.assertNotRegex(body, r"answer\)?\s*\+\s*1")

    def test_the_room_rules_are_the_header_s(self):
        town = re.search(r"IsTownRoom\([^)]*\)\s*\{(.*?)\}", self.code, re.S).group(1)
        self.assertEqual(re.findall(r'starts_with\("([^"]+)"\)', town), list(DATA["room_rules"]["town_prefixes"]))
        boss = re.search(r"IsBossRoom\([^)]*\)\s*\{(.*?)\n\}", self.code, re.S).group(1)
        self.assertEqual(re.findall(r'find\("([^"]+)"\)', boss), list(DATA["room_rules"]["boss_room_substrings"]))
        self.assertEqual(re.findall(r'starts_with\("([^"]+)"\)', boss), list(DATA["room_rules"]["boss_room_prefixes"]))

    def test_the_denominator_floors_four_fifths_of_the_gem_rate(self):
        body = re.search(r"PieceDenominator\(double gemRate\)\s*\{(.*?)\n\}", self.code, re.S).group(1)
        self.assertRegex(body, r"if\s*\(\s*!\(\s*gemRate\s*>\s*0\.0\s*\)\s*\)\s*return 0;")
        self.assertRegex(body, r"std::floor\(\s*gemRate\s*\*[^;]*kRatioNumerator[^;]*/[^;]*kRatioDenominator")
        self.assertRegex(body, r"d\s*<\s*1\.0\s*\?\s*1")

    def test_key_piece_shape_matches_the_header(self):
        key, icon = DATA["key_base"], DATA["icon"]
        self.assertEqual(int(self._constant("kKeyBaseCategory")), key["category"])
        self.assertEqual(int(self._constant("kKeyBaseItemType")), key["item_type"])
        self.assertEqual(int(self._constant("kKeyBaseItemType")), KEY_BASE_CLASS)
        self.assertEqual(self._constant("kKeyBaseRepoName"), '"%s"' % key["repository_name"])
        self.assertEqual(Fraction(self._constant("kActFractionDivisor")), ACT_FRACTION_DIVISOR)
        self.assertEqual(Fraction(self._constant("kKeyPieceTolerance")), KEY_PIECE_TOLERANCE)
        self.assertEqual(self._constant("kIconInfoKey"), '"%s"' % icon["info_key"])
        self.assertEqual(self._constant("kPieceSpriteName"), '"%s"' % icon["sprite"])
        self.assertEqual(self._constant("kGroundSpritePrefix")[1:-1] + icon["sprite"], icon["ground_sprite"])
        # KeyPieceB is the transform's index + act / divisor, and nothing for no act.
        body = self._body("inline double KeyPieceB")
        self.assertRegex(body, r"if\s*\(\s*baseIndex\s*<\s*0\s*\|\|\s*!IsAct\(act\)\s*\)\s*return -1\.0;")
        self.assertRegex(body, r"static_cast<double>\(baseIndex\)\s*\+\s*static_cast<double>\(act\)\s*/\s*kActFractionDivisor")
        # KeyPieceActOfItem truncates as the repository lookup does, refuses a
        # whole `b` and checks the seed's act within the tolerance.
        body = self._body("inline int KeyPieceActOfItem")
        self.assertIn("kKeyBaseItemType", body)
        self.assertRegex(body, r"std::trunc\(b\)\s*!=\s*static_cast<double>\(baseIndex\)")
        self.assertRegex(body, r"b\s*-\s*std::trunc\(b\)\s*<=\s*kKeyPieceTolerance")
        self.assertRegex(body, r"ActOfSeed\(seed\)")
        self.assertRegex(body, r"KeyPieceB\(baseIndex,\s*act\)\)\s*>\s*kKeyPieceTolerance")

    def test_stack_cap_matches_the_header(self):
        self.assertEqual(int(self._constant("kBagStackCap")), DATA["bag_stack"]["cap"])
        self.assertEqual(int(self._constant("kBagStackCap")), model.BAG_STACK_CAP)
        # DecideMerge holds the summed count within that cap, and only for a bag piece.
        body = self._body("inline MergeDecision DecideMerge")
        self.assertRegex(body, r"have\s*>\s*kBagStackCap\s*-\s*adding")
        self.assertIn("BagPieceActOfItem(incoming", body)

    def test_a_zero_count_is_one_piece_to_the_merge_but_not_to_the_model(self):
        # The documented difference (spec § Our code, "The bag merge"): the
        # merge's StackCount takes a count under 1 as one piece, while the
        # model's `stacks` sums the raw `o`. What the game does with 0 is not read.
        self.assertRegex(self.code, r"inline long long StackCount\(long long count\)\s*\{\s*"
                                    r"return count < 1 \? 1 : count;\s*\}")
        self.assertIn("StackCount(incoming.count)", self._body("inline MergeDecision DecideMerge"))
        held = model.Item(13, 4, 0, 1)
        cap = model.BAG_STACK_CAP
        # The model: a held count of 0 adds nothing, so a full incoming stack still fits.
        self.assertTrue(model.stacks(held._replace(o=0), held._replace(a=2, o=cap)))
        # The merge's count (StackCount, as pinned above) of the same pair is
        # one over the cap, so DecideMerge's `have > kBagStackCap - adding` refuses it.
        def stack_count(count):
            return 1 if count < 1 else count
        self.assertEqual(stack_count(0), 1)
        self.assertTrue(stack_count(0) > cap - stack_count(cap))
        # Negative control: from a count of 1 the two agree, and both refuse.
        self.assertFalse(model.stacks(held._replace(o=1), held._replace(a=2, o=cap)))

    def test_the_transfer_leads_to_the_boss_room(self):
        self.assertRegex(self._body("inline const char* TransferTarget"), r"boss->bossRoom")
        self.assertRegex(self._body("inline UseVerdict DecideUse"), r"return UseVerdict::Transfer;")

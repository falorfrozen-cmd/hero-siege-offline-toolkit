"""Checks for `hs_game_sdk.dungeon_chest_model` (ForgePact#31).

The model is written from `docs/models/dungeon-chest-spec.md` and covers the game
only: a key dungeon's end chest (`Dungeon_Chest_obj`) polls
`instance_exists(Enemy_Parent_obj)` and opens once no monster is alive, and the
dungeon's monsters stream in from creators that all exist at entry, so its
planned total is a sum taken at the chest's first sight. ForgePact's Dungeon
chest opens early control (`dungeonchest <pct>`) is our code, so it lives here as
input transforms (`set_mode`, `known_total`, `clamped`, `threshold`, `reached`,
`countdown`, `shown`). `LeverParityTests` pins those to ForgePact's source when
ForgePact carries the mod.

Baseline: what the game does with no mod. Target: what the control must turn it
into. That is the order `AGENTS.md` § "Mod Development Workflow" asks for. Live
procedure 1 answered four of the model's open questions; where the planned total
lives (a per-creator count read by name, or an estimate) is still open, and
`HypothesisTests` keeps it `None` until a measured entry of the curated file
answers it.

Each entry of `hs-game-sdk/curated/dungeon_chest_measurements.json` names the test
that reproduces it (`reproduced_by`) or says why none can (`not_reproduced`).

Run from the hub root: `py -3 -m unittest tests.test_dungeon_chest_model -v`.
"""
import ast
import inspect
import json
import re
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
FIXTURE = ROOT / "hs-game-sdk" / "curated" / "dungeon_chest_measurements.json"
MODEL_FILE = SDK_PY / "hs_game_sdk" / "dungeon_chest_model.py"
SPEC_DOC = ROOT / "docs" / "models" / "dungeon-chest-spec.md"
HOOKS_DIR = ROOT / ".claude" / "hooks"
FORGEPACT = ROOT / "ForgePact"
FORGEPACT_HEADER = FORGEPACT / "plugin" / "include" / "ForgePact" / "DungeonChestMod.hpp"
FORGEPACT_PANEL = FORGEPACT / "src" / "forgepact.py"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import dungeon_chest_model as model  # noqa: E402

# ---- ForgePact's Dungeon chest opens early, as input transforms (our code, not the game's) ----

#: The percentages the command stores (any whole number in this range).
FORGEPACT_PCT_MIN, FORGEPACT_PCT_MAX = 50, 95
#: The panel slider's resting value (`dungeon_chest_pct`'s default).
FORGEPACT_PCT_DEFAULT = 75
#: The countdown shows only when this many kills or fewer remain.
FORGEPACT_COUNTDOWN_LIMIT = 50
#: The off mode: the game's own rule.
OFF = None
#: The forms `HYPOTHESES['planned_total_source']` may take once Live 1b decides it.
TOTAL_SOURCES = ("variable", "estimate")


def set_mode(current, asked):
    """`dungeonchest <asked>`: off (`off` or `0`), or a whole number 50..95.
    Anything else is refused and the mode stays `current`."""
    if asked in ("off", "0") or (type(asked) is int and asked == 0):
        return OFF
    if isinstance(asked, str) and re.fullmatch(r"\d+", asked):
        asked = int(asked)
    if type(asked) is int and FORGEPACT_PCT_MIN <= asked <= FORGEPACT_PCT_MAX:
        return asked
    return current


def known_total(answer, creators):
    """What the mod takes from its total source at first sight: `None` (unknown)
    when there is no source, or when it answers 0 while creators are present."""
    if answer is None or (answer == 0 and creators > 0):
        return None
    return answer


def clamped(total, kills, alive):
    """The clamp: the total is never below the monsters already seen."""
    if total is None:
        return None
    return max(total, kills + alive)


def threshold(pct, total):
    """`ceil(pct / 100 * total)`, in whole numbers; `None` while off or unknown."""
    if pct is OFF or total is None:
        return None
    return -(-pct * total // 100)


def reached(pct, kills, total, alive):
    """Whether the chest may open: the game's rule always holds; while on with a
    known total, also once `kills >= threshold` of the clamped total."""
    if model.chest_openable(alive):
        return True
    t = threshold(pct, clamped(total, kills, alive))
    return t is not None and kills >= t


def countdown(pct, kills, total, alive):
    """Kills left to the threshold, never below 0; `None` while off or unknown."""
    t = threshold(pct, clamped(total, kills, alive))
    return None if t is None else max(0, t - kills)


def shown(pct, kills, total, alive, latched=False):
    """Whether `Chest: <n> kills to go` is shown: on, known, not latched, 0 < n <= 50."""
    n = countdown(pct, kills, total, alive)
    return n is not None and not latched and 0 < n <= FORGEPACT_COUNTDOWN_LIMIT


def _entries():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["measurements"]


def _entry(entry_id):
    return next(e for e in _entries() if e["id"] == entry_id)


class BaselineTests(unittest.TestCase):
    """The game with no mod: the chest opens only once no monster is alive."""

    def test_baseline_openable_only_when_no_monster_is_alive(self):
        for alive in range(0, 120):
            with self.subTest(alive=alive):
                self.assertEqual(model.chest_openable(alive), alive == 0)
        self.assertEqual(model.VANILLA_UNLOCK_ALIVE, 0)

    def test_dc2_the_rule_reads_only_the_alive_count(self):
        # The model takes the alive count as given (DC2: the Step calls no script
        # that counts enemies; DC10: the chest asks a builtin instead).
        self.assertEqual(list(inspect.signature(model.chest_openable).parameters), ["alive"])
        for total in (1, 7, 40, 300):
            for kills in range(0, total + 1):
                with self.subTest(total=total, kills=kills):
                    alive = total - kills
                    self.assertEqual(model.chest_openable(alive), kills == total)

    def test_dc4_the_static_reading_left_the_unlock_route_to_live(self):
        # DC4 is a static reading and answers nothing; each unlock-route answer
        # the model holds comes from a measured entry (DC9, DC10).
        self.assertEqual(_entry("DC4")["status"], "static_reading")
        self.assertNotIn("hypothesis", _entry("DC4"))
        measured = {e.get("hypothesis"): e for e in _entries() if e["status"] == "measured"}
        for key in ("unlock_is_a_builtin_poll", "unlock_is_a_variable"):
            with self.subTest(key=key):
                self.assertIn(key, model.HYPOTHESES)
                self.assertIn(key, measured)
                self.assertEqual(model.HYPOTHESES[key], measured[key]["values"]["verdict"])

    def test_dc6_a_kill_is_counted_once_toward_the_total(self):
        total = 40
        for kills in range(0, total + 1):
            with self.subTest(kills=kills):
                self.assertEqual(model.progress(kills, total), Fraction(kills, total))
        self.assertEqual(model.progress(total, total), 1)
        self.assertEqual(model.kills_to_vanilla(0), 0)

    def test_dc7_monsters_stream_in_so_kills_plus_alive_is_not_the_total(self):
        values = _entry("DC7")["values"]
        path = [tuple(p) for p in values["path"]]
        total = values["kills_to_clear"]
        self.assertEqual(path[0], (values["alive_entry"], 0))
        self.assertEqual(path[-1], (0, total))
        self.assertIn((values["alive_peak"], values["kills_at_peak"]), path)
        seen = [kills + alive for alive, kills in path]
        # Kills plus alive rose from 44 to 600: it is not the dungeon's total ...
        self.assertGreater(len(set(seen)), 1)
        self.assertEqual(seen[-1], total)
        self.assertTrue(all(s <= total for s in seen))
        # ... and a share over it is far too early: 50 % of the 44 at entry is 22
        # kills, under 4 % of the 600 the dungeon held.
        self.assertEqual(threshold(50, seen[0]), 22)
        self.assertLess(model.progress(22, total), Fraction(1, 25))
        self.assertIs(model.HYPOTHESES["all_monsters_alive_at_entry"], False)

    def test_dc8_every_creator_is_there_at_entry_and_stays(self):
        values = _entry("DC8")["values"]
        creators, clear = values["creators_first_tick"], _entry("DC11")["values"]["kills_to_clear"]
        self.assertEqual(values["creators_at_clear"], creators)
        self.assertGreater(creators, 0)
        self.assertIs(model.HYPOTHESES["no_creators_in_dungeon"], False)
        # A whole count per creator can carry the measured total: 600 over 122
        # creators is 112 creators of 5 and 10 of 4 (Σ planned, 0 alive).
        fives = clear - 4 * creators
        counts = [5] * fives + [4] * (creators - fives)
        self.assertEqual(len(counts), creators)
        self.assertEqual(model.planned_total(0, counts), clear)

    def test_dc10_the_game_s_rule_is_the_chest_s_own_poll(self):
        values = _entry("DC10")["values"]
        self.assertEqual((values["builtin"], values["arg"]), ("instance_exists", "Enemy_Parent_obj"))
        self.assertGreater(values["calls_at_entry"], 0)
        self.assertGreater(values["calls_at_end"], values["calls_at_entry"])
        self.assertEqual(set(values["chest_self_calls"].values()), {0})
        self.assertIs(model.HYPOTHESES["unlock_is_a_builtin_poll"], True)
        # instance_exists answers "some monster exists" exactly when alive > 0,
        # whatever the dungeon's total: the chest opens only on its "no".
        for total in (7, 40, 600):
            for alive in (0, 1, total):
                with self.subTest(total=total, alive=alive):
                    self.assertEqual(model.chest_openable(alive), not alive > 0)

    def test_dc11_the_estimate_route_reproduces_the_clear(self):
        values = _entry("DC11")["values"]
        clear, alive0, creators = values["kills_to_clear"], values["alive_entry"], values["creators"]
        mean = Fraction(values["mean_per_pending_creator"])
        self.assertEqual(mean, Fraction(clear - alive0, creators))
        self.assertEqual(model.estimated_total(alive0, creators, mean), clear)
        # Alive at first sight plus Σ planned over pending creators gives the same.
        fives = clear - alive0 - 4 * creators
        counts = [5] * fives + [4] * (creators - fives)
        self.assertEqual(model.planned_total(alive0, counts), clear)
        # The estimate rounds up: 3 creators at 1/2 each is 2 monsters, not 1.
        self.assertEqual(model.estimated_total(0, 3, Fraction(1, 2)), 2)
        self.assertEqual(model.estimated_total(10, 0, Fraction(9, 2)), 10)

    def test_kills_to_vanilla_is_every_living_monster(self):
        for alive in (0, 1, 7, 40):
            self.assertEqual(model.kills_to_vanilla(alive), alive)

    def test_off_reproduces_the_game(self):
        for total in (0, 1, 7, 40, 120, None):
            for kills in range(0, (total or 0) + 1):
                for alive in {(total or 0) - kills, 0, 5}:
                    with self.subTest(total=total, kills=kills, alive=alive):
                        self.assertEqual(reached(OFF, kills, total, alive), model.chest_openable(alive))
                        self.assertIsNone(countdown(OFF, kills, total, alive))
                        self.assertFalse(shown(OFF, kills, total, alive))

    def test_an_unknown_total_is_refused(self):
        # No source, or a source that answers 0 while creators are present.
        for answer, creators in ((None, 122), (None, 0), (0, 122), (0, 1)):
            with self.subTest(answer=answer, creators=creators):
                total = known_total(answer, creators)
                self.assertIsNone(total)
                for pct in (FORGEPACT_PCT_MIN, FORGEPACT_PCT_MAX):
                    self.assertIsNone(threshold(pct, clamped(total, 300, 44)))
                    self.assertIsNone(countdown(pct, 300, total, 44))
                    self.assertFalse(shown(pct, 300, total, 44))
                    # Refused means the game's rule: shut while a monster lives.
                    self.assertFalse(reached(pct, 300, total, 44))
                    self.assertTrue(reached(pct, 600, total, 0))
        with self.assertRaises(ValueError):
            model.progress(1, 0)
        # Negative control: a real answer is kept.
        self.assertEqual(known_total(600, 122), 600)
        self.assertEqual(threshold(50, known_total(600, 122)), 300)

    def test_values_are_exact(self):
        self.assertIsInstance(model.progress(1, 2), Fraction)
        self.assertIsInstance(model.planned_total(1, [2]), int)
        self.assertIsInstance(model.estimated_total(1, 2, Fraction(1, 3)), int)

    def test_nonsense_is_refused(self):
        for bad in (-1, -40):
            with self.assertRaises(ValueError):
                model.chest_openable(bad)
            with self.assertRaises(ValueError):
                model.planned_total(bad, [])
            with self.assertRaises(ValueError):
                model.planned_total(0, [1, bad])
            with self.assertRaises(ValueError):
                model.estimated_total(0, bad, 1)
            with self.assertRaises(ValueError):
                model.estimated_total(0, 1, Fraction(bad))
        for bad in (True, 1.0, "3", None):
            with self.assertRaises(TypeError):
                model.chest_openable(bad)
            with self.assertRaises(TypeError):
                model.progress(bad, 1)
            with self.assertRaises(TypeError):
                model.planned_total(0, [bad])
            with self.assertRaises(TypeError):
                model.estimated_total(0, 1, bad)


class TargetTests(unittest.TestCase):
    """What the control must turn the game into (spec § "Our code")."""

    def test_target_pct_50_of_600_latches_at_the_300th_kill(self):
        pct, total = 50, 600
        self.assertEqual(threshold(pct, total), 300)
        self.assertFalse(reached(pct, 299, total, 120))
        self.assertTrue(reached(pct, 300, total, 120))
        # The game alone would still want the 120 alive and whatever is unspawned.
        self.assertFalse(model.chest_openable(120))
        self.assertEqual(countdown(pct, 250, total, 150), 50)
        self.assertTrue(shown(pct, 250, total, 150))
        self.assertEqual(countdown(pct, 249, total, 150), 51)
        self.assertFalse(shown(pct, 249, total, 150))

    def test_target_the_countdown_only_counts_down_while_monsters_stream_in(self):
        pct, total = 50, 600
        # Live 1's own path: the clamp never moves T, so n is 300 - kills.
        for alive, kills in (tuple(p) for p in _entry("DC7")["values"]["path"]):
            with self.subTest(alive=alive, kills=kills):
                self.assertEqual(clamped(total, kills, alive), total)
                self.assertEqual(countdown(pct, kills, total, alive), max(0, 300 - kills))
        # Any alive count the planned total allows: monotone down to 0 at kill 300.
        last = None
        for kills in range(0, 301):
            alive = min((kills * 37) % 211, total - kills)
            n = countdown(pct, kills, total, alive)
            with self.subTest(kills=kills, alive=alive):
                if last is not None:
                    self.assertLessEqual(n, last)
                last = n
        self.assertEqual(last, 0)

    def test_target_pct_95_with_7_monsters_rounds_up_to_all_of_them(self):
        # 95 % of 7 is 6.65: rounding up asks for all 7, the same kill the game opens at.
        self.assertEqual(threshold(95, 7), 7)
        self.assertFalse(reached(95, 6, 7, 1))
        self.assertTrue(reached(95, 7, 7, 0))
        self.assertEqual(model.kills_to_vanilla(7), 7)

    def test_target_pct_50_of_a_planned_40_opens_at_the_20th_kill(self):
        # The parent's scenario, now over a planned total with packs still to spawn.
        pct, total = 50, 40
        self.assertEqual(threshold(pct, total), 20)
        self.assertEqual(countdown(pct, 0, total, 10), 20)
        self.assertTrue(shown(pct, 0, total, 10))
        self.assertFalse(reached(pct, 19, total, 5))
        self.assertEqual(countdown(pct, 19, total, 5), 1)
        self.assertTrue(reached(pct, 20, total, 5))
        self.assertEqual(countdown(pct, 20, total, 5), 0)
        self.assertFalse(shown(pct, 20, total, 5))
        # The game alone would still want the 5 alive and the 15 unspawned.
        self.assertFalse(model.chest_openable(5))

    def test_target_the_clamp_keeps_the_total_at_or_above_what_was_seen(self):
        # A planned 10, but 8 killed and 5 alive: 13 seen, so T is 13.
        self.assertEqual(clamped(10, 8, 5), 13)
        self.assertEqual(threshold(50, clamped(10, 8, 5)), 7)
        # Negative control: unclamped, the share would be over 10, not 13.
        self.assertEqual(threshold(50, 10), 5)
        for pct in range(FORGEPACT_PCT_MIN, FORGEPACT_PCT_MAX + 1):
            for total in range(0, 31):
                for kills in range(0, 16):
                    for alive in (0, 1, 5, 20):
                        tc = clamped(total, kills, alive)
                        t = threshold(pct, tc)
                        with self.subTest(pct=pct, total=total, kills=kills, alive=alive):
                            self.assertGreaterEqual(tc, kills + alive)
                            # Never past every monster seen or planned: kills + alive ... T.
                            self.assertLessEqual(t, tc)
                            expected = alive == 0 or (tc > 0 and model.progress(kills, tc) >= Fraction(pct, 100))
                            self.assertEqual(reached(pct, kills, total, alive), expected)

    def test_target_never_before_pct_of_the_planned_total(self):
        for pct in range(FORGEPACT_PCT_MIN, FORGEPACT_PCT_MAX + 1):
            for total in range(1, 161):
                t = threshold(pct, total)
                with self.subTest(pct=pct, total=total):
                    self.assertLessEqual(t, total)
                    self.assertGreaterEqual(model.progress(t, total), Fraction(pct, 100))
                    self.assertLess(model.progress(t - 1, total), Fraction(pct, 100))
                    # With nothing left to spawn, the game's rule implies the mod's.
                    self.assertTrue(reached(pct, total, total, 0))

    def test_target_an_empty_dungeon_is_reached_at_once(self):
        total = known_total(0, 0)
        self.assertEqual(total, 0)
        for pct in (FORGEPACT_PCT_MIN, FORGEPACT_PCT_DEFAULT, FORGEPACT_PCT_MAX):
            with self.subTest(pct=pct):
                self.assertEqual(threshold(pct, total), 0)
                self.assertTrue(reached(pct, 0, total, 0))
                self.assertEqual(countdown(pct, 0, total, 0), 0)
                self.assertFalse(shown(pct, 0, total, 0))

    def test_target_the_countdown_shows_the_last_50_kills_only(self):
        pct, total = 95, 100  # threshold 95
        self.assertEqual(threshold(pct, total), 95)
        self.assertEqual(countdown(pct, 0, total, 30), 95)
        self.assertFalse(shown(pct, 0, total, 30))
        self.assertEqual(countdown(pct, 44, total, 30), 51)
        self.assertFalse(shown(pct, 44, total, 30))
        self.assertEqual(countdown(pct, 45, total, 30), 50)
        self.assertTrue(shown(pct, 45, total, 30))
        self.assertEqual(countdown(pct, 94, total, 6), 1)
        self.assertTrue(shown(pct, 94, total, 6))
        self.assertEqual(countdown(pct, 95, total, 5), 0)
        self.assertFalse(shown(pct, 95, total, 5))

    def test_target_a_latched_threshold_hides_the_countdown(self):
        self.assertTrue(shown(50, 10, 40, 30))
        self.assertFalse(shown(50, 10, 40, 30, latched=True))

    def test_target_the_mode_stores_50_to_95_and_refuses_the_rest(self):
        for asked in (50, 73, 95, "50", "73", "95"):
            with self.subTest(asked=asked):
                self.assertEqual(set_mode(OFF, asked), int(asked))
        for asked in (49, 96, "49", "96", "abc", "", 73.5, "73.5", True, None, -50):
            with self.subTest(asked=asked):
                self.assertIs(set_mode(OFF, asked), OFF)
                self.assertEqual(set_mode(80, asked), 80)
        for asked in ("off", 0, "0"):
            with self.subTest(asked=asked):
                self.assertIs(set_mode(80, asked), OFF)
        self.assertTrue(FORGEPACT_PCT_MIN <= FORGEPACT_PCT_DEFAULT <= FORGEPACT_PCT_MAX)


class HypothesisTests(unittest.TestCase):
    """Each open question stays `None` until a measured curated entry answers it."""

    def test_every_hypothesis_is_none_until_measured(self):
        answers = {}
        for entry in _entries():
            if entry["status"] == "measured" and entry.get("hypothesis"):
                values = entry["values"] or {}
                self.assertIn("verdict", values, entry["id"])
                if entry["hypothesis"] == "planned_total_source":
                    self.assertIn(values["verdict"], TOTAL_SOURCES, entry["id"])
                else:
                    self.assertIsInstance(values["verdict"], bool, entry["id"])
                answers[entry["hypothesis"]] = values["verdict"]
        for key, value in model.HYPOTHESES.items():
            with self.subTest(key=key):
                self.assertEqual(value, answers.get(key))

    def test_every_hypothesis_named_by_an_entry_is_the_model_s(self):
        named = [e["hypothesis"] for e in _entries() if "hypothesis" in e]
        self.assertTrue(named)
        for key in named:
            self.assertIn(key, model.HYPOTHESES)
        self.assertEqual(sorted(named), sorted(set(named)))

    def test_live_one_answered_four_questions(self):
        checks = {e.get("live_check"): e for e in _entries()}
        for check, key, verdict in (("alive-count", "all_monsters_alive_at_entry", False),
                                    ("creators-in-dungeon", "no_creators_in_dungeon", False),
                                    ("unlock-signal", "unlock_is_a_variable", False),
                                    ("builtin-poll", "unlock_is_a_builtin_poll", True)):
            with self.subTest(check=check):
                entry = checks[check]
                self.assertEqual(entry["hypothesis"], key)
                self.assertEqual(entry["status"], "measured")
                self.assertTrue(entry["source"].endswith("-live-1.md"), entry["id"])
                self.assertIs(entry["values"]["verdict"], verdict)
                self.assertIs(model.HYPOTHESES[key], verdict)
        # The kill-tally question went with the old denominator.
        self.assertNotIn("kill_tally_matches_alive_drop", model.HYPOTHESES)

    def test_live_1b_placeholders_are_present(self):
        checks = {e.get("live_check"): e for e in _entries()}
        for check in ("creator-sum", "creator-match", "creator-state", "kills-equal-births", "unlock-works"):
            with self.subTest(check=check):
                self.assertIn(check, checks)
                if checks[check]["status"] == "pending":
                    self.assertIsNone(checks[check]["values"])
        self.assertEqual(checks["creator-sum"]["hypothesis"], "planned_total_source")
        if checks["creator-sum"]["status"] == "pending":
            self.assertIsNone(model.HYPOTHESES["planned_total_source"])

    def test_a_report_does_not_count_as_a_measurement(self):
        # Negative control: a `reported` or `pending` entry carrying a verdict answers nothing.
        fake = [{"status": "reported", "hypothesis": "boss_dungeon_same_rule", "values": {"verdict": True}},
                {"status": "pending", "hypothesis": "planned_total_source", "values": {"verdict": "variable"}}]
        answered = {e["hypothesis"] for e in fake if e["status"] == "measured"}
        self.assertEqual(answered, set())


class DungeonChestFamilyTests(unittest.TestCase):
    """The objects the spec names, against `hs-game-sdk`'s object tables."""

    def test_the_objects_are_the_sdks(self):
        from hs_game_sdk import objects
        GameObject = objects.GameObject
        for name, index in (("Dungeon_Chest_obj", 1366), ("Dungeon_Boss_Blocker_obj", 1365),
                            ("Spawn_Dungeon_obj", 4667), ("Enemy_Parent_obj", 1429),
                            ("Enemy_Creator_obj", 1415), ("Enemy_Death_Effect_obj", 1420)):
            with self.subTest(name=name):
                self.assertEqual(int(GameObject[name]), index)

    def test_alive_counts_monsters_not_creators_or_chests(self):
        # `instance_exists(Enemy_Parent_obj)` is what the chest asks (DC10): a
        # creator or the chest itself is not in that family, so neither keeps it shut.
        from hs_game_sdk import objects
        GameObject = objects.GameObject
        for name in ("Enemy_Creator_obj", "Dungeon_Chest_obj", "Dungeon_Boss_Blocker_obj",
                     "Spawn_Dungeon_obj", "Enemy_Death_Effect_obj"):
            with self.subTest(name=name):
                self.assertFalse(objects.is_descendant_of(GameObject[name], GameObject.Enemy_Parent_obj))
        # Positive control: an ordinary monster family is in it.
        self.assertTrue(objects.is_descendant_of(GameObject.Enemy_Child_Basic_obj, GameObject.Enemy_Parent_obj))


class FixtureShapeTests(unittest.TestCase):
    REQUIRED = ("id", "kind", "status", "date", "source", "scripts", "objects", "what", "values", "model")

    @classmethod
    def setUpClass(cls):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.note = data["$schema_note"]
        cls.entries = data["measurements"]

    def test_every_entry_has_the_fields(self):
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({"DC%d" % n for n in range(1, 19)} <= set(ids))
        self.assertIn("dungeon-chest-spec.md", self.note)
        for entry in self.entries:
            for field in self.REQUIRED:
                self.assertIn(field, entry, entry.get("id"))
            self.assertRegex(entry["id"], r"^DC\d+$")
            self.assertIn(entry["kind"], ("baseline", "target", "our_code"), entry["id"])
            self.assertIn(entry["status"],
                          ("static_reading", "measured", "reported", "pending", "not_observed"), entry["id"])
            self.assertRegex(entry["date"], r"^\d{4}-\d{2}-\d{2}$", entry["id"])
            self.assertEqual(("reproduced_by" in entry) + ("not_reproduced" in entry), 1,
                             f"{entry['id']} needs exactly one of reproduced_by / not_reproduced")

    def test_every_named_test_exists_in_this_module(self):
        named = 0
        for entry in self.entries:
            if "reproduced_by" not in entry:
                continue
            dotted = entry["reproduced_by"]
            prefix = "tests.test_dungeon_chest_model."
            self.assertTrue(dotted.startswith(prefix), dotted)
            class_name, method = dotted[len(prefix):].split(".")
            cls = globals().get(class_name)
            self.assertIsNotNone(cls, dotted)
            self.assertTrue(method.startswith("test_"), dotted)
            self.assertTrue(callable(getattr(cls, method, None)), dotted)
            named += 1
        self.assertGreater(named, 0)

    def test_every_script_is_bound_in_the_sdk(self):
        from hs_game_sdk.scripts import GameScript
        for entry in self.entries:
            for name in entry["scripts"]:
                self.assertIn(name, GameScript.__members__, f"{entry['id']}: {name}")
        # Negative control: an unbound name is not in the table.
        self.assertNotIn("gml_Script_" + "NoSuchChestScript", GameScript.__members__)

    def test_every_object_is_the_sdk_s_index(self):
        from hs_game_sdk.objects import OBJECT_NAME_TO_INDEX
        for entry in self.entries:
            self.assertTrue(entry["objects"], entry["id"])
            for name, index in entry["objects"].items():
                self.assertEqual(OBJECT_NAME_TO_INDEX.get(name), index, f"{entry['id']}: {name}")
        self.assertIsNone(OBJECT_NAME_TO_INDEX.get("No_Such_Chest_obj"))

    def _assert_sections(self, entry_id, path_text, sections):
        # Each section text appears in the file, in the order given.
        text = (ROOT / path_text).read_text(encoding="utf-8")
        at = 0
        for section in sections:
            found = text.find(section, at)
            self.assertGreaterEqual(found, 0, f"{entry_id}: {path_text}: {section}")
            at = found + len(section)

    def test_source_paths_exist_where_they_can_be_checked(self):
        # Hub CI checks out without submodules, and a Live capture under
        # .claude/workorders/ is local, so each is only checked where it exists.
        # A source is `<path> § <section>`, or a Live capture's bare path with
        # `capture_section` (text in the capture) and `tracked_copy` (`<path> §
        # <section> › <subsection>`, the committed write-up of the same session).
        forgepact_present = (FORGEPACT / "src").is_dir()
        checked = 0
        for entry in self.entries:
            path_text, sep, section = entry["source"].partition(" § ")
            if sep:
                self.assertTrue(path_text and section, entry["id"])
                sections = [section]
            else:
                self.assertRegex(path_text, r"^\.claude/workorders/[\w.-]+-live-[\w]+\.md$", entry["id"])
                self.assertTrue(entry.get("capture_section"), entry["id"])
                copy_path, copy_sep, copy_sections = entry.get("tracked_copy", "").partition(" § ")
                self.assertTrue(copy_sep and copy_path and copy_sections, entry["id"])
                if not copy_path.startswith("ForgePact/") or forgepact_present:
                    self._assert_sections(entry["id"], copy_path, copy_sections.split(" › "))
                    checked += 1
                sections = [entry["capture_section"]]
            if path_text.startswith("ForgePact/") and not forgepact_present:
                continue
            path = ROOT / path_text
            if path_text.startswith(".claude/workorders/") and not path.is_file():
                continue
            self.assertTrue(path.is_file(), f"{entry['id']}: {path_text}")
            self._assert_sections(entry["id"], path_text, sections)
            checked += 1
        self.assertGreater(checked, 0)


class NoDecompilerOutputTests(unittest.TestCase):
    """The spec and the model were written clean-room; nothing they ship may carry listing text."""

    FILES = (SPEC_DOC, MODEL_FILE, FIXTURE, Path(__file__).resolve())

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
        self.assertFalse(self._matches("the chest opens once no monster is alive"))

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
        for heading in ("Static reading", "Measured", "Not established", "Our code",
                        "The model", "What the model cannot catch"):
            self.assertRegex(spec, re.compile("^## " + heading + "$", re.M))
        for name in ("Dungeon_Chest_obj", "EnemyDestroyKillProc", "Enemy_Parent_obj",
                     "dungeon_chest_model", "dungeon_chest_measurements.json",
                     "planned total", "first sight", "max(T, k + a)",
                     "ceil(p × T / 100)", "max(0, t − k)", "0 < n ≤ 50", *model.HYPOTHESES):
            with self.subTest(name=name):
                self.assertIn(name, spec)
        # The parent's denominator (kills over kills + alive) is gone.
        self.assertNotIn("k / (k + a)", spec)
        self.assertNotIn("ceil(p × (k + a) / 100)", spec)

    def test_the_model_stays_small_and_stdlib_only(self):
        source = MODEL_FILE.read_text(encoding="utf-8")
        self.assertLess(len(source.splitlines()), 120)
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "fractions", "typing"})


@unittest.skipUnless(FORGEPACT_HEADER.is_file() and FORGEPACT_PANEL.is_file(),
                     "ForgePact does not carry DungeonChestMod.hpp (hub CI checks out without "
                     "submodules, or the mod has not landed), so there is no source to compare "
                     "the test transforms with")
class LeverParityTests(unittest.TestCase):
    """The transforms above are ForgePact's Dungeon chest opens early; pin them to its source.

    The header and this test are written at the same time (ForgePact#31's model and
    plugin lanes), so the pins read what the plan fixes (the bounds, the countdown
    text, rounding up, the panel's keys and defaults) rather than the header's names.
    """

    @classmethod
    def setUpClass(cls):
        cls.header = FORGEPACT_HEADER.read_text(encoding="utf-8", errors="replace")
        cls.panel = FORGEPACT_PANEL.read_text(encoding="utf-8-sig", errors="replace")

    def test_the_bounds_and_the_countdown_limit_are_in_the_header(self):
        code = re.sub(r"//[^\n]*", "", self.header)
        for value in (FORGEPACT_PCT_MIN, FORGEPACT_PCT_MAX, FORGEPACT_COUNTDOWN_LIMIT):
            with self.subTest(value=value):
                self.assertRegex(code, r"\b%d\b" % value)

    def test_the_countdown_text_is_the_header_s(self):
        self.assertIn("Chest: ", self.header)
        self.assertIn("kills to go", self.header)
        self.assertIn("ready to open", self.header)

    def test_the_threshold_rounds_up(self):
        code = re.sub(r"//[^\n]*", "", self.header)
        self.assertRegex(code, r"\+\s*99\s*\)\s*/\s*100|\bceil\b|%\s*100")

    def test_the_panel_keys_and_defaults(self):
        tree = ast.parse(self.panel)
        defaults = [node.value for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets)]
        self.assertEqual(len(defaults), 1)
        values = {ast.literal_eval(k): v for k, v in zip(defaults[0].keys, defaults[0].values)
                  if k is not None and isinstance(k, ast.Constant)}
        self.assertIn("mod_dungeon_chest", set(values))
        self.assertIn("dungeon_chest_pct", set(values))
        self.assertIs(ast.literal_eval(values["mod_dungeon_chest"]), False)
        self.assertEqual(ast.literal_eval(values["dungeon_chest_pct"]), FORGEPACT_PCT_DEFAULT)


if __name__ == "__main__":
    unittest.main()

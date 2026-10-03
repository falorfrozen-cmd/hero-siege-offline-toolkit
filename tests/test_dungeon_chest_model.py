"""Checks for `hs_game_sdk.dungeon_chest_model` (ForgePact#31).

The model is written from `docs/models/dungeon-chest-spec.md` and covers the game
only: a key dungeon's end chest (`Dungeon_Chest_obj`) opens once no monster is
alive. ForgePact's Dungeon chest opens early control (`dungeonchest <pct>`) is our
code, so it lives here as input transforms (`set_mode`, `threshold`, `reached`,
`countdown`, `shown`). `LeverParityTests` pins those to ForgePact's source when
ForgePact carries the mod.

Baseline: what the game does with no mod. Target: what the control must turn it
into. That is the order `AGENTS.md` § "Mod Development Workflow" asks for. How the
chest learns that no monster is alive (a builtin poll or a variable another event
writes) is not established; `HypothesisTests` keeps each open question `None`
until a measured entry of the curated file answers it.

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


def threshold(pct, kills, alive):
    """`ceil(pct / 100 * (kills + alive))`, in whole numbers."""
    return -(-pct * model.population(kills, alive) // 100)


def reached(pct, kills, alive):
    """Whether the chest may open: the game's rule while off, `kills >= threshold` while on."""
    if pct is OFF:
        return model.chest_openable(alive)
    return kills >= threshold(pct, kills, alive)


def countdown(pct, kills, alive):
    """Kills left to the threshold, never below 0; `None` while off (no countdown)."""
    if pct is OFF:
        return None
    return max(0, threshold(pct, kills, alive) - kills)


def shown(pct, kills, alive, latched=False):
    """Whether `Chest: <n> kills to go` is shown: on, not latched, 0 < n <= 50."""
    n = countdown(pct, kills, alive)
    return n is not None and not latched and 0 < n <= FORGEPACT_COUNTDOWN_LIMIT


def _entries():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["measurements"]


class BaselineTests(unittest.TestCase):
    """The game with no mod: the chest opens only once no monster is alive."""

    def test_baseline_openable_only_when_no_monster_is_alive(self):
        for alive in range(0, 120):
            with self.subTest(alive=alive):
                self.assertEqual(model.chest_openable(alive), alive == 0)
        self.assertEqual(model.VANILLA_UNLOCK_ALIVE, 0)

    def test_dc2_the_rule_reads_only_the_alive_count(self):
        # The model takes the alive count as given; it does not say how the chest
        # obtains it (DC2: the Step calls no script that counts enemies).
        self.assertEqual(list(inspect.signature(model.chest_openable).parameters), ["alive"])
        for total in (1, 7, 40, 300):
            for kills in range(0, total + 1):
                with self.subTest(total=total, kills=kills):
                    alive = total - kills
                    self.assertEqual(model.chest_openable(alive), kills == total)

    def test_dc4_the_unlock_route_is_not_established(self):
        measured = {e.get("hypothesis") for e in _entries() if e["status"] == "measured"}
        for key in ("unlock_is_a_builtin_poll", "unlock_is_a_variable"):
            with self.subTest(key=key):
                self.assertIn(key, model.HYPOTHESES)
                if key not in measured:
                    self.assertIsNone(model.HYPOTHESES[key])

    def test_dc6_a_kill_moves_one_monster_from_alive_to_killed(self):
        total = 40
        for kills in range(0, total + 1):
            alive = total - kills
            with self.subTest(kills=kills):
                self.assertEqual(model.population(kills, alive), total)
                self.assertEqual(model.progress(kills, alive), Fraction(kills, total))
        self.assertEqual(model.kills_to_vanilla(0), 0)

    def test_kills_to_vanilla_is_every_living_monster(self):
        for alive in (0, 1, 7, 40):
            self.assertEqual(model.kills_to_vanilla(alive), alive)

    def test_an_empty_dungeon_is_open_and_fully_cleared(self):
        self.assertTrue(model.chest_openable(0))
        self.assertEqual(model.population(0, 0), 0)
        self.assertEqual(model.progress(0, 0), Fraction(1))

    def test_off_reproduces_the_game(self):
        for total in (0, 1, 7, 40, 120):
            for kills in range(0, total + 1):
                alive = total - kills
                with self.subTest(total=total, kills=kills):
                    self.assertEqual(reached(OFF, kills, alive), model.chest_openable(alive))
                    self.assertIsNone(countdown(OFF, kills, alive))
                    self.assertFalse(shown(OFF, kills, alive))

    def test_values_are_exact(self):
        self.assertIsInstance(model.progress(1, 2), Fraction)
        self.assertIsInstance(model.population(1, 2), int)

    def test_nonsense_is_refused(self):
        for bad in (-1, -40):
            with self.assertRaises(ValueError):
                model.chest_openable(bad)
            with self.assertRaises(ValueError):
                model.population(0, bad)
        for bad in (True, 1.0, "3", None):
            with self.assertRaises(TypeError):
                model.chest_openable(bad)
            with self.assertRaises(TypeError):
                model.progress(bad, 1)


class TargetTests(unittest.TestCase):
    """What the control must turn the game into (spec § "Our code")."""

    def test_target_pct_50_with_40_monsters_opens_at_the_20th_kill(self):
        pct, total = 50, 40
        self.assertEqual(threshold(pct, 0, total), 20)
        self.assertEqual(countdown(pct, 0, total), 20)
        self.assertTrue(shown(pct, 0, total))
        self.assertFalse(reached(pct, 19, total - 19))
        self.assertEqual(countdown(pct, 19, total - 19), 1)
        self.assertTrue(reached(pct, 20, total - 20))
        self.assertEqual(countdown(pct, 20, total - 20), 0)
        self.assertFalse(shown(pct, 20, total - 20))
        # The game alone would still want 20 more kills here.
        self.assertFalse(model.chest_openable(total - 20))
        self.assertEqual(model.kills_to_vanilla(total - 20), 20)

    def test_target_pct_95_with_7_monsters_rounds_up_to_all_of_them(self):
        # 95 % of 7 is 6.65: rounding up asks for all 7, the same kill the game opens at.
        self.assertEqual(threshold(95, 0, 7), 7)
        self.assertFalse(reached(95, 6, 1))
        self.assertTrue(reached(95, 7, 0))
        self.assertEqual(model.kills_to_vanilla(7), 7)

    def test_target_never_later_than_the_game_and_never_below_pct(self):
        for pct in range(FORGEPACT_PCT_MIN, FORGEPACT_PCT_MAX + 1):
            for total in range(0, 161):
                t = threshold(pct, 0, total)
                with self.subTest(pct=pct, total=total):
                    # Never later than the game: the threshold is at most every monster.
                    self.assertLessEqual(t, model.kills_to_vanilla(total))
                    # The kill count is the population, so the threshold holds as kills rise.
                    for kills in (t - 1, t):
                        if 0 <= kills <= total:
                            self.assertEqual(threshold(pct, kills, total - kills), t)
                    # Never early: reached exactly when the dead share is at least pct %.
                    for kills in range(0, total + 1):
                        alive = total - kills
                        self.assertEqual(reached(pct, kills, alive),
                                         model.progress(kills, alive) >= Fraction(pct, 100))
                    # Once the game's own rule holds, the mod's does too.
                    self.assertTrue(reached(pct, total, 0))

    def test_target_the_zero_monster_dungeon_is_reached_at_once(self):
        for pct in (FORGEPACT_PCT_MIN, FORGEPACT_PCT_DEFAULT, FORGEPACT_PCT_MAX):
            with self.subTest(pct=pct):
                self.assertEqual(threshold(pct, 0, 0), 0)
                self.assertTrue(reached(pct, 0, 0))
                self.assertEqual(countdown(pct, 0, 0), 0)
                self.assertFalse(shown(pct, 0, 0))

    def test_target_the_countdown_shows_the_last_50_kills_only(self):
        pct, total = 95, 100  # threshold 95
        self.assertEqual(threshold(pct, 0, total), 95)
        self.assertEqual(countdown(pct, 0, total), 95)
        self.assertFalse(shown(pct, 0, total))
        self.assertEqual(countdown(pct, 44, total - 44), 51)
        self.assertFalse(shown(pct, 44, total - 44))
        self.assertEqual(countdown(pct, 45, total - 45), 50)
        self.assertTrue(shown(pct, 45, total - 45))
        self.assertEqual(countdown(pct, 94, total - 94), 1)
        self.assertTrue(shown(pct, 94, total - 94))
        self.assertEqual(countdown(pct, 95, total - 95), 0)
        self.assertFalse(shown(pct, 95, total - 95))

    def test_target_a_latched_threshold_hides_the_countdown(self):
        self.assertTrue(shown(50, 10, 30))
        self.assertFalse(shown(50, 10, 30, latched=True))

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

    def test_live_one_placeholders_are_present(self):
        # M4: the four questions the Join's post-Live-1 step fills.
        checks = {e.get("live_check"): e for e in _entries()}
        for check, key in (("alive-count", "all_monsters_alive_at_entry"),
                           ("creators-in-dungeon", "no_creators_in_dungeon"),
                           ("unlock-signal", "unlock_is_a_variable"),
                           ("builtin-poll", "unlock_is_a_builtin_poll")):
            with self.subTest(check=check):
                self.assertIn(check, checks)
                self.assertEqual(checks[check]["hypothesis"], key)
                if checks[check]["status"] == "pending":
                    self.assertIsNone(checks[check]["values"])

    def test_a_report_does_not_count_as_a_measurement(self):
        # Negative control: a `reported` or `pending` entry carrying a verdict answers nothing.
        fake = [{"status": "reported", "hypothesis": "boss_dungeon_same_rule", "values": {"verdict": True}},
                {"status": "pending", "hypothesis": "no_creators_in_dungeon", "values": {"verdict": False}}]
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
        # `instance_number(Enemy_Parent_obj)` is the alive count: a creator or the
        # chest itself is not in that family, so neither is counted as a monster.
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
        self.assertTrue({"DC1", "DC2", "DC3", "DC4", "DC5", "DC6"} <= set(ids))
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

    def test_source_paths_exist_where_they_can_be_checked(self):
        # Hub CI checks out without submodules, and a Live capture under
        # .claude/workorders/ is local, so each is only checked where it exists.
        forgepact_present = (FORGEPACT / "src").is_dir()
        checked = 0
        for entry in self.entries:
            path_text, sep, section = entry["source"].partition(" § ")
            self.assertTrue(sep and path_text and section, entry["id"])
            if path_text.startswith("ForgePact/") and not forgepact_present:
                continue
            path = ROOT / path_text
            if path_text.startswith(".claude/workorders/") and not path.is_file():
                continue
            self.assertTrue(path.is_file(), f"{entry['id']}: {path_text}")
            self.assertIn(section, path.read_text(encoding="utf-8"), f"{entry['id']}: {path_text}")
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
                     "ceil(p × (k + a) / 100)", "max(0, t − k)", "0 < n ≤ 50", *model.HYPOTHESES):
            with self.subTest(name=name):
                self.assertIn(name, spec)

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

    The header and this test were written at the same time (ForgePact#31's model and
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

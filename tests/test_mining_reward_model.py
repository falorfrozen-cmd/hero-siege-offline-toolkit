"""What one mining dig pays, modelled from a written spec and checked against
numbers ForgePact already measured (ForgePact issue #36, Mining Ore Extra Rolls).

`hs_game_sdk.mining_reward_model` models the game only: the stacks one dig drops
from the node's ore list, and the chance of a stat-gated bonus find. ForgePact's
levers (Mining Ore Multiplier, the Miner's Helmet's x4, Mining Ore Extra Rolls)
are our own code, so they are written here as transforms of the model's output
and never enter the SDK. `RollsLeverParityTests` pins those transforms to
ForgePact's source, so a ForgePact change fails here instead of drifting.

Each entry of `hs-game-sdk/curated/mining_reward_measurements.json` names the
test that reproduces it (`reproduced_by`). The mechanism, in our own words, is
`docs/models/mining-reward-spec.md`; the workflow is
`docs/agents/static-model-workflow.md`.

Run from the hub root: `py -3 -m unittest tests.test_mining_reward_model -v`.
"""

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
FIXTURE = ROOT / "hs-game-sdk" / "curated" / "mining_reward_measurements.json"
MODEL_FILE = SDK_PY / "hs_game_sdk" / "mining_reward_model.py"
SPEC_DOC = ROOT / "docs" / "models" / "mining-reward-spec.md"
HOOKS_DIR = ROOT / ".claude" / "hooks"
FORGEPACT = ROOT / "ForgePact"
FORGEPACT_MINING = FORGEPACT / "plugin" / "include" / "ForgePact" / "MiningOreMod.hpp"
FORGEPACT_PANEL = FORGEPACT / "src" / "forgepact.py"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import mining_reward_model as model  # noqa: E402


# ---- ForgePact's levers, as transforms (our code, not the game's) -----------

MAX_ROLLS = 10           # plugin `kMaxRolls`
MAX_MULTIPLIER = 10      # plugin `kMaxMultiplier`
HELMET_FACTOR = 4        # the Miner's Helmet replaces the multiplier with x4


def parse_rolls_command(text):
    """`miningrolls N` in the plugin's parser: exactly one whole number in
    1..MAX_ROLLS is accepted; anything else is refused (None) and changes
    nothing, like `miningore`'s parser against `kMaxMultiplier`."""
    parts = str(text).split()
    if len(parts) != 1:
        return None
    try:
        value = int(parts[0])
    except ValueError:
        return None
    return value if 1 <= value <= MAX_ROLLS else None


def panel_rolls(value):
    """The panel's slider value for `drops.mining_ore_rolls`: clamped to
    1..MAX_ROLLS, and 1 for anything unreadable (`drop_multiplier`)."""
    try:
        return max(1, min(MAX_ROLLS, int(float(value))))
    except (TypeError, ValueError, OverflowError):
        return 1


def scale_stack(stack, multiplier, helmet):
    """The quantity lever inside one run: each stack x M, or x4 in place of M
    when the helmet applies. At x1 the params are left exactly as the game made
    them (no `o` is added)."""
    factor = HELMET_FACTOR if helmet else multiplier
    if factor == 1:
        return dict(stack)
    return {**stack, "o": model.stack_quantity(stack) * factor}


def rolled_dig(kinds, rolls=1, multiplier=1, helmet=False, rerun_pays=True):
    """One dig with Mining Ore Extra Rolls at `rolls`.

    The game's completion runs once; if it paid ore, the plugin re-runs it up
    to `rolls - 1` more times on the same node, each run scaled by the quantity
    lever. An extra run that pays nothing ends the loop (`rerun_pays` False is
    Live procedure 1's open question, not a claim). Experience, quests and the
    floating text happen once per dig; the helmet's own dispatch once; every
    run draws each bonus site once; the node ends at hp 0 whatever happened.
    """
    if not 1 <= rolls <= MAX_ROLLS:
        raise ValueError(f"rolls must be 1..{MAX_ROLLS}, got {rolls!r}")
    first = [scale_stack(s, multiplier, helmet) for s in model.dig_stacks(kinds)]
    runs, unpaid = [first], 0
    if first:                                   # no re-run without a first ore reward
        for _ in range(rolls - 1):
            if not rerun_pays:
                unpaid += 1                     # ran, paid nothing: stop
                break
            runs.append([scale_stack(s, multiplier, helmet) for s in model.dig_stacks(kinds)])
    return {
        "runs": runs,
        "extra_runs": len(runs) - 1 + unpaid,
        "extra_runs_unpaid": unpaid,
        "bonus_draws": len(runs) + unpaid,
        "xp_awards": 1,
        "helmet_dispatches": 1 if helmet and first else 0,
        "hp_after": 0,
    }


def measured(entry_id):
    """The `values` of one fixture entry, so a test reads the recorded numbers."""
    entries = json.loads(FIXTURE.read_text(encoding="utf-8"))["measurements"]
    return next(e["values"] for e in entries if e["id"] == entry_id)


MIXED = ["copper", "copper", "gold", "tarethium", "tarethium", "tarethium"]


# ---- the tests --------------------------------------------------------------


class BaselineTests(unittest.TestCase):
    """Vanilla: the game with no ForgePact lever applied (rolls 1, x1)."""

    def test_baseline_one_dig_pays_the_node_list_once(self):
        # MR1's vanilla side: one stack of 6.
        mr1 = measured("MR1")
        single = ["iron"] * mr1["original"]
        self.assertEqual(model.dig_stacks(single), [{"b": 28, "o": 6}])
        dig = rolled_dig(single)
        self.assertEqual(dig["runs"], [[{"b": 28, "o": 6}]])
        self.assertEqual(dig["extra_runs"], 0)
        # One stack per kind, `o` = the count, and no `o` at a count of one.
        stacks = model.dig_stacks(MIXED)
        self.assertEqual(stacks, [{"b": 27, "o": 2}, {"b": 29}, {"b": 32, "o": 3}])
        self.assertEqual(rolled_dig(MIXED)["runs"], [stacks])
        self.assertEqual(model.total_ore(stacks), len(MIXED))
        self.assertEqual(model.stack_quantity({"b": 29}), 1)
        self.assertEqual(model.ORE_ITEM_TYPE, 14)
        self.assertEqual(sorted(model.ORE_BASES.values()), [27, 28, 29, 30, 31, 32])
        # MR1's measured side, through the existing multiplier: one stack of 60,
        # one native drop call.
        x10 = rolled_dig(single, multiplier=mr1["multiplier"])["runs"]
        self.assertEqual(x10, [[{"b": 28, "o": mr1["dispatched"]}]])
        self.assertEqual(len(x10[0]), mr1["native_drop_calls"])
        # An empty list pays nothing.
        self.assertEqual(model.dig_stacks([]), [])

    def test_mr3_a_dig_leaves_the_node_at_hp_0(self):
        mr3 = measured("MR3")
        self.assertEqual((mr3["hp_before"], mr3["hp_after"]), (1, 0))
        for kwargs in ({}, {"rolls": 10}, {"rolls": 10, "rerun_pays": False},
                       {"rolls": 3, "helmet": True}):
            self.assertEqual(rolled_dig(MIXED, **kwargs)["hp_after"], mr3["hp_after"], kwargs)
        self.assertEqual(rolled_dig([], rolls=10)["hp_after"], 0)

    def test_bonus_roll_needs_a_positive_stat(self):
        # A stat of 0 never pays, however many times the dig runs.
        for cap in (0, 1, 99, 1000):
            self.assertEqual(model.bonus_roll_probability(0, cap), 0.0)
        self.assertEqual(model.bonus_roll_probability(-3), 0.0)
        self.assertEqual(model.bonus_roll_probability(float("nan")), 0.0)
        self.assertEqual(model.probability_of_no_bonus(0, 10), 1.0)
        self.assertEqual(model.expected_bonus_hits(0, 10), 0.0)
        # The draw is inclusive: cap 99 has 100 outcomes, and stat 5 hits 5 of them.
        self.assertAlmostEqual(model.bonus_roll_probability(5, 99), 5 / 100)
        self.assertAlmostEqual(model.bonus_roll_probability(0.5, 99), 1 / 100)
        self.assertEqual(model.bonus_roll_probability(100, 99), 1.0)
        self.assertEqual(model.bonus_roll_probability(250, 99), 1.0)
        self.assertEqual(model.bonus_roll_probability(1, 0), 1.0)
        # Negative control: an exclusive draw (99 outcomes) would give 5/99.
        self.assertNotAlmostEqual(model.bonus_roll_probability(5, 99), 5 / 99)

    def test_hypotheses_are_marked_as_such(self):
        self.assertEqual(model.DEFAULT_BONUS_CAP, 99)
        self.assertIn("DEFAULT_BONUS_CAP", model.HYPOTHESES)
        self.assertIn("hypothesis", model.HYPOTHESES["DEFAULT_BONUS_CAP"].lower())

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            model.dig_stacks(["mithril"])
        for cap in (-1, 99.0, True):
            with self.assertRaises(ValueError):
                model.bonus_roll_probability(5, cap)


class TargetTests(unittest.TestCase):
    """ForgePact's levers applied, through the transforms defined above."""

    def test_target_three_rolls_pay_three_sets_of_stacks(self):
        vanilla = model.dig_stacks(MIXED)
        # Rolls 3 with the multiplier at x5: three sets, each stack x5.
        dig = rolled_dig(MIXED, rolls=3, multiplier=5)
        self.assertEqual(len(dig["runs"]), 3)
        self.assertEqual(dig["extra_runs"], 2)
        for run in dig["runs"]:
            self.assertEqual(run, [{"b": 27, "o": 10}, {"b": 29, "o": 5}, {"b": 32, "o": 15}])
        self.assertEqual(sum(model.total_ore(r) for r in dig["runs"]), 3 * 5 * len(MIXED))
        # Rolls alone repeat the list; they never change which kinds drop.
        plain = rolled_dig(MIXED, rolls=3)
        self.assertEqual(plain["runs"], [vanilla] * 3)
        # Experience, quests and the floating text still happen once.
        self.assertEqual(dig["xp_awards"], 1)
        # MR2: the helmet's x4 replaces the multiplier in every run, and its own
        # dispatch runs once per dig.
        for original, scaled in measured("MR2")["pairs"]:
            helmet = rolled_dig(["jade"] * original, rolls=3, multiplier=5, helmet=True)
            self.assertEqual(helmet["runs"], [[{"b": 31, "o": scaled}]] * 3)
            self.assertEqual(helmet["helmet_dispatches"], 1)
        # Negative control: rolls 1 is one set.
        self.assertEqual(len(rolled_dig(MIXED, rolls=1, multiplier=5)["runs"]), 1)

    def test_rolls_above_the_plugin_cap_are_refused(self):
        for n in range(1, MAX_ROLLS + 1):
            self.assertEqual(parse_rolls_command(str(n)), n)
        for text in ("0", "11", "999", "-1", "3 4", "3.5", "", "x"):
            self.assertIsNone(parse_rolls_command(text), text)
        # The panel clamps to the same bounds.
        self.assertEqual(panel_rolls(999), MAX_ROLLS)
        self.assertEqual(panel_rolls(0), 1)
        self.assertEqual(panel_rolls("x"), 1)
        self.assertEqual(panel_rolls(3), 3)
        # And the transform cannot be asked for more than the cap.
        with self.assertRaises(ValueError):
            rolled_dig(MIXED, rolls=MAX_ROLLS + 1)
        self.assertEqual(len(rolled_dig(MIXED, rolls=MAX_ROLLS)["runs"]), MAX_ROLLS)

    def test_bonus_finds_scale_with_the_roll_count(self):
        p = model.bonus_roll_probability(5)
        for rolls in (1, 3, 10):
            draws = rolled_dig(MIXED, rolls=rolls)["bonus_draws"]
            self.assertEqual(draws, rolls)
            self.assertAlmostEqual(model.expected_bonus_hits(5, draws), rolls * p)
            self.assertAlmostEqual(model.probability_of_no_bonus(5, draws), (1 - p) ** rolls)
            # A character without the stat sees nothing, at any roll count.
            self.assertEqual(model.expected_bonus_hits(0, draws), 0.0)

    def test_no_rerun_without_a_first_ore_reward(self):
        # A step call that paid no ore starts no extra run.
        empty = rolled_dig([], rolls=10)
        self.assertEqual((empty["runs"], empty["extra_runs"], empty["bonus_draws"]), ([[]], 0, 1))
        # An extra run that pays nothing ends the loop at once.
        unpaid = rolled_dig(MIXED, rolls=10, rerun_pays=False)
        self.assertEqual(len(unpaid["runs"]), 1)
        self.assertEqual((unpaid["extra_runs"], unpaid["extra_runs_unpaid"]), (1, 1))
        self.assertEqual(unpaid["hp_after"], 0)


class FixtureShapeTests(unittest.TestCase):
    """`hs-game-sdk/curated/mining_reward_measurements.json` stays checkable."""

    REQUIRED = ("id", "kind", "status", "date", "source", "scripts", "what", "values", "model")

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.entries = cls.data["measurements"]

    def test_every_entry_has_the_required_fields(self):
        self.assertIn("$schema_note", self.data)
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({"MR1", "MR2", "MR3"} <= set(ids))
        for entry in self.entries:
            for field in self.REQUIRED:
                self.assertIn(field, entry, entry.get("id"))
            self.assertRegex(entry["id"], r"^MR\d+$")
            self.assertIn(entry["kind"], ("baseline", "target", "our_code"), entry["id"])
            self.assertIn(entry["status"], ("measured", "qualitative", "approximate", "our_code"),
                          entry["id"])
            self.assertRegex(entry["date"], r"^\d{4}-\d{2}-\d{2}$", entry["id"])
            self.assertEqual(("reproduced_by" in entry) + ("not_reproduced" in entry), 1,
                             f"{entry['id']} needs exactly one of reproduced_by / not_reproduced")

    def test_every_named_test_exists_in_this_module(self):
        for entry in self.entries:
            if "reproduced_by" not in entry:
                continue
            dotted = entry["reproduced_by"]
            prefix = "tests.test_mining_reward_model."
            self.assertTrue(dotted.startswith(prefix), dotted)
            class_name, method = dotted[len(prefix):].split(".")
            cls = globals().get(class_name)
            self.assertIsNotNone(cls, dotted)
            self.assertTrue(callable(getattr(cls, method, None)), dotted)
            self.assertTrue(method.startswith("test_"), dotted)

    def test_every_script_is_bound_in_the_sdk(self):
        from hs_game_sdk.scripts import GameScript
        for entry in self.entries:
            self.assertTrue(entry["scripts"], entry["id"])
            for name in entry["scripts"]:
                self.assertIn(name, GameScript.__members__, f"{entry['id']}: {name}")

    def test_source_paths_exist_where_they_can_be_checked(self):
        # Hub CI checks out without submodules, so a ForgePact path is only
        # checked where ForgePact is initialised.
        forgepact_present = (FORGEPACT / "docs").is_dir()
        checked = 0
        for entry in self.entries:
            self.assertTrue(entry["source"], entry["id"])
            for source in entry["source"]:
                self.assertTrue(("path" in source) != ("commit" in source), (entry["id"], source))
                if "commit" in source:
                    self.assertRegex(source["commit"], r"^[0-9a-f]{7,40}$", entry["id"])
                    continue
                if source["path"].startswith("ForgePact/") and not forgepact_present:
                    continue
                path = ROOT / source["path"]
                self.assertTrue(path.is_file(), f"{entry['id']}: {source['path']}")
                if "section" in source:
                    self.assertIn(source["section"], path.read_text(encoding="utf-8"),
                                  f"{entry['id']}: {source['path']}")
                checked += 1
        if forgepact_present:
            self.assertGreater(checked, 0)


class NoDecompilerOutputTests(unittest.TestCase):
    """The model was built clean-room; nothing it ships may carry listing text."""

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
        self.assertFalse(self._matches("the dig counts the list's entries per kind"))

    def test_no_signature_in_the_new_files(self):
        for path in self.FILES:
            self.assertTrue(path.is_file(), path)
            self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [], path)

    def test_no_local_decompiler_paths_in_the_new_files(self):
        forbidden = ("hs-" + "decomp", "ghidra" + "_projects")
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                self.assertNotIn(word, text, path)
        # Positive control: the same check does see the words when they are there.
        self.assertIn(forbidden[0], "C:/tools/" + forbidden[0] + "/x")


def _load_panel():
    """ForgePact's `src/forgepact.py`, loaded in-process with no bytecode written."""
    spec = importlib.util.spec_from_file_location("_forgepact_panel_mining_rolls", FORGEPACT_PANEL)
    panel = importlib.util.module_from_spec(spec)
    saved_path, saved_bytecode = list(sys.path), sys.dont_write_bytecode
    sys.path.insert(0, str(FORGEPACT_PANEL.parent))   # its sibling imports
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(panel)
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bytecode
    return panel


@unittest.skipUnless(FORGEPACT_MINING.is_file() and FORGEPACT_PANEL.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "so there is no lever source to compare the test transforms with")
class RollsLeverParityTests(unittest.TestCase):
    """The transforms at the top of this file are ForgePact's levers; pin them
    to ForgePact's source so a ForgePact change fails here instead of drifting."""

    @classmethod
    def setUpClass(cls):
        cls.header = FORGEPACT_MINING.read_text(encoding="utf-8", errors="replace")

    def test_max_rolls_matches_the_plugin_header(self):
        rolls = re.search(r"\bkMaxRolls\s*=\s*(\d+)\s*;", self.header)
        self.assertIsNotNone(rolls, "MiningOreMod.hpp declares no kMaxRolls")
        self.assertEqual(int(rolls.group(1)), MAX_ROLLS)
        # The parser refuses above the cap (not only the panel).
        self.assertRegex(self.header, r">\s*kMaxRolls\b|\bkMaxRolls\s*<")
        multiplier = re.search(r"\bkMaxMultiplier\s*=\s*(\d+)\s*;", self.header)
        self.assertIsNotNone(multiplier)
        self.assertEqual(int(multiplier.group(1)), MAX_MULTIPLIER)

    def test_panel_clamps_rolls_to_the_same_bounds(self):
        panel = _load_panel()
        for value in (0, 1, 3, 10, 11, 999, -5, "x", None):
            self.assertEqual(panel.drop_multiplier("mining_ore_rolls", value), panel_rolls(value),
                             value)
        self.assertEqual(panel.drop_command("mining_ore_rolls", 5), "miningrolls 5")
        self.assertEqual(panel.DEFAULTS["drops"]["mining_ore_rolls"], 1)


if __name__ == "__main__":
    unittest.main()

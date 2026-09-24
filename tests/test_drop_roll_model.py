"""The two-stage drop roll, modelled from a written spec and checked against
numbers ForgePact already measured (issue #162's pilot).

`hs_game_sdk.drop_roll_model` models the game only: the `LoadDrops` gate, the
per-item `droprate.base` roll, and the dungeon-key and relic variants.
ForgePact's levers (`droprate group`, `dungeonkey`, the relic pre-roll) are our
own code, so they are written here as input transforms and never enter the
SDK. `LeverParityTests` pins these transforms to ForgePact's source, so a
ForgePact change fails here instead of letting the two drift apart.

Each entry of `hs-game-sdk/curated/drop_roll_measurements.json` names the test
that reproduces it (`reproduced_by`), or says why it cannot be reproduced
(`not_reproduced`). The mechanism, in our own words, is
`docs/models/drop-roll-spec.md`; how this workflow is meant to be used is
`docs/agents/static-model-workflow.md`.

Run from the hub root: `py -3 -m unittest tests.test_drop_roll_model -v`.
"""

import importlib.util
import inspect
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_PY = ROOT / "hs-game-sdk" / "python"
FIXTURE = ROOT / "hs-game-sdk" / "curated" / "drop_roll_measurements.json"
MODEL_FILE = SDK_PY / "hs_game_sdk" / "drop_roll_model.py"
SPEC_DOC = ROOT / "docs" / "models" / "drop-roll-spec.md"
WORKFLOW_DOC = ROOT / "docs" / "agents" / "static-model-workflow.md"
HOOKS_DIR = ROOT / ".claude" / "hooks"
FORGEPACT = ROOT / "ForgePact"
FORGEPACT_PLUGIN = FORGEPACT / "plugin" / "ModuleMain.cpp"
FORGEPACT_PANEL = FORGEPACT / "src" / "forgepact.py"

sys.path.insert(0, str(SDK_PY))
from hs_game_sdk import drop_roll_model as model  # noqa: E402

# The inner scale `s` is not established (spec "Not established"); a claim
# about the inner roll has to hold across the plausible range, not at one guess.
# 0.7 is chances[13]'s native factor, applied in either direction.
INNER_SCALES = (0.7, 1.0, 1 / 0.7)


# ---- ForgePact's levers, as input transforms (our code, not the game's) ----

KEY_TYPE = 11            # LoadDrops type whose vanilla call the dungeonkey hook follows
DUNGEON_KEY_TYPE = 12
RELIC_TYPE = 41
# Per-death pre-roll scale for a type (plugin `g_DkTipOlcek`); a type without an
# entry is 1.0, which means "no pre-roll".
PREROLL_SCALE = {RELIC_TYPE: 0.00025}


class DropRateGroup:
    """`droprate group <family> m`: remember each item's vanilla base on first
    touch, once per process, then write max(1, vanilla / m), or the vanilla
    value itself when m <= 1. Repeating the command never compounds."""

    def __init__(self):
        self.vanilla = {}

    def apply(self, item, current_base, multiplier):
        if multiplier <= 0:
            multiplier = 1.0                    # 0 or negative means vanilla
        vanilla = self.vanilla.setdefault(item, current_base)
        if vanilla <= 0:
            return current_base                 # the plugin skips such an item
        new = vanilla if multiplier <= 1 else vanilla / multiplier
        return max(1.0, new)


def droprate_set(_current_base, absolute):
    """`droprate set <i> <value>`: writes the value as it is."""
    return absolute


def gate_multiplier(family, multiplier):
    """The multiplier `build_key_cmds` sends with `dungeonkey add` (1.3.13 on):
    the slider itself for relic, 1 for every other family."""
    return multiplier if family == "relic" else 1


def preroll_probability(scale, multiplier, exponent=2):
    """The plugin's own per-death die before an extra roll. Quadratic since
    ForgePact cbac161 (exponent 2), linear in v1.2.2 (exponent 1); clamped at 1.
    A scale of 1 or more means there is no pre-roll at all."""
    if scale >= 1.0:
        return 1.0
    return min(1.0, scale * multiplier ** exponent)


def extra_roll_gate_probability(chances, drop_type, gate_mult, *, preroll_scale=None,
                                preroll_exponent=2, die_outcomes=model.DEFAULT_DIE_OUTCOMES):
    """`dungeonkey on` + `chance auto`, after the vanilla type-11 call: the
    probability that the extra roll for `drop_type` passes the game's gate on
    one death. The monster's own listing of the type is left alone. The
    pre-roll defaults to today's (`PREROLL_SCALE`, quadratic); v1.2.2's linear
    0.0005 is `preroll_scale=0.0005, preroll_exponent=1`."""
    if chances.get(drop_type, 0) > 0:
        return 0.0
    if preroll_scale is None:
        preroll_scale = PREROLL_SCALE.get(drop_type, 1.0)
    pre = preroll_probability(preroll_scale, gate_mult, preroll_exponent)
    return pre * model.gate_probability(chances.get(KEY_TYPE, 0) * gate_mult, die_outcomes)


# ---- the tests --------------------------------------------------------------


class BaselineTests(unittest.TestCase):
    """Vanilla: the game with no ForgePact lever applied."""

    def test_m1_a_zero_chance_never_opens_the_gate(self):
        # M1: chances[12] was 0 in 200 of 200 calls on key-dropping monsters,
        # and type 12 never appeared.
        for outcomes in (1, 10, 100, 101, 1000):
            self.assertEqual(model.gate_probability(0, outcomes), 0.0)
        self.assertEqual(model.gate_probability(-5), 0.0)
        self.assertEqual(model.gate_probability(float("nan")), 0.0)
        self.assertEqual(model.dungeon_key_probability(0, [1500] * 26), 0.0)
        # Negative control: the same monster's type-11 slot does open.
        self.assertGreater(model.gate_probability(5), 0.0)

    def test_integer_chance_c_passes_c_times_in_n(self):
        for outcomes in (50, 100, 101):
            for chance in range(1, outcomes + 1):
                self.assertAlmostEqual(model.gate_probability(chance, outcomes), chance / outcomes)
        # 100 is a certain drop at the default outcome count, and nothing
        # above it can be more certain.
        self.assertEqual(model.gate_probability(100), 1.0)
        self.assertEqual(model.gate_probability(250), 1.0)

    def test_m3_vanilla_key_base_gives_no_key_in_95_calls(self):
        # M3: 95 DropDungeonKeys calls at base 1500, no key seen.
        for s in INNER_SCALES:
            p = model.dungeon_key_call_probability([1500] * 26, s)
            self.assertGreaterEqual(model.probability_of_no_hit(p, 95), 0.5, s)
        # Negative control: at base 1 the same calls would all hit.
        self.assertEqual(model.probability_of_no_hit(model.inner_probability(1), 95), 0.0)

    def test_the_relic_roll_has_no_base_parameter(self):
        # M7 (a measurement, the only source): no 1-in-base roll follows the
        # relic gate, so the model's relic function cannot even be given a base.
        # Whether the base weights the pick between relics is not established.
        params = inspect.signature(model.relic_roll_probability).parameters
        self.assertNotIn("base", params)
        self.assertEqual(model.relic_roll_probability(0), 0.0)

    def test_hypotheses_are_marked_as_such(self):
        # The unknowns are parameters whose defaults are labelled hypotheses,
        # never silent constants.
        self.assertEqual(model.DEFAULT_DIE_OUTCOMES, 100)
        self.assertEqual(model.DEFAULT_INNER_SCALE, 1.0)
        for name in ("DEFAULT_DIE_OUTCOMES", "DEFAULT_INNER_SCALE"):
            self.assertIn(name, model.HYPOTHESES)
            self.assertIn("hypothesis", model.HYPOTHESES[name].lower())

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            model.gate_probability(5, 0)
        with self.assertRaises(ValueError):
            model.inner_probability(0)
        with self.assertRaises(ValueError):
            model.dungeon_key_call_probability([])


class TargetTests(unittest.TestCase):
    """ForgePact's levers applied, through the transforms defined above."""

    def test_m2_opened_gate_passes_at_the_monsters_key_chance(self):
        # M2: 1233 extra type-12 rolls, 95 passed; chances[11] was 5 to 9.
        trials, passes = 1233, 95
        low = extra_roll_gate_probability({KEY_TYPE: 5}, DUNGEON_KEY_TYPE, gate_multiplier("dungeon", 5))
        high = extra_roll_gate_probability({KEY_TYPE: 9}, DUNGEON_KEY_TYPE, gate_multiplier("dungeon", 5))
        self.assertAlmostEqual(low, 0.05)
        self.assertAlmostEqual(high, 0.09)
        self.assertTrue(model.observation_within(passes, trials, low, high))
        # A forced gate would have passed every roll.
        self.assertFalse(model.observation_within(passes, trials, 1.0, 1.0))
        consistent = model.consistent_die_outcomes(passes, trials, 5, 9, range(2, 2001))
        self.assertIn(100, consistent)
        # ...and the observation does constrain N: neither extreme fits.
        self.assertNotIn(10, consistent)
        self.assertNotIn(1000, consistent)
        # The hook leaves a monster that lists type 12 itself alone.
        self.assertEqual(extra_roll_gate_probability({KEY_TYPE: 5, DUNGEON_KEY_TYPE: 40},
                                                     DUNGEON_KEY_TYPE, 1), 0.0)

    def test_m4_base_50_gives_about_two_keys_in_95_calls(self):
        base = droprate_set(1500, 50)
        for s in INNER_SCALES:
            expected = model.expected_hits(model.dungeon_key_call_probability([base] * 26, s), 95)
            self.assertGreaterEqual(expected, 1.0, s)
            self.assertLessEqual(expected, 4.0, s)

    def test_m5_base_3_makes_keys_visible(self):
        base = droprate_set(1500, 3)
        for s in INNER_SCALES:
            expected = model.expected_hits(model.dungeon_key_call_probability([base] * 26, s), 95)
            self.assertGreaterEqual(expected, 10.0, s)

    def test_m6_scaling_a_chance_below_one_changes_nothing(self):
        # Every chance in (0, 1] passes only on a draw of zero.
        for chance in (1.0, 0.5, 0.05, 0.01, 0.001, 1e-9):
            self.assertEqual(model.gate_probability(chance), model.gate_probability(1))
        # v1.2.1 wrote chances[11] x slider x scale into the relic slot. On the
        # measured monsters (chances[11] 5 to 9, slider x2) the two scales give
        # the same gate: no reduction at all.
        for c11 in range(5, 10):
            coarse = model.gate_probability(c11 * 2 * 0.05)
            fine = model.gate_probability(c11 * 2 * 0.001)
            self.assertEqual(coarse, fine, c11)
        # Across any monster up to chances[11] = 20 the predicted reduction is
        # at most 2x, where the scale change intended 50x.
        for c11 in range(1, 21):
            for slider in (1, 2):
                ratio = (model.gate_probability(c11 * slider * 0.05)
                         / model.gate_probability(c11 * slider * 0.001))
                self.assertLessEqual(ratio, 2.0, (c11, slider))

    def test_m7_relic_base_lever_is_a_no_op(self):
        lever = DropRateGroup()
        before = 25_000_000
        after = lever.apply(("relic", 0), before, 100)
        self.assertEqual(after, 250_000)                 # the lever does write
        # ...but the relic roll cannot be given a base, so the write changes
        # nothing: the relic probability is the gate's, whatever the base.
        self.assertNotIn("base", inspect.signature(model.relic_roll_probability).parameters)
        self.assertEqual(model.relic_roll_probability(5), model.gate_probability(5))
        # Positive control: the same write moves a base-driven family.
        self.assertGreater(model.dungeon_key_probability(5, [after]),
                           model.dungeon_key_probability(5, [before]))

    def test_m8_quadratic_and_linear_pre_roll_agree_at_x2(self):
        # M8's shares are not reproducible (see the fixture); only the identity is.
        quadratic = preroll_probability(0.00025, 2, exponent=2)
        linear = preroll_probability(0.0005, 2, exponent=1)
        self.assertAlmostEqual(quadratic, 0.001)
        self.assertAlmostEqual(linear, 0.001)
        chances = {KEY_TYPE: 7}
        self.assertAlmostEqual(
            extra_roll_gate_probability(chances, RELIC_TYPE, 2),
            extra_roll_gate_probability(chances, RELIC_TYPE, 2,
                                        preroll_scale=0.0005, preroll_exponent=1))
        # Negative control: at x100 the two curves part (linear stays at 0.05).
        self.assertNotAlmostEqual(preroll_probability(0.00025, 100),
                                  preroll_probability(0.0005, 100, exponent=1))
        # x100 clamps the pre-roll at 1: the relic slot is tried on every death.
        self.assertEqual(preroll_probability(0.00025, 100), 1.0)
        # Families without a pre-roll scale are never thinned.
        self.assertEqual(preroll_probability(PREROLL_SCALE.get(DUNGEON_KEY_TYPE, 1.0), 50), 1.0)

    def test_m9_multiplier_on_gate_and_roll_squares_the_lever(self):
        c11, base = 5, 1500

        def rate(gate_mult, roll_mult):
            chances = {KEY_TYPE: c11}
            gate = extra_roll_gate_probability(chances, DUNGEON_KEY_TYPE, gate_mult)
            lever = DropRateGroup()
            return gate * model.inner_probability(lever.apply("key", base, roll_mult))

        reference = rate(1, 1)
        for m in (2, 5, 10):
            # 1.3.10 to 1.3.12: the slider on both stages.
            self.assertAlmostEqual(rate(m, m) / reference, m * m, places=9)
            # 1.3.13 on: the gate stays at the monster's own key chance.
            self.assertAlmostEqual(rate(gate_multiplier("dungeon", m), m) / reference, m, places=9)

    def test_m10_droprate_group_divides_the_vanilla_base_without_compounding(self):
        lever = DropRateGroup()
        first = lever.apply("key", 1500, 5)
        self.assertEqual(first, 300)
        self.assertEqual(lever.apply("key", first, 5), 300)      # never compounds
        self.assertEqual(lever.apply("key", 300, 1), 1500)       # x1 restores vanilla
        self.assertEqual(lever.apply("key", 1500, 5000), 1)      # floors at 1
        self.assertEqual(lever.apply("key", 1500, 0), 1500)      # 0 means vanilla
        self.assertAlmostEqual(model.inner_probability(first) / model.inner_probability(1500), 5.0)


class FixtureShapeTests(unittest.TestCase):
    """`hs-game-sdk/curated/drop_roll_measurements.json` stays checkable."""

    REQUIRED = ("id", "kind", "status", "date", "source", "scripts", "what", "model")

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.entries = cls.data["measurements"]

    def test_every_entry_has_the_required_fields(self):
        self.assertIn("$schema_note", self.data)
        ids = [e["id"] for e in self.entries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({f"M{i}" for i in range(1, 11)} <= set(ids))
        for entry in self.entries:
            for field in self.REQUIRED:
                self.assertIn(field, entry, entry.get("id"))
            self.assertIn(entry["kind"], ("baseline", "target", "our_code"), entry["id"])
            self.assertIn(entry["status"], ("measured", "qualitative", "approximate", "our_code"),
                          entry["id"])
            self.assertRegex(entry["date"], r"^\d{4}-\d{2}-\d{2}$", entry["id"])
            self.assertEqual(("reproduced_by" in entry) + ("not_reproduced" in entry), 1,
                             f"{entry['id']} needs exactly one of reproduced_by / not_reproduced")

    def test_every_named_test_exists_in_this_module(self):
        for entry in self.entries:
            for field in ("reproduced_by", "identity_checked_by"):
                if field not in entry:
                    continue
                dotted = entry[field]
                prefix = "tests.test_drop_roll_model."
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

    def test_commit_sources_are_abbreviated_hashes(self):
        for entry in self.entries:
            self.assertTrue(entry["source"], entry["id"])
            for source in entry["source"]:
                self.assertTrue(("path" in source) != ("commit" in source), (entry["id"], source))
                if "commit" in source:
                    self.assertRegex(source["commit"], r"^[0-9a-f]{7,40}$", entry["id"])
                    self.assertEqual(source.get("repo"), "ForgePact", entry["id"])

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
        if forgepact_present:
            self.assertGreater(checked, 0)


class NoDecompilerOutputTests(unittest.TestCase):
    """The model was built clean-room; nothing it ships may carry listing text."""

    FILES = (MODEL_FILE, FIXTURE, SPEC_DOC, WORKFLOW_DOC, Path(__file__).resolve())

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
        self.assertFalse(self._matches("the gate compares a whole-number draw with the chance"))

    def test_no_signature_in_the_pilot_files(self):
        for path in self.FILES:
            self.assertTrue(path.is_file(), path)
            self.assertEqual(self._matches(path.read_text(encoding="utf-8")), [], path)

    def test_no_local_decompiler_paths_in_the_pilot_files(self):
        forbidden = ("hs-" + "decomp", "ghidra" + "_projects")
        for path in self.FILES:
            text = path.read_text(encoding="utf-8")
            for word in forbidden:
                self.assertNotIn(word, text, path)


def _function_body(source, signature):
    """The brace-balanced body that follows `signature` in C++ source."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace:i + 1]
    raise ValueError(f"unbalanced body after {signature!r}")


@unittest.skipUnless(FORGEPACT_PLUGIN.is_file(),
                     "ForgePact is not checked out (hub CI checks out without submodules), "
                     "so there is no lever source to compare the test transforms with")
class LeverParityTests(unittest.TestCase):
    """The transforms at the top of this file are ForgePact's levers; pin them
    to ForgePact's source so a ForgePact change fails here instead of drifting."""

    @classmethod
    def setUpClass(cls):
        cls.plugin = FORGEPACT_PLUGIN.read_text(encoding="utf-8", errors="replace")

    def test_relic_preroll_scale_and_curve(self):
        table = re.search(r"g_DkTipOlcek\s*=\s*\{(.*?)\};", self.plugin, re.S)
        self.assertIsNotNone(table)
        entries = {int(t): float(v) for t, v in
                   re.findall(r"\{\s*(\d+)\s*,\s*([0-9.eE+-]+)\s*\}", table.group(1))}
        self.assertEqual(entries, PREROLL_SCALE)
        hook = _function_body(self.plugin, "static RValue& Hook_LoadDrops(")
        # Quadratic in the type's own multiplier, clamped at 1.
        self.assertRegex(hook, r"olcek\s*\*\s*kendiCarpan\s*\*\s*kendiCarpan")
        self.assertRegex(hook, r"if\s*\(\s*olasilik\s*>\s*1\.0\s*\)\s*olasilik\s*=\s*1\.0")
        # The extra roll's chance is the monster's own chances[11] times that multiplier...
        self.assertRegex(hook, r"taban\s*\*\s*kendiCarpan")
        self.assertRegex(hook, r"RValue\(\s*11\.0\s*\)")
        # ...and a type the monster already lists is left alone.
        self.assertRegex(hook, r"mevcut\.ToDouble\(\)\s*>\s*0\.0\s*\)\s*\{[^}]*continue")

    def test_divide_floors_at_one_and_never_compounds(self):
        vanilla = _function_body(self.plugin, "static double VanilyaBase(")
        # First touch stores the value; every later call returns the stored one.
        self.assertIn("g_DropRateVanilya.find(anahtar)", vanilla)
        self.assertIn("return it->second;", vanilla)
        group = _function_body(self.plugin, "static int DropGrupUygula(")
        relic = self.plugin[self.plugin.index('else if (grup == "relic")'):]
        relic = relic[:relic.index('else if (grup == "dungeon")')]
        generic = _function_body(self.plugin, "static void DropRateCmd(")
        generic = generic[generic.index("// v artik CARPAN"):]
        for name, body, mult in (("DropGrupUygula", group, "carpan"),
                                 ("relic branch", relic, "v"),
                                 ("generic branch", generic, "v")):
            # The division always starts from the stored vanilla value.
            self.assertRegex(body, r"double vanilya = VanilyaBase\(", name)
            self.assertRegex(
                body,
                r"\(\s*%s\s*<=\s*1\.0\s*\)\s*\?\s*vanilya\s*:\s*\(\s*vanilya\s*/\s*%s\s*\)" % (mult, mult),
                name)
            self.assertRegex(body, r"if\s*\(\s*yeni\s*<\s*1\.0\s*\)\s*yeni\s*=\s*1\.0", name)
        # A zero or negative multiplier means vanilla.
        self.assertRegex(_function_body(self.plugin, "static void DropRateCmd("),
                         r"if\s*\(\s*v\s*<=\s*0\.0\s*\)\s*v\s*=\s*1\.0")

    def test_gate_multiplier_is_the_slider_only_for_relic(self):
        spec = importlib.util.spec_from_file_location("_forgepact_panel_drop_roll", FORGEPACT_PANEL)
        panel = importlib.util.module_from_spec(spec)
        saved_path, saved_bytecode = list(sys.path), sys.dont_write_bytecode
        sys.path.insert(0, str(FORGEPACT_PANEL.parent))   # its sibling imports
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(panel)
        finally:
            sys.path[:] = saved_path
            sys.dont_write_bytecode = saved_bytecode
        gated = [(family, drop_type) for family, _label, drop_type in panel.KEYS if drop_type]
        self.assertIn(("relic", RELIC_TYPE), gated)
        self.assertIn(("dungeon", DUNGEON_KEY_TYPE), gated)
        for m in (2, 7):
            commands = panel.build_key_cmds({family: m for family, _ in gated})
            for family, drop_type in gated:
                self.assertIn(f"dungeonkey add {drop_type} {gate_multiplier(family, m)}", commands)
            self.assertIn("dungeonkey chance auto", commands)


if __name__ == "__main__":
    unittest.main()

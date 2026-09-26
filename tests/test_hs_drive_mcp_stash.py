"""`tools/hs_drive_mcp/stash.py` -- the stash and bag tools.

`ipc.send` and `input.inject` are replaced by scripted doubles and `_sleep`
by a no-op; nothing here starts a game, sends a key or reads the real
`%LOCALAPPDATA%`. The listings the doubles hand back are live 2's replies,
byte for byte (`tests/hs_drive_mcp_stashlayout_fixtures.py`), or built from
them in the format the player build prints after Step 5: several listings in
one frame (one send carrying several `menulayout <Obj>` lines, the shape
`MULTI_LISTING_REPLY` shows live), a window row whose `stashTabSelected`
value is changed, and a `tabSelected=` field after it (the field Step 5 added;
`derived` below does exactly that and nothing else). The verbs' own lines
follow the shapes `ForgePact/tests/test_stash_bag_layout_contract.py` pins.
The `Player_obj` and `Town_Stash_obj` rows are copied verbatim from the same
session's `out.txt` (the warp of P2-2: 912,822 before, 884,628 after).

The baseline and target pairs (`AGENTS.md` § "Mod Development Workflow"):
for each tool, a game whose verb reply and listings never change is refused
with the tool's own "did not happen" token after exactly the sends its
contract allows, and one whose listings change as the action would is `ok`.
"""
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import layout, results, saves, stash  # noqa: E402
from tests import hs_drive_mcp_stashlayout_fixtures as fx  # noqa: E402
from tests.hs_drive_mcp_lease_fixtures import isolate_lease_dir  # noqa: E402


def setUpModule():
    isolate_lease_dir()


RUNNING = ("running", "1 hero_siege.exe process(es) are live: [4242].")
NOT_RUNNING = ("not_running", "the process snapshot returned 0 rows.")
PIDS = [4242]

HEADER = ("menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 "
          "view=244.0,268.0,1280.0,720.0")
TOWN_STASH_ROW = ("  obj=Town_Stash_obj id=228465 gui=884.0,580.0 win=663,458 "
                  "bbox=856.0,565.0,913.0,598.0 visible=1 sprite=Stash_Act_01_spr text=")
PLAYER_BEFORE_ROW = ("  obj=Player_obj id=261723 gui=912.0,822.0 win=684,649 "
                     "bbox=900.0,816.0,924.0,840.0 visible=1 sprite=none name=Sorak text=")
PLAYER_AFTER_ROW = ("  obj=Player_obj id=261723 gui=884.0,628.0 win=663,496 "
                    "bbox=872.0,622.0,896.0,646.0 visible=1 sprite=none name=Sorak text=")
MATERIAL = "0-0-209564349884-14"   # live 2's K_M
NEW_KEY = "0-0-212527295000-14"

OPEN_READ = "menulayout UI_Stash_obj\nmenulayout Player_obj\nmenulayout Town_Stash_obj"
TAB_READ = "menulayout UI_Stash_obj\nmenulayout UI_Button_Stash_Tab_obj"
BAG_READ = "menulayout UI_Stash_obj\nmenulayout UI_Button_Inventory_Tab_Small_obj"
WINDOW_READ = "menulayout UI_Stash_obj"
PLAYER_READ = "menulayout Player_obj"
GRID_READ = "menulayout UI_Inventory_Grid_obj"
WARP = "playerwarp 884.0 628.0"
GIVE = f"giveitem bag {MATERIAL} 1"


def frame(*lines):
    return "---- running command file ----\r\n" + "".join(l + "\r\n" for l in lines) + "---- done ----\r\n"


def inner(reply):
    """The lines between a fixture's framing."""
    return reply.split("\r\n")[1:-2]


def listing(*rows):
    return [HEADER, *rows, f"menulayout: listed={len(rows)} absent=none capped=0"]


def combined(*replies):
    """Several fixtures' listings in one frame, as one send of several
    `menulayout <Obj>` lines answers."""
    return frame(*[line for r in replies for line in inner(r)])


def derived(stash_tab=None, tab=None):
    """`STASH_WINDOW_REPLY` with its `stashTabSelected` value changed, and a
    `tabSelected=` field after it (the Step 5 build prints it there)."""
    text = fx.STASH_WINDOW_REPLY
    if stash_tab is not None:
        text = text.replace("stashTabSelected=0", f"stashTabSelected={stash_tab}")
    if tab is not None:
        text = text.replace(" text=\r\n", f" tabSelected={tab} text=\r\n", 1)
    return text


NO_WINDOW = frame(*listing())


class ScriptedIpc:
    """`ipc.send`, replaced. `script` maps the joined lines of one send to a
    list of framed replies, consumed one at a time; the last one repeats."""

    def __init__(self, script):
        self.script = {key: list(replies) for key, replies in script.items()}
        self.calls: list[str] = []

    def send(self, lines, *, tool="hs_command", **kwargs):
        key = "\n".join(lines)
        self.calls.append(key)
        if kwargs.get("lease_checked") is not True:
            raise AssertionError(f"{key!r} was sent without lease_checked=True")
        if key not in self.script:
            raise AssertionError(f"unscripted send {key!r}")
        queue = self.script[key]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return results.ok(tool, sent=list(lines), reply=reply, reply_lines=reply.splitlines(),
                          consumed=True, queued=False)


class ScriptedInject:
    def __init__(self, undelivered=False):
        self.calls: list[dict] = []
        self.undelivered = undelivered

    def __call__(self, actions, *, route="send_input", force_focus=False, tool="hs_input", **kwargs):
        self.calls.append({"actions": actions, "route": route, "force_focus": force_focus,
                           "lease_checked": kwargs.get("lease_checked")})
        if self.undelivered:
            return results.ok(tool, records_sent=2, records_rejected=2, complete=False,
                              detail="SendInput rejected 2 of 2 record(s).")
        return results.ok(tool, records_sent=2, records_rejected=0, complete=True,
                          focus_via="already_foreground")


class StashBase(unittest.TestCase):
    def setUp(self):
        self.sleeps: list[float] = []
        self.enterContext(patch.object(stash, "_sleep", self.sleeps.append))
        temp = tempfile.TemporaryDirectory(prefix="hs-drive-stash-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        live = root / "hs2saves"
        live.mkdir()
        (live / "herosiege14.hss").write_bytes(b"character")
        (live / "stash.hss").write_bytes(b"stash")
        self.enterContext(patch.dict(os.environ, {"HS_DRIVE_SAVE_DIR": str(live),
                                                  "HS_DRIVE_BACKUP_DIR": str(root / "backups")}))
        made = saves.backup("live-3", gate=lambda: NOT_RUNNING)
        self.assertTrue(made["ok"], made)
        self.backup_id = made["backup_id"]
        self.created = saves._parse_utc(made["created_utc"])

    def use(self, script, inject=None):
        self.ipc = ScriptedIpc(script)
        self.inject = inject or ScriptedInject()
        self.enterContext(patch.object(stash.ipc, "send", self.ipc.send))
        self.enterContext(patch.object(stash.input_module, "inject", self.inject))

    def gated(self, started=None, running=True):
        start = self.created + timedelta(minutes=1) if started is None else started
        return dict(gate=(lambda: RUNNING) if running else (lambda: NOT_RUNNING), pids=PIDS,
                    start_reader=lambda pid: start)

    def open(self, **kwargs):
        return stash.hs_stash_open(kwargs.pop("backup_id", self.backup_id), **self.gated(**kwargs))

    def tab(self, name="materials", **kwargs):
        return stash.hs_stash_tab(name, kwargs.pop("backup_id", self.backup_id), **self.gated(**kwargs))

    def bag(self, name="materials", **kwargs):
        return stash.hs_bag_tab(name, kwargs.pop("backup_id", self.backup_id), **self.gated(**kwargs))

    def close(self, running=True):
        return stash.hs_stash_close(gate=(lambda: RUNNING) if running else (lambda: NOT_RUNNING))

    def give(self, to="bag", template=MATERIAL, count=1, **kwargs):
        return stash.hs_give_item(to, template, kwargs.pop("backup_id", self.backup_id), count=count,
                                  **self.gated(**kwargs))

    def assertRefused(self, result, reason):
        self.assertTrue(result.get("refused"), result)
        self.assertEqual(result["reason"], reason, result)
        for name in ("verb_trail", "layout_trail", "proof"):
            self.assertIn(name, result, name)
        self.assertEqual(result["lease"], "none", result)


OPEN_SCRIPT = {
    OPEN_READ: [frame(*listing(), *listing(PLAYER_BEFORE_ROW), *listing(TOWN_STASH_ROW))],
    WARP: [frame("playerwarp: before=912.0,822.0 after=884.0,628.0")],
    PLAYER_READ: [frame(*listing(PLAYER_AFTER_ROW))],
}


# --------------------------------------------------------------------------
# hs_stash_open
# --------------------------------------------------------------------------

class OpenTests(StashBase):
    def test_baseline_the_window_never_lists_is_stash_not_open(self):
        self.use({**OPEN_SCRIPT, WINDOW_READ: [NO_WINDOW]})
        result = self.open()
        self.assertRefused(result, "stash_not_open")
        self.assertEqual(self.ipc.calls, [OPEN_READ, WARP, PLAYER_READ] + [WINDOW_READ] * stash.POLL_ATTEMPTS)
        self.assertEqual(len(self.inject.calls), 1)
        self.assertEqual([v["sent"] for v in result["verb_trail"]], [WARP])

    def test_target_the_key_opens_the_window(self):
        self.use({**OPEN_SCRIPT, WINDOW_READ: [fx.STASH_WINDOW_REPLY]})
        result = self.open()
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["phase"], result["route"], result["window_id"], result["stash_tab_selected"]),
                         ("stash_open", "interact", 262983, 0))
        self.assertEqual(result["target"], [884.0, 628.0])
        self.assertEqual(self.ipc.calls, [OPEN_READ, WARP, PLAYER_READ, WINDOW_READ])
        press = self.inject.calls[0]
        self.assertEqual(press["actions"], [{"type": "key", "vk": 70, "hold_ms": 120}])
        self.assertTrue(press["force_focus"])
        self.assertTrue(press["lease_checked"])
        self.assertEqual(result["layout_trail"][0]["key"], 70)
        self.assertEqual(result["verb_trail"][0]["reply"], ["playerwarp: before=912.0,822.0 after=884.0,628.0"])
        self.assertIn(PLAYER_AFTER_ROW.strip(), result["proof"])

    def test_stash_already_open_sends_nothing_more(self):
        self.use({OPEN_READ: [frame(*inner(fx.STASH_WINDOW_REPLY), *listing(PLAYER_BEFORE_ROW),
                                    *listing(TOWN_STASH_ROW))]})
        self.assertRefused(self.open(), "stash_already_open")
        self.assertEqual((self.ipc.calls, self.inject.calls), ([OPEN_READ], []))

    def test_no_stash_in_the_room_is_stash_not_reachable(self):
        self.use({OPEN_READ: [frame(*listing(), *listing(PLAYER_BEFORE_ROW), *listing())]})
        self.assertRefused(self.open(), "stash_not_reachable")
        self.assertEqual((self.ipc.calls, self.inject.calls), ([OPEN_READ], []))

    def test_a_warp_that_does_not_land_presses_no_key(self):
        self.use({**OPEN_SCRIPT, PLAYER_READ: [frame(*listing(PLAYER_BEFORE_ROW))]})
        result = self.open()
        self.assertRefused(result, "warp_not_confirmed")
        self.assertEqual(self.inject.calls, [])
        self.assertEqual(self.ipc.calls, [OPEN_READ, WARP] + [PLAYER_READ] * stash.POLL_ATTEMPTS)

    def test_a_refused_warp_is_warp_not_confirmed(self):
        self.use({**OPEN_SCRIPT,
                  WARP: [frame("playerwarp: refused - no local player resolves by name; nothing was written")]})
        self.assertRefused(self.open(), "warp_not_confirmed")
        self.assertEqual(self.ipc.calls, [OPEN_READ, WARP])

    def test_an_undelivered_key_is_click_not_delivered(self):
        self.use({**OPEN_SCRIPT, WINDOW_READ: [fx.STASH_WINDOW_REPLY]}, inject=ScriptedInject(undelivered=True))
        self.assertRefused(self.open(), "click_not_delivered")
        self.assertNotIn(WINDOW_READ, self.ipc.calls)

    def test_an_older_build_is_plugin_verb_missing(self):
        self.use({**OPEN_SCRIPT, WARP: [frame("command unavailable in player build: playerwarp")]})
        self.assertRefused(self.open(), "plugin_verb_missing")
        self.assertEqual(self.inject.calls, [])


# --------------------------------------------------------------------------
# hs_stash_close
# --------------------------------------------------------------------------

CLOSE_UNCHANGED = frame("stashclose: before=listed after=listed",
                        "stashclose: not confirmed - UI_Stash_obj is still listed after UiACloseButton ran")


class CloseTests(StashBase):
    def test_baseline_the_window_stays_is_stash_still_open(self):
        self.use({WINDOW_READ: [fx.STASH_WINDOW_REPLY], "stashclose": [CLOSE_UNCHANGED]})
        result = self.close()
        self.assertRefused(result, "stash_still_open")
        self.assertEqual(self.ipc.calls, [WINDOW_READ, "stashclose"] + [WINDOW_READ] * stash.POLL_ATTEMPTS)

    def test_target_the_window_goes(self):
        self.use({WINDOW_READ: [fx.STASH_WINDOW_REPLY, NO_WINDOW],
                  "stashclose": [frame("stashclose: before=listed after=none")]})
        result = self.close()
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["phase"], result["window_id"]), ("stash_closed", 262983))
        self.assertEqual(self.ipc.calls, [WINDOW_READ, "stashclose", WINDOW_READ])
        self.assertEqual(result["verb_trail"], [{"sent": "stashclose", "reply": ["stashclose: before=listed after=none"]}])

    def test_no_window_is_stash_not_open_with_no_verb_sent(self):
        self.use({WINDOW_READ: [NO_WINDOW]})
        result = self.close()
        self.assertRefused(result, "stash_not_open")
        self.assertEqual((self.ipc.calls, result["verb_trail"]), ([WINDOW_READ], []))

    def test_close_takes_no_backup_and_needs_the_game(self):
        self.use({})
        self.assertRefused(self.close(running=False), "game_not_running")
        self.assertEqual(self.ipc.calls, [])


# --------------------------------------------------------------------------
# hs_stash_tab
# --------------------------------------------------------------------------

TAB_START = combined(fx.STASH_WINDOW_REPLY, fx.STASH_TABS_REPLY)


class StashTabTests(StashBase):
    def test_baseline_the_state_never_moves_is_tab_not_selected(self):
        self.use({TAB_READ: [TAB_START],
                  "stashtab -4": [frame("stashtab: before=0 after=0 handler=UiAStashMaterialTabClick",
                                        "stashtab: refused - the state did not change (stashTabSelected stayed 0)")],
                  WINDOW_READ: [fx.STASH_WINDOW_REPLY]})
        result = self.tab("materials")
        self.assertRefused(result, "tab_not_selected")
        self.assertEqual(self.ipc.calls, [TAB_READ, "stashtab -4"] + [WINDOW_READ] * stash.POLL_ATTEMPTS)

    def test_target_materials_reaches_minus_four(self):
        self.use({TAB_READ: [TAB_START],
                  "stashtab -4": [frame("stashtab: before=0 after=-4 handler=UiAStashMaterialTabClick")],
                  WINDOW_READ: [derived(stash_tab=-4)]})
        result = self.tab("materials")
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["tab_number"], result["selected_before"], result["selected_after"], result["handler"]),
                         (-4, 0, -4, "UiAStashMaterialTabClick"))
        self.assertEqual(self.ipc.calls, [TAB_READ, "stashtab -4", WINDOW_READ])

    def test_socketable_through_its_closure(self):
        self.use({TAB_READ: [TAB_START],
                  "stashtab -2": [frame("stashtab: before=0 after=-2 "
                                        "handler=anon@1018@gml_Object_UI_Stash_Tab_Bar_Container_obj_Create_0")],
                  WINDOW_READ: [derived(stash_tab=-2)]})
        result = self.tab("socketable")
        self.assertEqual((result["ok"], result["selected_after"]), (True, -2), result)

    def test_the_tab_already_on_show_sends_no_verb(self):
        self.use({TAB_READ: [TAB_START]})
        result = self.tab("personal")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["already_selected"])
        self.assertEqual((self.ipc.calls, result["verb_trail"]), ([TAB_READ], []))

    def test_an_unknown_name_is_refused_before_any_send(self):
        self.use({})
        for name in ("bank", "shared20", "", None, -4):
            with self.subTest(tab=name):
                self.assertRefused(self.tab(name), "unknown_tab")
        self.assertEqual(self.ipc.calls, [])

    def test_no_window_is_stash_not_open(self):
        self.use({TAB_READ: [combined(NO_WINDOW, fx.STASH_TABS_REPLY)]})
        self.assertRefused(self.tab("materials"), "stash_not_open")
        self.assertEqual(self.ipc.calls, [TAB_READ])

    def test_no_row_for_the_tab_is_tab_not_listed(self):
        self.use({TAB_READ: [combined(fx.STASH_WINDOW_REPLY, NO_WINDOW)]})
        self.assertRefused(self.tab("materials"), "tab_not_listed")
        self.assertEqual(self.ipc.calls, [TAB_READ])

    def test_a_handler_no_session_reproduced_is_route_not_measured(self):
        self.use({TAB_READ: [TAB_START],
                  "stashtab -5": [frame("stashtab: refused - tab -5's handler UiAStashUniqueItemType is not a "
                                        "measured shape; nothing was called")]})
        self.assertRefused(self.tab("unique"), "route_not_measured")
        self.assertEqual(self.ipc.calls, [TAB_READ, "stashtab -5"])

    def test_no_session_backup_is_refused_before_any_send(self):
        self.use({})
        result = self.tab("materials", started=self.created - timedelta(minutes=1))
        self.assertRefused(result, "no_session_backup")
        self.assertEqual((self.ipc.calls, result["verb_trail"], result["layout_trail"]), ([], [], []))

    def test_a_missing_backup_is_refused_before_any_send(self):
        self.use({})
        result = self.tab("materials", backup_id="no-such-backup")
        self.assertIn(result["reason"], ("invalid_backup_id", "backup_incomplete"), result)
        self.assertEqual((self.ipc.calls, result["verb_trail"], result["layout_trail"]), ([], [], []))


# --------------------------------------------------------------------------
# hs_bag_tab
# --------------------------------------------------------------------------

BAG_START = combined(derived(tab=0), fx.BAG_SUBTABS_REPLY)


class BagTabTests(StashBase):
    def test_baseline_tab_selected_never_moves_is_tab_not_selected(self):
        self.use({BAG_READ: [BAG_START],
                  "bagtab materials": [frame(
                      "bagtab: before=0 after=0 activeNode_before=263016 activeNode_after=263016",
                      "bagtab: refused - the state did not change (tabSelected stayed 0)")],
                  WINDOW_READ: [derived(tab=0)]})
        result = self.bag("materials")
        self.assertRefused(result, "tab_not_selected")
        self.assertEqual(self.ipc.calls, [BAG_READ, "bagtab materials"] + [WINDOW_READ] * stash.POLL_ATTEMPTS)

    def test_target_materials_moves_tab_selected_and_says_the_focus_is_not_proven(self):
        self.use({BAG_READ: [BAG_START],
                  "bagtab materials": [frame(
                      "bagtab: before=0 after=-4 activeNode_before=263016 activeNode_after=263016")],
                  WINDOW_READ: [derived(tab=-4)]})
        result = self.bag("materials")
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["selected_before"], result["selected_after"]), (0, -4))
        self.assertEqual((result["activeNode_before"], result["activeNode_after"]), ("263016", "263016"))
        self.assertIn("not proven", result["focus_note"])
        self.assertEqual(self.ipc.calls, [BAG_READ, "bagtab materials", WINDOW_READ])
        # stashTabSelected is not the bag's state: it read 0 throughout.
        self.assertIn("stashTabSelected=0", result["proof"][-1])

    def test_every_other_sub_tab_is_route_not_measured_before_any_send(self):
        self.use({})
        for name in ("vault", "vaultactive", "key", "tarot", "relic", "main", "extra", "", None):
            with self.subTest(tab=name):
                result = self.bag(name)
                self.assertRefused(result, "route_not_measured")
                self.assertEqual(result["verb_trail"], [])
        self.assertEqual(self.ipc.calls, [])

    def test_no_stash_window_is_bag_not_open(self):
        self.use({BAG_READ: [combined(NO_WINDOW, fx.BAG_SUBTABS_REPLY)]})
        self.assertRefused(self.bag("socket"), "bag_not_open")
        self.assertEqual(self.ipc.calls, [BAG_READ])

    def test_socket_by_its_callstack(self):
        self.use({BAG_READ: [BAG_START],
                  "bagtab socket": [frame("bagtab: before=0 after=-2 activeNode_before=263017 activeNode_after=263017")],
                  WINDOW_READ: [derived(tab=-2)]})
        result = self.bag("socket")
        self.assertEqual((result["ok"], result["selected_after"]), (True, -2), result)


# --------------------------------------------------------------------------
# hs_give_item
# --------------------------------------------------------------------------

GIVE_CONFIRMED = frame(f"giveitem: key={NEW_KEY} before=3 after=4 o=1",
                       f"giveitem: confirmed - {NEW_KEY} in map 0 and in the destination cells")


class GiveTests(StashBase):
    def test_target_the_confirmed_line_with_one_more_item(self):
        grid = frame(*listing(
            "  obj=UI_Inventory_Grid_obj id=257745 gui=357.2,1337.6 win=268,1056 bbox=357.2,1337.6,358.2,1338.6 "
            "visible=1 sprite=none uiNodeCallstack=PotionGrid activationArgs=[] enabled=0 nodeGridWidth=4 "
            "nodeGridHeight=1 gridScale=0.5 gridName= text=",
            f"  cell=1,0 grid=257745 fp={NEW_KEY} o=none"))
        self.use({GIVE: [GIVE_CONFIRMED], GRID_READ: [grid]})
        result = self.give()
        self.assertTrue(result["ok"], result)
        self.assertEqual((result["confirmed"], result["key"], result["before"], result["after"], result["o"]),
                         (True, NEW_KEY, 3, 4, 1))
        self.assertEqual(self.ipc.calls, [GIVE, GRID_READ])
        self.assertIn(f"cell=1,0 grid=257745 fp={NEW_KEY} o=none", result["proof"])
        self.assertIn(f"giveitem: confirmed - {NEW_KEY} in map 0 and in the destination cells",
                      result["verb_trail"][0]["reply"])

    def test_a_listing_without_the_key_is_not_required(self):
        # With no window open only the HUD belt grid is listed.
        self.use({GIVE: [GIVE_CONFIRMED], GRID_READ: [frame(*listing())]})
        result = self.give()
        self.assertTrue(result["ok"], result)

    def test_baseline_no_confirmed_line_is_give_not_confirmed(self):
        self.use({GIVE: [frame(f"giveitem: key={NEW_KEY} before=3 after=3 o=1",
                               f"giveitem: not confirmed - map 0 answers 1, the destination cells answer 0 "
                               f"for {NEW_KEY}, items 3 -> 3")]})
        result = self.give()
        self.assertRefused(result, "give_not_confirmed")
        self.assertEqual(self.ipc.calls, [GIVE])

    def test_a_confirmed_line_without_one_more_item_is_not_confirmed(self):
        self.use({GIVE: [frame(f"giveitem: key={NEW_KEY} before=3 after=3 o=1",
                               f"giveitem: confirmed - {NEW_KEY} in map 0 and in the destination cells")]})
        self.assertRefused(self.give(), "give_not_confirmed")

    def test_the_stash_is_route_not_measured_before_any_send(self):
        self.use({})
        result = self.give(to="stash")
        self.assertRefused(result, "route_not_measured")
        self.assertEqual((self.ipc.calls, result["verb_trail"]), ([], []))

    def test_a_count_it_cannot_make_is_refused_before_any_send(self):
        self.use({})
        for count in (0, -1, 1.5, "2", True):
            with self.subTest(count=count):
                self.assertRefused(self.give(count=count), "count_unsupported")
        self.assertEqual(self.ipc.calls, [])

    def test_the_verbs_count_refusal_is_count_unsupported(self):
        line = f"giveitem bag {MATERIAL} 2"
        self.use({line: [frame(f"giveitem: refused - count above 1: template {MATERIAL}'s save struct has no o "
                               "(a non-stackable); nothing was made")]})
        self.assertRefused(self.give(count=2), "count_unsupported")
        self.assertEqual(self.ipc.calls, [line])

    def test_an_unknown_template_is_template_not_found(self):
        self.use({GIVE: [frame(f"giveitem: refused - template not found: map 0 holds no item {MATERIAL}; "
                               "nothing more was called")]})
        self.assertRefused(self.give(), "template_not_found")
        self.assertEqual(self.ipc.calls, [GIVE])

    def test_any_other_refusal_of_the_verb_is_give_refused(self):
        self.use({GIVE: [frame("giveitem: refused - InitItemFromJson answered no item; nothing was placed")]})
        result = self.give()
        self.assertRefused(result, "give_refused")
        self.assertIn("InitItemFromJson", result["detail"])

    def test_bad_arguments_are_refused_before_any_send(self):
        self.use({})
        self.assertRefused(self.give(to="cube"), "invalid_input")
        self.assertRefused(self.give(template="two words"), "invalid_input")
        self.assertEqual(self.ipc.calls, [])

    def test_an_older_build_is_plugin_verb_missing(self):
        self.use({GIVE: [frame("command unavailable in player build: giveitem")]})
        self.assertRefused(self.give(), "plugin_verb_missing")

    def test_no_game_is_game_not_running_before_any_send(self):
        self.use({})
        self.assertRefused(self.give(running=False), "game_not_running")
        self.assertEqual(self.ipc.calls, [])


class VocabularyTests(unittest.TestCase):
    def test_the_thirteen_tokens_are_defined_once_and_answered_here(self):
        self.assertEqual(len(results.STASH_REASONS), 13)
        self.assertEqual(len(set(results.STASH_REASONS)), 13)
        for token in results.STASH_REASONS + results.ACTION_REASONS:
            self.assertEqual(results.REASONS.count(token), 1, token)
        source = (ROOT / "tools" / "hs_drive_mcp" / "stash.py").read_text(encoding="utf-8")
        for token in results.STASH_REASONS + ("route_not_measured", "plugin_verb_missing"):
            self.assertIn(f'"{token}"', source, token)
        # `no_session_backup` is the shared gate's, never spelled here.
        self.assertIn("saves.session_backup_gate(", source)
        self.assertNotIn('"no_session_backup"', source)


if __name__ == "__main__":
    unittest.main()

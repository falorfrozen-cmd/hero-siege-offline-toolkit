"""`tools/hs_drive_mcp/layout.py` -- parsing ForgePact's `menulayout` listing.

Pure parsing: no game, no Windows, no submodule, no MCP SDK.

The fixtures are the three replies phase 0 captured from a running game
(`tests/hs_drive_mcp_menulayout_fixtures.py`), exactly as `ipc.send` returned
them -- framed by `---- running command file ----` / `---- done ----`, CRLF --
because a double that hands back a bare or reshaped line cannot represent the
input a live run fails on (the L-1 lesson `charselect._reply_line` was
written for). Hand-written listings appear only where a test needs a shape
no live screen showed (two candidates, an unreadable field, a short page),
each one next to the verbatim case it varies.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import layout  # noqa: E402
from tests.hs_drive_mcp_menulayout_fixtures import (  # noqa: E402
    CHOSE_RM_REPLY, MAIN_MENU_REPLY, PANEL_REPLY)
from tests import hs_drive_mcp_skillstate_fixtures as skill_fixtures  # noqa: E402
from tests import hs_drive_mcp_stashlayout_fixtures as stash_fixtures  # noqa: E402

CLIENT_1080 = [1920, 1080]
HEADER_CHOSE_RM = ("menulayout: room=Chose_rm gui=2560x1368 window=1920x1080 "
                   "fullscreen=0 view=0.0,0.0,1280.0,720.0")


def card(slot, x, y, visible=1):
    """One `Choose_Parent_obj` row in the shape phase 0 listed them."""
    return (f"  obj=Choose_Parent_obj id={257047 + slot} gui=0.0,0.0 "
            f"win={x},{y} bbox=0.0,0.0,1.0,1.0 visible={visible} "
            f"sprite=Choosing_SSF_spr slot={slot} text=")


def reply(text):
    """What `ipc.send` returns for a command: `reply` plus `reply_lines`."""
    return {"ok": True, "refused": False, "reply": text,
            "reply_lines": text.splitlines()}


def framed(*lines):
    return ("---- running command file ----\r\n" + "".join(l + "\r\n" for l in lines)
            + "---- done ----\r\n")


class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.listing = layout.parse(reply(MAIN_MENU_REPLY))

    def test_header_fields(self):
        self.assertIsNotNone(self.listing)
        self.assertEqual(self.listing.room, "Main_Menu_rm")
        self.assertEqual(self.listing.gui, (2560, 1368))
        self.assertEqual(self.listing.window, (1920, 1080))
        self.assertIs(self.listing.fullscreen, False)
        self.assertEqual(self.listing.view, (0.0, 0.0, 1280.0, 720.0))

    def test_footer_fields(self):
        self.assertEqual(self.listing.listed, 19)
        self.assertEqual(self.listing.absent, ())
        self.assertIs(self.listing.capped, False)
        self.assertEqual(len(self.listing.rows), self.listing.listed)

    def test_absent_names_are_kept(self):
        listing = layout.parse(reply(framed(
            "menulayout: room=Chose_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=0.0,0.0,2560.0,1368.0",
            "menulayout: listed=0 absent=Save_Slot_Shop_obj,UI_Main_Menu_obj capped=1")))
        self.assertEqual(listing.absent, ("Save_Slot_Shop_obj", "UI_Main_Menu_obj"))
        self.assertIs(listing.capped, True)
        self.assertEqual(listing.rows, ())

    def test_a_bare_reply_without_reply_lines_parses_the_same(self):
        bare = {"reply": MAIN_MENU_REPLY}
        self.assertEqual(layout.parse(bare), self.listing)


class RowTests(unittest.TestCase):
    def setUp(self):
        self.rows = layout.parse(reply(MAIN_MENU_REPLY)).rows

    def test_play_local_row(self):
        row = self.rows[0]
        self.assertEqual(row.obj, "UI_Button_obj")
        self.assertEqual(row.id, 257029)
        self.assertEqual(row.gui, (448.0, 676.4))
        self.assertEqual(row.win, (336, 534))
        self.assertEqual(row.bbox, (240.0, 604.2, 658.0, 750.5))
        self.assertIs(row.visible, True)
        self.assertEqual(row.sprite, "Menu_Button_Kaelith_spr")
        self.assertEqual(row.text, "Play local")

    def test_text_runs_to_the_end_of_the_line(self):
        texts = [row.text for row in self.rows]
        self.assertIn("Cosmetic Shop", texts)
        self.assertIn("Featured Cosmetics", texts)
        row = layout.parse_row(
            "  obj=UI_Button_obj id=1 gui=1.0,2.0 win=1,2 bbox=0.0,0.0,1.0,1.0 "
            'visible=1 sprite=none text=Say "hi" = win=9,9 text=x')
        self.assertEqual(row.text, 'Say "hi" = win=9,9 text=x')
        self.assertEqual(row.win, (1, 2))

    def test_empty_text_is_empty(self):
        self.assertEqual(self.rows[5].obj, "UI_Container_obj")
        self.assertEqual(self.rows[5].text, "")
        self.assertIs(self.rows[5].visible, False)

    def test_read_failed_is_none_never_zero(self):
        row = layout.parse_row(
            "  obj=X id=<read-failed> gui=<read-failed>,3.0 win=<read-failed>,<read-failed> "
            "bbox=0.0,0.0,1.0,1.0 visible=<read-failed> sprite=<read-failed> text=")
        self.assertIsNone(row.id)
        self.assertEqual(row.gui, (None, 3.0))
        self.assertEqual(row.win, (None, None))
        self.assertIsNone(row.visible)

    def test_optional_fields_are_kept_apart_from_text(self):
        row = layout.parse_row(
            "  obj=Save_Character_obj id=7 gui=324.0,285.0 win=243,225 bbox=0.0,0.0,1.0,1.0 "
            "visible=1 sprite=none name=Pal Two slot=0 selected=1 text=")
        self.assertEqual(row.extra, {"name": "Pal Two", "slot": "0", "selected": "1"})
        self.assertEqual(row.text, "")

    def test_non_row_lines_are_not_rows(self):
        self.assertIsNone(layout.parse_row("---- done ----"))
        self.assertIsNone(layout.parse_row("menulayout: listed=0 absent=none capped=0"))


class MatcherTests(unittest.TestCase):
    def test_play_local_is_exactly_one_visible_ui_button(self):
        listing = layout.parse(reply(MAIN_MENU_REPLY))
        rows = layout.play_local_rows(listing)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].obj, "UI_Button_obj")
        self.assertIs(rows[0].visible, True)
        self.assertEqual(layout.match_play_local(listing).win, (336, 534))

    def test_negative_control_hidden_and_other_objects_are_ignored(self):
        # A hidden `UI_Button_obj` whose text is also `Play local` must never
        # be the answer, and neither may another object with the same text
        # or a button whose text merely starts with it. (The live main menu
        # has the hidden-duplicate shape too: a second, `visible=0`
        # `Cosmetic Shop`.)
        listing = layout.parse(reply(framed(
            "menulayout: room=Main_Menu_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=0.0,0.0,2560.0,1368.0",
            "  obj=UI_Button_obj id=5 gui=900.0,500.0 win=675,395 bbox=0.0,0.0,1.0,1.0 visible=0 sprite=none text=Play local",
            "  obj=UI_Button_Small_obj id=6 gui=900.0,500.0 win=675,395 bbox=0.0,0.0,1.0,1.0 visible=1 sprite=none text=Play local",
            "  obj=UI_Button_obj id=7 gui=900.0,500.0 win=675,395 bbox=0.0,0.0,1.0,1.0 visible=1 sprite=none text=Play localx",
            "menulayout: listed=3 absent=none capped=0")))
        self.assertEqual(layout.play_local_rows(listing), [])
        self.assertIsNone(layout.match_play_local(listing))

    def test_two_candidates_is_not_an_answer(self):
        line = ("  obj=UI_Button_obj id={} gui=448.0,676.4 win=336,534 bbox=0.0,0.0,1.0,1.0 "
                "visible=1 sprite=none text=Play local")
        listing = layout.parse(reply(framed(
            "menulayout: room=Main_Menu_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=0.0,0.0,2560.0,1368.0",
            line.format(1), line.format(2),
            "menulayout: listed=2 absent=none capped=0")))
        self.assertEqual(len(layout.play_local_rows(listing)), 2)
        self.assertIsNone(layout.match_play_local(listing))

    def test_an_unreadable_point_is_not_clickable(self):
        listing = layout.parse(reply(framed(
            "menulayout: room=Main_Menu_rm gui=<read-failed>x1368 window=1920x1080 fullscreen=0 view=0.0,0.0,2560.0,1368.0",
            "  obj=UI_Button_obj id=1 gui=448.0,676.4 win=<read-failed>,534 bbox=0.0,0.0,1.0,1.0 visible=1 sprite=none text=Play local",
            "menulayout: listed=1 absent=none capped=0")))
        self.assertIsNone(layout.match_play_local(listing))


class ReadTests(unittest.TestCase):
    def test_a_good_listing_reads(self):
        listing, reason, detail = layout.read(reply(MAIN_MENU_REPLY), CLIENT_1080)
        self.assertEqual((reason, detail), ("", ""))
        self.assertEqual(listing.room, "Main_Menu_rm")

    def test_an_older_player_build_is_layout_command_missing(self):
        listing, reason, detail = layout.read(
            reply(framed("command unavailable in player build: menulayout")), CLIENT_1080)
        self.assertIsNone(listing)
        self.assertEqual(reason, "layout_command_missing")
        self.assertIn("command unavailable in player build: menulayout", detail)

    def test_no_header_is_layout_command_missing(self):
        for text in (framed("pong"), "", framed()):
            listing, reason, detail = layout.read(reply(text), CLIENT_1080)
            self.assertIsNone(listing, text)
            self.assertEqual(reason, "layout_command_missing", text)
            self.assertIn("menulayout: room=", detail)

    def test_window_disagreeing_with_the_client_is_window_size_mismatch(self):
        listing, reason, detail = layout.read(reply(MAIN_MENU_REPLY), [2560, 1440])
        self.assertIsNotNone(listing)
        self.assertEqual(reason, "window_size_mismatch")
        self.assertIn("1920x1080", detail)
        self.assertIn("2560x1440", detail)

    def test_an_unreadable_window_is_a_mismatch_not_a_pass(self):
        text = MAIN_MENU_REPLY.replace("window=1920x1080", "window=<read-failed>x<read-failed>")
        _, reason, _ = layout.read(reply(text), CLIENT_1080)
        self.assertEqual(reason, "window_size_mismatch")


class SlotMatcherTests(unittest.TestCase):
    """Phase 0's `slotObject: Choose_Parent_obj`, `slotRule: order:y,x over
    the visible=1 rows`, against the `Chose_rm` listing it captured."""

    def setUp(self):
        self.listing = layout.parse(reply(CHOSE_RM_REPLY))

    def test_the_listing_is_the_slot_screen(self):
        self.assertEqual(self.listing.room, layout.SLOT_ROOM)
        self.assertEqual(self.listing.listed, 56)

    def test_page_one_has_24_visible_cards_and_the_hidden_duplicates_are_dropped(self):
        every = [row for row in self.listing.rows
                 if row.obj == layout.SLOT_OBJECT]
        self.assertEqual(len(every), 48, "24 visible cards plus 24 hidden")
        cards = layout.slot_rows(self.listing)
        self.assertEqual(len(cards), 24)
        self.assertTrue(all(row.visible for row in cards))

    def test_slot_1_is_the_top_left_card(self):
        row = layout.match_slot(self.listing, 1)
        self.assertEqual(row.win, (177, 174))
        self.assertEqual(row.id, 257048)

    def test_slot_2_is_the_card_right_of_slot_1_on_the_same_row(self):
        # D12, the owner's rule: slots run left to right along a row, then
        # the next row -- slot 2 is grid x:1, y:0, never x:0, y:1.
        one = layout.match_slot(self.listing, 1)
        two = layout.match_slot(self.listing, 2)
        self.assertEqual(two.win, (381, 174))
        self.assertGreater(two.win[0], one.win[0])
        self.assertEqual(two.win[1], one.win[1])
        below = layout.match_slot(self.listing, 9)
        self.assertEqual(below.win, (177, 429),
                         "the card below slot 1 is slot 9, the next row's first")
        self.assertNotEqual(two.win, below.win)

    def test_row_major_order_holds_whatever_order_the_rows_are_listed_in(self):
        # Two cards on the top row, one on the next, listed column-first --
        # the order a column-major reading would number 1, 2, 3.
        listing = layout.parse(reply(framed(
            HEADER_CHOSE_RM,
            card(1, 177, 174), card(3, 177, 429), card(2, 381, 174),
            card(4, 381, 174, visible=0),
            "menulayout: listed=4 absent=none capped=0")))
        self.assertEqual(layout.match_slot(listing, 1).win, (177, 174))
        self.assertEqual(layout.match_slot(listing, 2).win, (381, 174))
        self.assertEqual(layout.match_slot(listing, 3).win, (177, 429))
        self.assertIsNone(layout.match_slot(listing, 4),
                          "a hidden card is not a slot")

    def test_the_game_slot_variable_agrees_with_the_row_major_order(self):
        # Phase 0 checked this on the live screen; the fixture carries it.
        for index, row in enumerate(layout.slot_rows(self.listing), start=1):
            self.assertEqual(row.extra.get("slot"), str(index), row.line)

    def test_a_slot_beyond_the_listed_cards_is_none(self):
        self.assertIsNone(layout.match_slot(self.listing, 25))
        self.assertIsNone(layout.match_slot(self.listing, 0))

    def test_the_main_menu_lists_no_cards(self):
        self.assertEqual(layout.slot_rows(layout.parse(reply(MAIN_MENU_REPLY))),
                         [])


class PlayMatcherTests(unittest.TestCase):
    """Phase 0's `playObject: UI_Button_obj`, `playRule: text=Play exactly
    and visible=1`, against the character-panel listing it captured."""

    def test_play_is_the_one_visible_play_button_on_the_panel(self):
        listing = layout.parse(reply(PANEL_REPLY))
        row = layout.match_play(listing)
        self.assertIsNotNone(row)
        self.assertEqual((row.obj, row.id, row.win, row.text),
                         ("UI_Button_obj", 257591, (584, 345), "Play"))

    def test_play_is_not_listed_before_a_card_is_clicked(self):
        self.assertIsNone(layout.match_play(layout.parse(reply(CHOSE_RM_REPLY))))

    def test_play_local_is_not_play(self):
        self.assertEqual(layout.play_rows(layout.parse(reply(MAIN_MENU_REPLY))),
                         [])

    def test_the_cards_stay_listed_behind_the_panel(self):
        # Phase 0: card rows stay visible=1 under the panel, so their
        # disappearance cannot be the signal the panel opened -- PLAY is.
        self.assertEqual(len(layout.slot_rows(layout.parse(reply(PANEL_REPLY)))),
                         24)

    def test_case_and_visibility_matter(self):
        listing = layout.parse(reply(framed(
            HEADER_CHOSE_RM,
            "  obj=UI_Button_obj id=1 gui=0.0,0.0 win=584,345 bbox=0.0,0.0,1.0,1.0 visible=1 sprite=none text=PLAY",
            "  obj=UI_Button_obj id=2 gui=0.0,0.0 win=584,345 bbox=0.0,0.0,1.0,1.0 visible=0 sprite=none text=Play",
            "  obj=UI_Button_Small_obj id=3 gui=0.0,0.0 win=584,345 bbox=0.0,0.0,1.0,1.0 visible=1 sprite=none text=Play",
            "menulayout: listed=3 absent=none capped=0")))
        self.assertIsNone(layout.match_play(listing))

    def test_describe_quotes_the_header_and_the_visible_buttons(self):
        text = layout.describe(layout.parse(reply(PANEL_REPLY)), "UI_Button_obj")
        self.assertIn("room=Chose_rm", text)
        self.assertIn("'Play' win=584,345", text)


class FixtureTests(unittest.TestCase):
    def test_fixtures_are_framed_and_crlf(self):
        for name, text in (("main menu", MAIN_MENU_REPLY),
                           ("Chose_rm", CHOSE_RM_REPLY),
                           ("panel", PANEL_REPLY)):
            with self.subTest(name):
                self.assertTrue(text.startswith("---- running command file ----\r\n"))
                self.assertTrue(text.endswith("---- done ----\r\n"))
                self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_every_fixture_row_parses_and_the_footer_count_matches(self):
        for text in (MAIN_MENU_REPLY, CHOSE_RM_REPLY, PANEL_REPLY):
            listing = layout.parse(reply(text))
            self.assertEqual(len(listing.rows), listing.listed)
            self.assertEqual(listing.window, (1920, 1080))


class SkillBarAndTalentScreenTests(unittest.TestCase):
    """The skill bar's `slot=` rows and the talent screen's `talentId`/`name`
    fields, on the `menulayout` replies live 2 of the skill research printed
    (`tests/hs_drive_mcp_skillstate_fixtures.py`, cut from that session's
    `out.txt`)."""

    def test_the_bar_row_carries_its_29_slot_rows(self):
        # 13 in row 0 (slots 0-12) and 16 in row 1 (0-15); live 2's capture
        # summarised them as 28, the reply itself holds 29.
        listing = layout.parse(reply(skill_fixtures.MENULAYOUT_HUD))
        self.assertEqual(len(listing.rows), 1)
        bar = listing.rows[0]
        self.assertEqual((bar.obj, bar.id), ("UI_Hud_Talent_obj", 262341))
        self.assertEqual(len(bar.slots), 29)
        self.assertEqual([s.row for s in bar.slots].count(0), 13)
        first = bar.slots[0]
        self.assertEqual((first.row, first.index, first.talent), (0, 0, 242))
        self.assertEqual(first.win, (6, 885))
        self.assertEqual(first.gui, (7.6, 1121.0))
        # An empty slot is the game's own 0, not an unreadable None.
        self.assertEqual(bar.slots[6].talent, 0)
        self.assertEqual([(s.row, s.index) for s in bar.slots[13:15]], [(1, 0), (1, 1)])
        # The slot lines are the bar's, never rows of their own.
        self.assertEqual(listing.listed, 1)

    def test_a_slot_line_belongs_only_to_the_bar_row(self):
        text = framed(HEADER_CHOSE_RM,
                      "  obj=UI_Button_obj id=1 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,1.0,1.0 visible=1 sprite=none text=",
                      "  slot=0,0 talent=242 gui=7.6,1121.0 win=6,885",
                      "menulayout: listed=1 absent=none capped=0")
        listing = layout.parse(reply(text))
        self.assertEqual(listing.rows[0].slots, ())
        # A whole-array line and an unreadable id are not plausible values.
        bar = layout.parse(reply(framed(
            HEADER_CHOSE_RM,
            "  obj=UI_Hud_Talent_obj id=2 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none text=",
            "  slot=0,* absent",
            "  slot=1,0 talent=none gui=none,none win=none,none",
            "menulayout: listed=1 absent=none capped=0"))).rows[0]
        self.assertEqual([(s.row, s.index, s.talent) for s in bar.slots], [(0, None, None), (1, 0, None)])
        self.assertEqual(bar.slots[1].win, (None, None))

    def test_the_talent_buttons_carry_talent_id_and_a_name_with_spaces(self):
        listing = layout.parse(reply(skill_fixtures.MENULAYOUT_TALENT_BUTTONS))
        self.assertEqual(listing.listed, 18)
        self.assertEqual(len(listing.rows), 18)
        shadow = layout.rows_with_talent(listing, "UI_Button_Talent_Player_obj", 239)
        self.assertEqual([(r.id, r.name) for r in shadow], [(275481, "Shadow Bolt")])
        black = layout.rows_with_talent(listing, "UI_Button_Talent_Player_obj", 244)
        self.assertEqual([r.name for r in black], ["Black Mass"])
        # Negative control: no talent button carries an id nobody listed.
        self.assertEqual(layout.rows_with_talent(listing, "UI_Button_Talent_Player_obj", 999), [])
        # A name the game spells with a typographic apostrophe survives.
        self.assertIn("Satan’s Mark", [r.name for r in listing.rows])

    def test_the_sub_skill_buttons_and_the_nodes(self):
        sub = layout.parse(reply(skill_fixtures.MENULAYOUT_SUB_SKILL_BUTTONS))
        self.assertEqual([r.id for r in layout.rows_with_talent(sub, "UI_Button_Sub_Skill_obj", 239)], [275482])
        nodes = layout.parse(reply(skill_fixtures.MENULAYOUT_SUBTALENT_NODES))
        self.assertEqual(len(nodes.rows), 15)
        # The nodes carry no talentId and no name: live 2's reason the verb
        # takes the nth listed node.
        self.assertEqual({r.talent_id for r in nodes.rows}, {None})
        self.assertEqual({r.name for r in nodes.rows}, {None})
        self.assertEqual([r.id for r in nodes.rows[:2]], [275677, 275678])

    def test_the_talent_screen_open_and_closed(self):
        opened = layout.parse(reply(skill_fixtures.MENULAYOUT_TALENT_SCREEN_OPEN))
        self.assertEqual([(r.obj, r.id) for r in opened.rows], [("UI_Talent_Screen_obj", 275195)])
        closed = layout.parse(reply(skill_fixtures.MENULAYOUT_TALENT_SCREEN_CLOSED))
        self.assertEqual((closed.listed, closed.rows), (0, ()))


# --------------------------------------------------------------------------
# The stash and the bag (hs-drive-stash-bag-actions)
# --------------------------------------------------------------------------

STASH_FIXTURES = {name: getattr(stash_fixtures, name) for name in (
    "STASH_WINDOW_REPLY", "STASH_TABS_REPLY", "BAG_SUBTABS_REPLY",
    "STASH_CLOSE_BUTTON_REPLY", "MULTI_LISTING_REPLY")}


def cell_line(x, y, grid, fp):
    """A cell row in the format ForgePact's `MenuLayoutCells` prints
    (`test_stash_bag_layout_contract.MenuLayoutCellRows` pins it); no live
    reply carries one yet - live 3 captures the first."""
    return f"  cell={x},{y} grid={grid} fp={fp} o=none"


GRID_HEADER = ("menulayout: room=Town_01_rm gui=2560x1368 window=1920x1080 fullscreen=0 "
               "view=244.0,268.0,1280.0,720.0")
#: The bag's main grid row as live 2 attempt 1 listed it (MULTI_LISTING_REPLY).
BAG_GRID_ROW = ("  obj=UI_Inventory_Grid_obj id=264099 gui=1572.0,765.7 win=1179,605 "
                "bbox=1572.0,765.7,2484.0,1130.5 visible=1 sprite=none uiNodeCallstack=InventoryGrid "
                "activationArgs=[] enabled=1 nodeGridWidth=15 nodeGridHeight=6 gridScale=1 gridName= text=")
BELT_GRID_ROW = ("  obj=UI_Inventory_Grid_obj id=257745 gui=357.2,1337.6 win=268,1056 "
                 "bbox=357.2,1337.6,358.2,1338.6 visible=1 sprite=none uiNodeCallstack=PotionGrid "
                 "activationArgs=[] enabled=0 nodeGridWidth=4 nodeGridHeight=1 gridScale=0.5 gridName= text=")


class StashFixtureTests(unittest.TestCase):
    def test_every_stash_fixture_is_framed_crlf_and_parses(self):
        for name, text in STASH_FIXTURES.items():
            with self.subTest(fixture=name):
                self.assertTrue(text.startswith("---- running command file ----\r\n"))
                self.assertTrue(text.endswith("---- done ----\r\n"))
                self.assertNotIn("\n", text.replace("\r\n", ""))
                listings = layout.parse_all(reply(text))
                self.assertTrue(listings)
                for listing in listings:
                    self.assertEqual(listing.listed, len(listing.rows), listing.header)
                    self.assertEqual(listing.window, (1920, 1080))

    def test_one_send_of_six_menulayout_lines_parses_to_six_listings(self):
        listings = layout.parse_all(reply(stash_fixtures.MULTI_LISTING_REPLY))
        self.assertEqual([l.listed for l in listings], [1, 23, 5, 6, 2, 0])
        self.assertEqual({r.obj for r in listings[1].rows}, {"UI_Button_Stash_Tab_obj"})
        # parse() still answers the first listing only.
        self.assertEqual(layout.parse(reply(stash_fixtures.MULTI_LISTING_REPLY)).listed, 1)
        # Negative control: a reply with no header has no listing.
        self.assertEqual(layout.parse_all(reply(framed("pong"))), [])


class StashMatcherTests(unittest.TestCase):
    def setUp(self):
        self.window = layout.parse_all(reply(stash_fixtures.STASH_WINDOW_REPLY))
        self.tabs = layout.parse_all(reply(stash_fixtures.STASH_TABS_REPLY))
        self.subtabs = layout.parse_all(reply(stash_fixtures.BAG_SUBTABS_REPLY))
        self.multi = layout.parse_all(reply(stash_fixtures.MULTI_LISTING_REPLY))

    def test_the_stash_window_and_its_tab_state(self):
        row = layout.match_stash_window(self.window)
        self.assertEqual((row.id, row.number("stashTabSelected")), (262983, 0))
        # tabSelected is not printed by the live-2 build: None, never 0.
        self.assertIsNone(row.number("tabSelected"))
        # Negative control: no window in the tab listing, and two windows are not one.
        self.assertIsNone(layout.match_stash_window(self.tabs))
        self.assertIsNone(layout.match_stash_window(self.window + self.window))

    def test_a_stash_tab_by_its_tab_number(self):
        for number, row_id, text in ((-4, 263032, "Materials"), (-2, 263031, "Socketable"),
                                     (-5, 263033, "Unique"), (0, 263034, "Personal"),
                                     (19, 263053, "Shared19")):
            row = layout.match_stash_tab(self.tabs, number)
            self.assertEqual((row.id, row.text), (row_id, text))
        # Negative control: a number no row carries, and the bag's tab rows.
        self.assertIsNone(layout.match_stash_tab(self.tabs, 20))
        self.assertIsNone(layout.match_stash_tab(self.subtabs, -4))

    def test_a_bag_subtab_by_its_callstack(self):
        self.assertEqual(layout.match_bag_subtab(self.subtabs, "InventoryTabMaterial").id, 263017)
        self.assertEqual(layout.match_bag_subtab(self.subtabs, "InventoryTabSocket").id, 263016)
        # Negative control: the text is empty on every row, so text is no key.
        self.assertIsNone(layout.match_bag_subtab(self.subtabs, ""))
        self.assertIsNone(layout.match_bag_subtab(self.tabs, "InventoryTabMaterial"))

    def test_the_bag_grid_and_the_player_and_stash_positions(self):
        grid = layout.match_bag_grid(self.multi)
        self.assertEqual((grid.id, grid.number("nodeGridWidth"), grid.number("nodeGridHeight")),
                         (264099, 15, 6))
        self.assertIsNone(layout.match_bag_grid(self.window))
        listing = layout.parse_all(reply(framed(
            GRID_HEADER,
            "  obj=Town_Stash_obj id=228465 gui=884.0,580.0 win=663,458 bbox=856.0,565.0,913.0,598.0 "
            "visible=1 sprite=Stash_Act_01_spr text=",
            "menulayout: listed=1 absent=none capped=0",
            GRID_HEADER,
            "  obj=Player_obj id=261723 gui=884.0,628.0 win=663,496 bbox=872.0,622.0,896.0,646.0 "
            "visible=1 sprite=none name=Sorak text=",
            "menulayout: listed=1 absent=none capped=0")))
        self.assertEqual(layout.match_town_stash(listing).gui, (884.0, 580.0))
        self.assertEqual(layout.match_player(listing).gui, (884.0, 628.0))
        self.assertIsNone(layout.match_player(self.window))

    def test_cell_rows_belong_to_their_grid_and_match_by_fingerprint(self):
        text = framed(GRID_HEADER, BELT_GRID_ROW,
                      cell_line(0, 0, 257745, "0-0-209492724983-18"),
                      BAG_GRID_ROW,
                      cell_line(3, 0, 264099, "0-0-209564349884-14"),
                      cell_line(4, 0, 264099, "0-0-1-3"), cell_line(4, 1, 264099, "0-0-1-3"),
                      "menulayout: listed=2 absent=none capped=0")
        listings = layout.parse_all(reply(text))
        belt, bag = listings[0].rows
        self.assertEqual([c.fp for c in belt.cells], ["0-0-209492724983-18"])
        self.assertEqual(len(bag.cells), 3)
        cell = bag.cells[0]
        self.assertEqual((cell.x, cell.y, cell.grid, cell.o), (3, 0, 264099, None))
        self.assertEqual(layout.match_item_grid(listings, "0-0-209564349884-14").id, 264099)
        self.assertEqual(len(layout.cells_holding(listings, "0-0-1-3")), 2)   # one row per cell covered
        self.assertEqual(layout.free_cells(bag), 15 * 6 - 3)
        # Negative controls: an absent key, and a cell line under a non-grid row.
        self.assertIsNone(layout.match_item_grid(listings, "0-0-9-9"))
        self.assertEqual(layout.cells_holding(listings, "0-0-9-9"), [])
        stray = layout.parse_all(reply(framed(
            GRID_HEADER, "  obj=UI_Stash_obj id=1 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 "
            "sprite=none enabled=1 stashTabSelected=0 tabSelected=-4 text=",
            cell_line(0, 0, 1, "0-0-2-14"), "menulayout: listed=1 absent=none capped=0")))
        self.assertEqual(stray[0].rows[0].cells, ())
        self.assertEqual(stray[0].rows[0].number("tabSelected"), -4)

    def test_a_capped_grid_has_no_free_cell_count(self):
        capped = layout.parse_row(BAG_GRID_ROW.replace(" text=", " cellcap=1 text="))
        self.assertTrue(capped.cellcap)
        self.assertIsNone(layout.free_cells(capped))
        self.assertFalse(layout.parse_row(BAG_GRID_ROW).cellcap)


class VerbReplyTests(unittest.TestCase):
    """Each player verb's reply in the format
    `ForgePact/tests/test_stash_bag_layout_contract.StashBagPlayerVerbs` pins."""

    def test_before_after_and_the_fields_beside_them(self):
        parsed = layout.parse_verb(reply(framed(
            "bagtab: before=0 after=-4 activeNode_before=263016 activeNode_after=263016")), "bagtab")
        self.assertEqual((parsed.before, parsed.after), ("0", "-4"))
        self.assertEqual(parsed.fields["activeNode_after"], "263016")
        self.assertIsNone(parsed.refused)
        warp = layout.parse_verb(reply(framed("playerwarp: before=912.0,822.0 after=884.0,628.0")), "playerwarp")
        self.assertEqual(warp.after, "884.0,628.0")

    def test_giveitem_confirmed_and_not_confirmed(self):
        good = layout.parse_verb(reply(framed(
            "giveitem: key=0-0-212527295000-14 before=3 after=4 o=1",
            "giveitem: confirmed - 0-0-212527295000-14 in map 0 and in the destination cells")), "giveitem")
        self.assertEqual((good.fields["key"], good.before, good.after, good.fields["o"]),
                         ("0-0-212527295000-14", "3", "4", "1"))
        self.assertTrue(good.confirmed)
        self.assertIsNone(good.not_confirmed)
        bad = layout.parse_verb(reply(framed(
            "giveitem: key=0-0-212527295000-14 before=3 after=3 o=1",
            "giveitem: not confirmed - map 0 answers 1, the destination cells answer 0")), "giveitem")
        self.assertIsNone(bad.confirmed)
        self.assertTrue(bad.not_confirmed)

    def test_a_refusal_and_an_older_build(self):
        refused = layout.parse_verb(reply(framed(
            "stashtab: refused - stash not open (no UI_Stash_obj is listed); nothing was called")), "stashtab")
        self.assertTrue(refused.refused.startswith("stash not open"))
        self.assertEqual(refused.fields, {})
        old = layout.parse_verb(reply(framed("command unavailable in player build: stashtab")), "stashtab")
        self.assertTrue(old.unavailable)
        # Negative control: another verb's lines are not this verb's.
        other = layout.parse_verb(reply(framed("bagtab: before=0 after=-4")), "stashtab")
        self.assertEqual((other.lines, other.fields, other.unavailable), ((), {}, False))


if __name__ == "__main__":
    unittest.main()

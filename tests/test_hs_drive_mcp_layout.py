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


if __name__ == "__main__":
    unittest.main()

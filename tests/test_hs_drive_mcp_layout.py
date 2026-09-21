"""`tools/hs_drive_mcp/layout.py` -- parsing ForgePact's `menulayout` listing.

Pure parsing: no game, no Windows, no submodule, no MCP SDK.

The fixture is a reply exactly as `ipc.send` returns it -- framed by
`---- running command file ----` / `---- done ----`, CRLF -- because a double
that hands back a bare or reshaped line cannot represent the input a live run
fails on (the L-1 lesson `charselect._reply_line` was written for).

**STAND-IN.** `MAIN_MENU_REPLY` is hand-written until the phase-0 live session
(ForgePact `docs/menu-layout-research.md`) captures the real reply, and must
then be replaced by it verbatim. What it rests on: the 2026-09-21 research
session's `menuprobe list UI_Button_obj` at `Main_Menu_rm` -- 13 instances,
`Play local` at GUI (448, 676.4), id 257029, sprite `Menu_Button_Kaelith_spr`,
visible, which C-1.15 mapped to client (336, 534) on a 1920x1080 windowed
client with a 2560x1368 GUI. That row's numbers are measured; every other
row's position, id, sprite and bbox is invented to give the parser something
realistic to walk (the texts and visibilities are the ones measured: six
visible buttons, seven hidden ones, two `Cosmetic Shop`).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import layout  # noqa: E402

FIXTURE_IS_STAND_IN = True

MAIN_MENU_REPLY = (
    "---- running command file ----\r\n"
    "menulayout: room=Main_Menu_rm gui=2560x1368 window=1920x1080 fullscreen=0 view=0.0,0.0,2560.0,1368.0\r\n"
    "  obj=UI_Button_obj id=257029 gui=448.0,676.4 win=336,534 bbox=260.0,640.0,636.0,712.0 visible=1 sprite=Menu_Button_Kaelith_spr text=Play local\r\n"
    "  obj=UI_Button_obj id=257030 gui=448.0,776.4 win=336,612 bbox=260.0,740.0,636.0,812.0 visible=1 sprite=Menu_Button_Kaelith_spr text=Play online\r\n"
    "  obj=UI_Button_obj id=257031 gui=448.0,876.4 win=336,691 bbox=260.0,840.0,636.0,912.0 visible=1 sprite=Menu_Button_Kaelith_spr text=Options\r\n"
    "  obj=UI_Button_obj id=257032 gui=448.0,976.4 win=336,770 bbox=260.0,940.0,636.0,1012.0 visible=1 sprite=Menu_Button_Kaelith_spr text=Cosmetic Shop\r\n"
    "  obj=UI_Button_obj id=257033 gui=2200.0,300.0 win=1650,237 bbox=2000.0,250.0,2400.0,350.0 visible=1 sprite=Menu_Button_Kaelith_spr text=Featured Cosmetics\r\n"
    "  obj=UI_Button_obj id=257034 gui=2200.0,1200.0 win=1650,947 bbox=2000.0,1160.0,2400.0,1240.0 visible=1 sprite=Menu_Button_Kaelith_spr text=Official Discord\r\n"
    "  obj=UI_Button_obj id=257035 gui=1280.0,200.0 win=960,158 bbox=1250.0,170.0,1310.0,230.0 visible=0 sprite=Menu_Button_Close_spr text=\r\n"
    "  obj=UI_Button_obj id=257036 gui=1280.0,684.0 win=960,540 bbox=1100.0,640.0,1460.0,728.0 visible=0 sprite=Menu_Button_Kaelith_spr text=Cosmetic Shop\r\n"
    "  obj=UI_Button_obj id=257037 gui=900.0,500.0 win=675,395 bbox=850.0,450.0,950.0,550.0 visible=0 sprite=Menu_Class_Tile_spr text=Play local\r\n"
    "  obj=UI_Button_obj id=257038 gui=1100.0,500.0 win=825,395 bbox=1050.0,450.0,1150.0,550.0 visible=0 sprite=Menu_Class_Tile_spr text=Class 2\r\n"
    "  obj=UI_Button_obj id=257039 gui=1300.0,500.0 win=975,395 bbox=1250.0,450.0,1350.0,550.0 visible=0 sprite=Menu_Class_Tile_spr text=Class 3\r\n"
    "  obj=UI_Button_obj id=257040 gui=1500.0,500.0 win=1125,395 bbox=1450.0,450.0,1550.0,550.0 visible=0 sprite=Menu_Class_Tile_spr text=Shop Tile 1\r\n"
    "  obj=UI_Button_obj id=257041 gui=1700.0,500.0 win=1275,395 bbox=1650.0,450.0,1750.0,550.0 visible=0 sprite=Menu_Class_Tile_spr text=Shop Tile 2\r\n"
    "  obj=Menu_Controller_obj id=100012 gui=0.0,0.0 win=0,0 bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none text=\r\n"
    "  obj=Profile_Manager_obj id=100013 gui=0.0,0.0 win=0,0 bbox=<read-failed>,<read-failed>,<read-failed>,<read-failed> visible=0 sprite=none text=\r\n"
    "menulayout: listed=15 absent=none capped=0\r\n"
    "---- done ----\r\n")

CLIENT_1080 = [1920, 1080]


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
        self.assertEqual(self.listing.view, (0.0, 0.0, 2560.0, 1368.0))

    def test_footer_fields(self):
        self.assertEqual(self.listing.listed, 15)
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
        self.assertEqual(row.bbox, (260.0, 640.0, 636.0, 712.0))
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
        self.assertEqual(self.rows[6].text, "")
        self.assertIs(self.rows[6].visible, False)

    def test_read_failed_is_none_never_zero(self):
        row = self.rows[-1]
        self.assertEqual(row.bbox, (None, None, None, None))
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
        # The fixture carries a hidden `UI_Button_obj` whose text is also
        # `Play local` (id 257037); it must never be the answer, and neither
        # may another object with the same text.
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


class FixtureTests(unittest.TestCase):
    def test_fixture_is_framed_and_crlf(self):
        self.assertTrue(MAIN_MENU_REPLY.startswith("---- running command file ----\r\n"))
        self.assertTrue(MAIN_MENU_REPLY.endswith("---- done ----\r\n"))
        self.assertNotIn("\n", MAIN_MENU_REPLY.replace("\r\n", ""))


if __name__ == "__main__":
    unittest.main()

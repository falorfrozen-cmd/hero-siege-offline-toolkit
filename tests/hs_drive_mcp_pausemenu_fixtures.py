"""Pause-menu `menulayout` listings for `hs_exit_to_menu`'s tests.

**One row is measured; the rest is written by hand.** ForgePact #201's Live
procedures 1 and 2 (2026-10-13, Live 1 cell C and Live 2 cell G) listed the
real pause menu: its Exit row is a `UI_Button_obj` whose text reads
`Save & Exit` and whose `uiNodeCallstack` is `PauseSaveExit`, at `win=1280,856`
on a 2560x1440 fullscreen client (`docs/RUNTIME_DATA_MODELS.md` § 8.4). The
`EXIT_ID` row below carries that measured text and callstack, so a text with
`&` and spaces goes through `layout.parse` the way the game's does. Its id and
point are invented (this fixture's window is 1920x1080), as are every other
row, id and point here. The rows are written in the plugin's reply
format (the same framing, CRLF and field order as the captured listings in
`hs_drive_mcp_menulayout_fixtures.py` and `hs_drive_mcp_stashlayout_fixtures.py`).
Also known: `UI_Pause_obj` exists only while the menu is open, each open builds
new `UI_Button_obj` rows, and Restart's `uiNodeCallstack` is `PauseRestart`
(§ 8.4, measured 2026-09-22).
"""

TOWN_ROOM = "Town_01_rm"
WINDOW = "1920x1080"

#: The Exit row's listed point, written here by hand so the tests assert the
#: number in the fixture rather than agree with the matcher.
EXIT_POINT = (960, 772)
EXIT_ID = 300108


def header(room: str = TOWN_ROOM, window: str = WINDOW) -> str:
    return (f"menulayout: room={room} gui=2560x1368 window={window} "
            "fullscreen=0 view=244.0,268.0,1280.0,720.0")


def footer(listed: int, capped: int = 0) -> str:
    return f"menulayout: listed={listed} absent=none capped={capped}"


def button(id_: int, win: tuple[int, int], text: str, callstack: str,
           visible: int = 1) -> str:
    x, y = win
    gx, gy = x * 4 / 3, y * 4 / 3
    return (f"  obj=UI_Button_obj id={id_} gui={gx:.1f},{gy:.1f} win={x},{y} "
            f"bbox={gx - 150:.1f},{gy - 40:.1f},{gx + 150:.1f},{gy + 40:.1f} "
            f"visible={visible} sprite=Menu_Button_Kaelith_spr "
            f"uiNodeCallstack={callstack} activationArgs=[] enabled=1 "
            f"text={text}")


def pause_row(id_: int = 300100) -> str:
    return (f"  obj=UI_Pause_obj id={id_} gui=0.0,0.0 win=0,0 "
            "bbox=0.0,0.0,0.0,0.0 visible=1 sprite=none text=")


def listing(rows: list[str], *, room: str = TOWN_ROOM, window: str = WINDOW,
            capped: int = 0) -> list[str]:
    """One `menulayout <Obj>` listing: header, rows, footer."""
    return [header(room, window), *rows, footer(len(rows), capped)]


def framed(*listings: list[str]) -> str:
    """One reply carrying the given listings, framed as every reply is."""
    lines = ["---- running command file ----"]
    for one in listings:
        lines.extend(one)
    lines.append("---- done ----")
    return "".join(line + "\r\n" for line in lines)


#: In the world, before Escape: two HUD buttons that stay listed whatever
#: menu opens. The second one's text contains "exit" on purpose: it is the
#: negative control, a row listed before the key, which must never be
#: clicked.
HUD_BUTTONS = [
    button(299001, (1800, 40), "Menu", "HudMenu"),
    button(299002, (1860, 40), "Exit Portal", "HudPortalExit"),
]

#: The pause menu's own buttons once it is open (new ids, the open's own).
PAUSE_BUTTONS = [
    button(300101, (960, 380), "Resume", "PauseResume"),
    button(300102, (960, 478), "Options", "PauseOptions"),
    button(300103, (960, 576), "Restart", "PauseRestart"),
    button(300104, (960, 674), "Join Discord", "PauseJoinDiscordExitLink"),
    # The measured row (2026-10-13, #201 Live 1 cell C and Live 2 cell G):
    # text and callstack as the game lists them; id and point invented.
    button(EXIT_ID, EXIT_POINT, "Save & Exit", "PauseSaveExit"),
]

#: A second row that also reads as an Exit row, for the ambiguity rule.
SECOND_EXIT = button(300109, (960, 870), "Exit Game", "PauseExitGame")

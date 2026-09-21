"""Read ForgePact's `menulayout` listing: where the menu buttons are.

`menulayout` is a read-only player command (ForgePact
`docs/menu-layout-research.md`, pinned by `tests/test_menu_layout_contract.py`
there) that lists every live main-menu and character-select button instance
with its object name, on-screen text and position in **window (client)
coordinates**, computed inside the game from its own GUI and window sizes.
This module parses one `ipc.send` reply of it and answers the questions
`hs_select_character` asks of each screen. It clicks nothing, sends nothing
and imports no MCP SDK; it is pure text in, values out.

The reply shape is the plugin's parse contract, framed the way every command
reply is (`---- running command file ----` / `---- done ----`, CRLF)::

    menulayout: room=<Room> gui=<W>x<H> window=<W>x<H> fullscreen=<0|1> view=<x>,<y>,<w>,<h>
      obj=<Obj> id=<id> gui=<x>,<y> win=<cx>,<cy> bbox=<l>,<t>,<r>,<b> visible=<0|1> sprite=<S|none>[ label=..][ name=..][ slot=..][ index=..][ page=..][ selected=..] text=<to end of line>
    menulayout: listed=<n> absent=<names|none> capped=<0|1>

`text=` is always the last field and runs to the end of the line, because a
button label may hold spaces, quotes and `=`. A field the plugin could not
read prints `<read-failed>`, which parses here as `None` -- never as a
plausible zero.

Two ways a reply is not a listing, both `layout_command_missing`: a player
build older than the command answers `command unavailable in player build:
menulayout`, and anything else with no `menulayout:` header is no listing
either. A listing whose `window=` differs from the client size this server
measured is `window_size_mismatch`: its `win` points were computed for a
different window, so none of them may be clicked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COMMAND = "menulayout"

HEADER_PREFIX = "menulayout: room="
FOOTER_PREFIX = "menulayout: listed="
ROW_PREFIX = "obj="
TEXT_FIELD = " text="
READ_FAILED = "<read-failed>"

#: What a player build that predates the command prints (`RunCommand`'s
#: allowlist refusal, `command unavailable in player build: <cmd>`).
UNAVAILABLE = "command unavailable in player build: menulayout"

#: Refusal tokens this module maps a reply to. `results.py` owns the
#: vocabulary; these name the two of its tokens a listing alone can decide.
LAYOUT_COMMAND_MISSING = "layout_command_missing"
WINDOW_SIZE_MISMATCH = "window_size_mismatch"

#: The `Play local` button: a `UI_Button_obj` identified by its text, which is
#: the identifier the research session measured (two `Cosmetic Shop` buttons
#: exist, so sprite and position are not).
PLAY_LOCAL_OBJECT = "UI_Button_obj"
PLAY_LOCAL_TEXT = "Play local"


@dataclass(frozen=True)
class Row:
    """One listed instance. Numbers the plugin could not read are `None`."""
    obj: str
    id: int | None
    gui: tuple[float | None, float | None]
    win: tuple[int | None, int | None]
    bbox: tuple[float | None, ...]
    visible: bool | None
    sprite: str
    text: str
    extra: dict[str, str] = field(default_factory=dict)
    line: str = ""

    def summary(self) -> dict[str, Any]:
        """The `obj/id/win/text` a caller records for the row it clicked."""
        return {"obj": self.obj, "id": self.id, "win": list(self.win),
                "text": self.text}


@dataclass(frozen=True)
class Listing:
    room: str
    gui: tuple[int | None, int | None]
    window: tuple[int | None, int | None]
    fullscreen: bool | None
    view: tuple[float | None, ...]
    rows: tuple[Row, ...]
    listed: int | None
    absent: tuple[str, ...]
    capped: bool | None
    header: str = ""


def reply_lines(result: dict[str, Any]) -> list[str]:
    """Every line of an `ipc.send` reply, stripped. `reply_lines` when the
    transport provided it, else `reply` split -- the same source
    `charselect._reply_line` reads, so both see one reply the same way."""
    lines = result.get("reply_lines")
    if lines is None:
        lines = (result.get("reply") or "").splitlines()
    return [raw.strip() for raw in lines]


def _fields(text: str) -> dict[str, str]:
    """`k=v` tokens separated by single spaces. A token with no `=` belongs
    to the previous value (an optional field whose value holds a space)."""
    out: dict[str, str] = {}
    last = None
    for token in text.split(" "):
        if not token:
            continue
        key, sep, value = token.partition("=")
        if sep and key:
            out[key] = value
            last = key
        elif last is not None:
            out[last] += " " + token
    return out


def _int(value: str | None) -> int | None:
    if value is None or value == READ_FAILED:
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return int(round(float(value)))
        except ValueError:
            return None


def _float(value: str | None) -> float | None:
    if value is None or value == READ_FAILED:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _flag(value: str | None) -> bool | None:
    return {"1": True, "0": False}.get(value or "")


def _pair(value: str | None, sep: str, convert) -> tuple:
    parts = (value or "").split(sep)
    if len(parts) != 2:
        return (None, None)
    return (convert(parts[0]), convert(parts[1]))


def parse_row(line: str) -> Row | None:
    """One `obj=...` row, or `None` if `line` is not one."""
    line = line.strip()
    if not line.startswith(ROW_PREFIX):
        return None
    idx = line.find(TEXT_FIELD)
    if idx < 0:
        return None
    head, text = line[:idx], line[idx + len(TEXT_FIELD):]
    fields = _fields(head)
    bbox = tuple(_float(v) for v in (fields.get("bbox") or "").split(","))
    known = {"obj", "id", "gui", "win", "bbox", "visible", "sprite"}
    return Row(
        obj=fields.get("obj", ""),
        id=_int(fields.get("id")),
        gui=_pair(fields.get("gui"), ",", _float),
        win=_pair(fields.get("win"), ",", _int),
        bbox=bbox if len(bbox) == 4 else (None, None, None, None),
        visible=_flag(fields.get("visible")),
        sprite=fields.get("sprite", ""),
        text=text,
        extra={k: v for k, v in fields.items() if k not in known},
        line=line,
    )


def parse(result: dict[str, Any]) -> Listing | None:
    """The listing in one `ipc.send` reply, or `None` when it has no
    `menulayout:` header (not a listing at all)."""
    lines = reply_lines(result)
    header_at = next((i for i, l in enumerate(lines)
                      if l.startswith(HEADER_PREFIX)), None)
    if header_at is None:
        return None
    header = lines[header_at]
    fields = _fields(header[len("menulayout: "):])
    rows: list[Row] = []
    footer: dict[str, str] = {}
    for line in lines[header_at + 1:]:
        if line.startswith(FOOTER_PREFIX):
            footer = _fields(line[len("menulayout: "):])
            break
        row = parse_row(line)
        if row is not None:
            rows.append(row)
    absent = footer.get("absent")
    return Listing(
        room=fields.get("room", ""),
        gui=_pair(fields.get("gui"), "x", _int),
        window=_pair(fields.get("window"), "x", _int),
        fullscreen=_flag(fields.get("fullscreen")),
        view=tuple(_float(v) for v in (fields.get("view") or "").split(",")),
        rows=tuple(rows),
        listed=_int(footer.get("listed")),
        absent=() if absent in (None, "none") else tuple(absent.split(",")),
        capped=_flag(footer.get("capped")),
        header=header,
    )


def _quote(result: dict[str, Any], limit: int = 400) -> str:
    text = (result.get("reply") or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def read(result: dict[str, Any],
         client_size: tuple[int, int] | list[int]) -> tuple[Listing | None, str, str]:
    """`(listing, "", "")` for a usable listing, else `(listing_or_None,
    reason, detail)`: `layout_command_missing` when the reply is not a
    listing, `window_size_mismatch` when its window is not this client."""
    lines = reply_lines(result)
    if any(l.startswith(UNAVAILABLE) for l in lines):
        return None, LAYOUT_COMMAND_MISSING, (
            f"the installed ForgePact plugin answered {UNAVAILABLE!r}: it "
            "predates the read-only `menulayout` command, so where the menu "
            "buttons are cannot be asked and nothing is clicked. Install a "
            "ForgePact build that has it.")
    listing = parse(result)
    if listing is None:
        return None, LAYOUT_COMMAND_MISSING, (
            f"`{COMMAND}` replied with no line starting {HEADER_PREFIX!r} "
            f"(raw reply: {_quote(result)!r}), so there is no listing to "
            "click from and nothing is clicked.")
    width, height = int(client_size[0]), int(client_size[1])
    if listing.window != (width, height):
        return listing, WINDOW_SIZE_MISMATCH, (
            f"the listing was computed for a {listing.window[0]}x"
            f"{listing.window[1]} window (header {listing.header!r}) but "
            f"this window's client area measures {width}x{height}, so its "
            "`win` points are for a different window and none is clicked.")
    return listing, "", ""


def visible_rows(listing: Listing, obj: str) -> list[Row]:
    return [row for row in listing.rows if row.obj == obj and row.visible]


def play_local_rows(listing: Listing) -> list[Row]:
    """Every visible `UI_Button_obj` whose text is exactly `Play local`."""
    return [row for row in visible_rows(listing, PLAY_LOCAL_OBJECT)
            if row.text == PLAY_LOCAL_TEXT]


def match_play_local(listing: Listing) -> Row | None:
    """The one `Play local` row with a readable `win` point, or `None` when
    there is none, or more than one (two candidates is not an answer)."""
    rows = [row for row in play_local_rows(listing)
            if None not in row.win]
    return rows[0] if len(rows) == 1 else None

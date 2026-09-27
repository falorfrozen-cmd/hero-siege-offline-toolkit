"""Read ForgePact's `menulayout` listing: where the menu buttons are.

`menulayout` is a read-only player command (ForgePact
`docs/menu-layout-research.md`, pinned by `tests/test_menu_layout_contract.py`
there) that lists every live instance of its candidate menu objects (and
the UI children they reach) with its object name, on-screen text and
position in **window (client) coordinates**, computed inside the game from
its own GUI and window sizes. This module parses one `ipc.send` reply of it
and answers the questions `hs_select_character` asks of each screen: which
row is `Play local`, which is save slot N, which is `PLAY`. It clicks
nothing, sends nothing and imports no MCP SDK; it is pure text in, values
out. The matchers are phase 0's Decision lines (ForgePact
`docs/menu-layout-research.md`), and the tests run them against the three
listings that session captured, verbatim.

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

from dataclasses import dataclass, field, replace
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

#: The room the save-slot cards and the character panel are both in.
SLOT_ROOM = "Chose_rm"

#: Phase 0's Decision (ForgePact `docs/menu-layout-research.md`, 2026-09-21,
#: recorded in `1553fbd`): `slotObject: Choose_Parent_obj`, `playObject: UI_Button_obj`,
#: both clicked at their listed origin (`point:origin`).
SLOT_OBJECT = "Choose_Parent_obj"
PLAY_OBJECT = "UI_Button_obj"
PLAY_TEXT = "Play"


#: The skill bar (toolkit #147, ForgePact `docs/skill-actions-research.md`):
#: its row is followed by one `  slot=<row>,<i> talent=<id|none>
#: gui=<x>,<y> win=<cx>,<cy>` line per element of its `row0` and `row1`
#: arrays, or one `  slot=<row>,* absent|empty|<read-failed>` line for an
#: array it could not list.
HUD_OBJECT = "UI_Hud_Talent_obj"
SLOT_PREFIX = "slot="

#: The stash and the bag (toolkit #147, ForgePact
#: `docs/stash-bag-layout-research.md` § Decision). A grid's row is followed
#: by one `  cell=<x>,<y> grid=<id> fp=<fingerprint|none> o=none` line per
#: occupied node (`cellRule`: a node carries its fingerprint and no count);
#: a grid past 200 occupied nodes carries `cellcap=1` on its own row.
GRID_OBJECT = "UI_Inventory_Grid_obj"
CELL_PREFIX = "cell="
STASH_OBJECT = "UI_Stash_obj"
STASH_TAB_OBJECT = "UI_Button_Stash_Tab_obj"
BAG_SUBTAB_OBJECT = "UI_Button_Inventory_Tab_Small_obj"
PLAYER_OBJECT = "Player_obj"
TOWN_STASH_OBJECT = "Town_Stash_obj"
#: `bagTabRule`: a bag sub-tab row is told apart by `uiNodeCallstack`.
BAG_MAIN_GRID = "InventoryGrid"


@dataclass(frozen=True)
class CellRow:
    """One occupied grid node. `fp` is `None` for `none` (a node with no
    fingerprint); `o` is always `None` - a node carries no count."""
    x: int | None
    y: int | None
    grid: int | None
    fp: str | None
    o: int | None
    line: str = ""


@dataclass(frozen=True)
class SlotRow:
    """One skill-bar slot line. `index` is `None` on a whole-array line
    (`slot=<row>,* ...`); `talent` is `None` for `none` or an unreadable
    id, never a plausible 0 -- an empty slot the game itself holds as 0
    reads 0."""
    row: int | None
    index: int | None
    talent: int | None
    gui: tuple[float | None, float | None]
    win: tuple[int | None, int | None]
    line: str = ""


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
    slots: tuple[SlotRow, ...] = ()
    cells: tuple[CellRow, ...] = ()

    def number(self, name: str) -> int | None:
        """An optional integer field (`tabNumber`, `stashTabSelected`,
        `tabSelected`, ...), or `None` when the row does not carry it or it
        is unreadable - never a plausible 0."""
        value = self.extra.get(name)
        return None if value is None else _int(value)

    @property
    def cellcap(self) -> bool:
        """True when the grid had more occupied nodes than its cell rows."""
        return self.extra.get("cellcap") == "1"

    @property
    def talent_id(self) -> int | None:
        """The row's own `talentId` field (the talent screen's buttons and
        sub-panel carry it), or `None` when it has none or it is unreadable."""
        value = self.extra.get("talentId")
        return None if value is None else _int(value)

    @property
    def name(self) -> str | None:
        """The row's `name` field (a talent button's display name), which may
        hold spaces; `None` when the row carries none."""
        return self.extra.get("name")

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


def parse_slot(line: str) -> SlotRow | None:
    """One `slot=<row>,<i> ...` line, or `None` if `line` is not one."""
    line = line.strip()
    if not line.startswith(SLOT_PREFIX):
        return None
    fields = _fields(line)
    where = (fields.get("slot") or "").split(",")
    if len(where) != 2:
        return None
    index = None if where[1] == "*" else _int(where[1])
    talent = fields.get("talent")
    return SlotRow(
        row=_int(where[0]),
        index=index,
        talent=None if talent in (None, "none") else _int(talent),
        gui=_pair(fields.get("gui"), ",", _float),
        win=_pair(fields.get("win"), ",", _int),
        line=line,
    )


def parse_cell(line: str) -> CellRow | None:
    """One `cell=<x>,<y> grid=<id> fp=<fp|none> o=none` line, or `None` if
    `line` is not one."""
    line = line.strip()
    if not line.startswith(CELL_PREFIX):
        return None
    fields = _fields(line)
    x, y = _pair(fields.get("cell"), ",", _int)
    fp = fields.get("fp")
    o = fields.get("o")
    return CellRow(x=x, y=y, grid=_int(fields.get("grid")),
                   fp=None if fp in (None, "none", READ_FAILED) else fp,
                   o=None if o in (None, "none") else _int(o), line=line)


def _parse_from(lines: list[str], header_at: int) -> tuple[Listing, int]:
    """The listing whose header is `lines[header_at]`, and the index of the
    line after its footer (or `len(lines)` when it has none). A `slot=` line
    belongs to the skill-bar row above it, a `cell=` line to the grid row
    above it, and to no other row."""
    header = lines[header_at]
    fields = _fields(header[len("menulayout: "):])
    rows: list[Row] = []
    slots: list[SlotRow] = []
    cells: list[CellRow] = []
    footer: dict[str, str] = {}

    def close_row() -> None:
        if rows and (slots or cells):
            rows[-1] = replace(rows[-1], slots=tuple(slots), cells=tuple(cells))
        slots.clear()
        cells.clear()

    end = len(lines)
    for i in range(header_at + 1, len(lines)):
        line = lines[i]
        if line.startswith(FOOTER_PREFIX):
            footer = _fields(line[len("menulayout: "):])
            end = i + 1
            break
        if line.startswith(HEADER_PREFIX):
            end = i   # a listing with no footer ends where the next begins
            break
        slot = parse_slot(line)
        if slot is not None:
            if rows and rows[-1].obj == HUD_OBJECT:
                slots.append(slot)
            continue
        cell = parse_cell(line)
        if cell is not None:
            if rows and rows[-1].obj == GRID_OBJECT:
                cells.append(cell)
            continue
        row = parse_row(line)
        if row is not None:
            close_row()
            rows.append(row)
    close_row()
    absent = footer.get("absent")
    return _listing(fields, rows, footer, absent, header), end


def parse(result: dict[str, Any]) -> Listing | None:
    """The first listing in one `ipc.send` reply, or `None` when it has no
    `menulayout:` header (not a listing at all)."""
    lines = reply_lines(result)
    header_at = next((i for i, l in enumerate(lines)
                      if l.startswith(HEADER_PREFIX)), None)
    if header_at is None:
        return None
    return _parse_from(lines, header_at)[0]


def parse_all(result: dict[str, Any]) -> list[Listing]:
    """Every listing in one reply, in order: one `hs_command` send carrying
    several `menulayout <Obj>` lines answers with one listing per line
    (empty for an object with no instance). `[]` when there is none."""
    lines = reply_lines(result)
    out: list[Listing] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith(HEADER_PREFIX):
            listing, i = _parse_from(lines, i)
            out.append(listing)
        else:
            i += 1
    return out


def _listing(fields: dict[str, str], rows: list[Row], footer: dict[str, str],
             absent: str | None, header: str) -> Listing:
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


def slot_rows(listing: Listing) -> list[Row]:
    """The save-slot cards, in slot order: every visible `Choose_Parent_obj`
    with a readable `win` point, sorted by `win` y then `win` x.

    Row-major (the owner's rule, D12): slot 1 is the top-left card, slot 2
    the card to its right on the same row, and the next row starts after
    the last card of this one. Phase 0 checked the game's own `slot`
    variable against this order on all 24 page-1 cards and they agreed.
    `visible=1` is not optional: the same screen lists a second, hidden
    `Choose_Parent_obj` at every card's point (`slot` 25-48 at phase 0), and
    counting those would double every card."""
    rows = [row for row in visible_rows(listing, SLOT_OBJECT)
            if None not in row.win]
    return sorted(rows, key=lambda row: (row.win[1], row.win[0]))


def match_slot(listing: Listing, slot: int) -> Row | None:
    """Card `slot` (1-based, row-major), or `None` when fewer are listed."""
    rows = slot_rows(listing)
    return rows[slot - 1] if 1 <= slot <= len(rows) else None


def play_rows(listing: Listing) -> list[Row]:
    """Every visible `UI_Button_obj` whose text is exactly `Play` -- not
    `Play local`, and case-sensitive -- with a readable `win` point."""
    return [row for row in visible_rows(listing, PLAY_OBJECT)
            if row.text == PLAY_TEXT and None not in row.win]


def match_play(listing: Listing) -> Row | None:
    """The character panel's one `PLAY` row, or `None` when there is none or
    more than one. The row does not exist until a card has been clicked
    (phase 0), so a caller polls for it rather than reading once."""
    rows = play_rows(listing)
    return rows[0] if len(rows) == 1 else None


def rows_with_talent(listing: Listing, obj: str, talent_id: int) -> list[Row]:
    """Every `obj` row whose own `talentId` is `talent_id` -- how the talent
    screen's button for one talent is told from the others (live 2 of the
    skill research: the rows carry no other identifying field)."""
    return [row for row in listing.rows
            if row.obj == obj and row.talent_id == talent_id]


def describe(listing: Listing, obj: str, limit: int = 30) -> str:
    """A refusal's quote of a listing: its header, how many rows it carried,
    and the visible `obj` rows it offered (text and `win`), so a caller can
    see what was there instead of the button it was looking for."""
    rows = visible_rows(listing, obj)
    shown = "; ".join(f"{row.text!r} win={row.win[0]},{row.win[1]}"
                      for row in rows[:limit])
    more = f" (+{len(rows) - limit} more)" if len(rows) > limit else ""
    return (f"{listing.header!r}, {len(listing.rows)} row(s), "
            f"{len(rows)} visible {obj}: [{shown}]{more}")


# --------------------------------------------------------------------------
# The stash and the bag (hs-drive-stash-bag-actions)
#
# Each matcher answers exactly one row or None: two candidates are not an
# answer. They take every listing of one reply (`parse_all`), since a stash
# tool sends one `menulayout <Obj>` line per object it reads.
# --------------------------------------------------------------------------

def _rows(listings: Listing | list[Listing], obj: str) -> list[Row]:
    if isinstance(listings, Listing):
        listings = [listings]
    return [row for listing in listings for row in listing.rows if row.obj == obj]


def _one(rows: list[Row]) -> Row | None:
    return rows[0] if len(rows) == 1 else None


def match_stash_window(listings: Listing | list[Listing]) -> Row | None:
    """The one `UI_Stash_obj` row: the open stash window, whose
    `stashTabSelected` is the stash tab on show and `tabSelected` the bag
    sub-tab beside it (`stashTabState`, `bagTabState`)."""
    return _one(_rows(listings, STASH_OBJECT))


def match_player(listings: Listing | list[Listing]) -> Row | None:
    """The one `Player_obj` row; its `gui=` is a room position."""
    return _one(_rows(listings, PLAYER_OBJECT))


def match_town_stash(listings: Listing | list[Listing]) -> Row | None:
    """The one `Town_Stash_obj` row; its `gui=` is a room position."""
    return _one(_rows(listings, TOWN_STASH_OBJECT))


def match_bag_grid(listings: Listing | list[Listing]) -> Row | None:
    """The bag's main grid: the one `UI_Inventory_Grid_obj` whose
    `uiNodeCallstack` is `InventoryGrid` (the bag panel of whichever window
    shows it)."""
    return _one([row for row in _rows(listings, GRID_OBJECT)
                 if row.extra.get("uiNodeCallstack") == BAG_MAIN_GRID])


def match_stash_tab(listings: Listing | list[Listing], tab_number: int) -> Row | None:
    """The one `UI_Button_Stash_Tab_obj` whose `tabNumber` is `tab_number`
    (`stashTabRule`) - never its text or position."""
    return _one([row for row in _rows(listings, STASH_TAB_OBJECT)
                 if row.number("tabNumber") == tab_number])


def match_bag_subtab(listings: Listing | list[Listing], callstack: str) -> Row | None:
    """The one `UI_Button_Inventory_Tab_Small_obj` whose `uiNodeCallstack` is
    `callstack` (`bagTabRule`); its `text` is empty and it has no
    `tabNumber`."""
    return _one([row for row in _rows(listings, BAG_SUBTAB_OBJECT)
                 if row.extra.get("uiNodeCallstack") == callstack])


def cells_holding(listings: Listing | list[Listing], fp: str) -> list[CellRow]:
    """Every cell row, in every grid, whose fingerprint is `fp` - one per
    cell an item covers (`itemRule: fingerprint`)."""
    return [cell for row in _rows(listings, GRID_OBJECT) for cell in row.cells if cell.fp == fp]


def match_item_grid(listings: Listing | list[Listing], fp: str) -> Row | None:
    """The one grid row whose cells hold `fp`, or None when no grid does or
    more than one does."""
    return _one([row for row in _rows(listings, GRID_OBJECT)
                 if any(cell.fp == fp for cell in row.cells)])


def free_cells(row: Row) -> int | None:
    """How many of a grid's nodes hold nothing: its `nodeGridWidth` x
    `nodeGridHeight` less its cell rows. None when either size is unreadable
    or the grid was past the cell cap (its rows are then not all of them)."""
    width, height = row.number("nodeGridWidth"), row.number("nodeGridHeight")
    if width is None or height is None or row.cellcap:
        return None
    return width * height - len(row.cells)


# --------------------------------------------------------------------------
# The player verbs' reply lines
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class VerbReply:
    """What one `playerwarp`/`stashtab`/`bagtab`/`stashclose`/`giveitem`
    send printed: every line beginning `<verb>: `, the `before=`/`after=`
    line's fields (`before`, `after` and whatever else it carries - `key`,
    `o`, `handler`, `activeNode_before`, ...), and the refusal, confirmed and
    not-confirmed texts after their prefixes."""
    verb: str
    lines: tuple[str, ...]
    fields: dict[str, str]
    refused: str | None
    confirmed: str | None
    not_confirmed: str | None
    unavailable: bool

    @property
    def before(self) -> str | None:
        return self.fields.get("before")

    @property
    def after(self) -> str | None:
        return self.fields.get("after")


def parse_verb(result: dict[str, Any], verb: str) -> VerbReply:
    """The `<verb>: ...` lines of one reply. `unavailable` when the player
    build predates the verb (`command unavailable in player build: <verb>`).
    A reply with no line of the verb's own carries no fields and no verdict,
    which a caller reads as "the verb said nothing", never as a pass."""
    lines = reply_lines(result)
    tag = verb + ": "
    own = tuple(l for l in lines if l.startswith(tag))
    fields: dict[str, str] = {}
    refused = confirmed = not_confirmed = None
    for line in own:
        body = line[len(tag):]
        if body.startswith("refused - "):
            refused = refused or body[len("refused - "):]
        elif body.startswith("confirmed - "):
            confirmed = body[len("confirmed - "):]
        elif body.startswith("not confirmed - "):
            not_confirmed = body[len("not confirmed - "):]
        elif " before=" in " " + body and " after=" in body:
            fields = _fields(body)
    unavailable = any(l == f"command unavailable in player build: {verb}" for l in lines)
    return VerbReply(verb, own, fields, refused, confirmed, not_confirmed, unavailable)

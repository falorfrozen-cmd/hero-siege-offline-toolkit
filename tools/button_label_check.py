#!/usr/bin/env python3
"""button_label_check.py -- where a button's label is drawn, measured on a screenshot.

ForgePact #131's Live 4 passed every numeric check on the Move all button - its
box, its size, its sprite read back by name - while the screenshot showed its
`Move all` label drawn at the box's top-left corner and clipped. No member the
mod can read says where the game draws a node's `text`, so the picture is the
only instrument. This tool measures it.

Given a screenshot, the GUI size (`menulayout`'s header `gui=WxH`) and two
GUI-unit boxes - `--box`, the button under test, and `--ref`, a button the game
draws itself (the backpack's Sort Tab, `InventorySort`) - it:

- maps each box onto the image (image size over GUI size per axis; a GUI box's
  right and bottom are inclusive, as `bbox_right`/`bbox_bottom` are), refusing
  when the two aspects differ by more than 1 %;
- takes as label pixels those whose luminance is above the box's median
  luminance by more than 60 (the label is drawn light on the button's face);
- reports per box the label pixel count, the label's bounding box (image px and
  GUI units), its centre's offset from the box's centre in image px, and the
  mean colour of the label and of the box.

A box is `centred` when both offsets are within 4 px, the label's bounding box
lies at least 2 px inside the box on every side, and its pixel count is at
least 40 % of the reference's. The reference must itself be centred, or the
tool has proved nothing about the box.

Exit codes:
    0  the box and the reference are both centred
    1  the reference is centred and the box is not
    2  the reference is not centred (the instrument proved nothing), a usage
       error, an unreadable image, Pillow missing, or an aspect mismatch

Usage:
    py -3 tools/button_label_check.py <png> --gui 2560x1440 \\
        --box 2090,1262,2282,1328 --ref 2290,1262,2482,1328

Take the screenshot with hs-drive's `hs_screenshot` `target="game"`,
`method="grab_window"`: its pixels are the game window's client area, which is
what the GUI maps onto. docs/tools/button-label-check.md has the calibration on
Live 4's own screenshot. Read-only: the image is opened for reading and nothing
is written.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

LUMA_ABOVE_MEDIAN = 60      # a label pixel is this much brighter than the box's median
OFFSET_PX = 4.0             # the label centre's largest offset from the box centre, per axis
INSET_PX = 2                # the label's bounding box lies at least this far inside the box
MIN_SHARE_OF_REF = 0.40     # the label's pixel count against the reference's
ASPECT_TOLERANCE = 0.01     # image aspect against the GUI's


class UsageError(Exception):
    pass


@dataclass
class Measure:
    name: str
    gui: tuple[float, float, float, float]
    px: tuple[int, int, int, int]          # inclusive image rectangle
    count: int = 0
    label: tuple[int, int, int, int] | None = None   # inclusive, image px
    offset: tuple[float, float] | None = None
    label_rgb: tuple[int, int, int] | None = None
    box_rgb: tuple[int, int, int] = (0, 0, 0)
    median: float = 0.0
    reasons: tuple[str, ...] = ()

    @property
    def centred(self) -> bool:
        return not self.reasons


def parse_gui(text: str) -> tuple[int, int]:
    parts = text.lower().split("x")
    try:
        w, h = (int(p) for p in parts)
    except ValueError:
        raise UsageError(f"--gui wants WxH (menulayout's header gui=WxH), got {text!r}") from None
    if w <= 0 or h <= 0:
        raise UsageError(f"--gui wants a positive size, got {text!r}")
    return w, h


def parse_box(text: str, flag: str) -> tuple[float, float, float, float]:
    try:
        vals = tuple(float(v) for v in text.split(","))
    except ValueError:
        raise UsageError(f"{flag} wants left,top,right,bottom in GUI units, got {text!r}") from None
    if len(vals) != 4:
        raise UsageError(f"{flag} wants four numbers left,top,right,bottom, got {text!r}")
    l, t, r, b = vals
    if r <= l or b <= t:
        raise UsageError(f"{flag} is empty or inverted: {text!r}")
    return vals


def measure(img, luma, name, gui_box, sx, sy) -> Measure:
    """The label pixels inside one box (GUI units), before the reference is known."""
    l, t, r, b = gui_box
    px = (round(l * sx), round(t * sy), round(r * sx), round(b * sy))
    w, h = img.size
    L, T = max(px[0], 0), max(px[1], 0)
    R, B = min(px[2], w - 1), min(px[3], h - 1)
    m = Measure(name=name, gui=gui_box, px=px)
    if R < L or B < T:
        m.reasons = ("outside-image",)
        return m
    # Raw bytes rather than getdata(), which Pillow 12 deprecates.
    lum = luma.crop((L, T, R + 1, B + 1)).tobytes()
    raw = img.crop((L, T, R + 1, B + 1)).tobytes()
    rgb = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    m.median = float(sorted(lum)[len(lum) // 2])
    m.box_rgb = tuple(round(sum(c[i] for c in rgb) / len(rgb)) for i in range(3))
    cw = R - L + 1
    xs, ys, hits = [], [], []
    for i, v in enumerate(lum):
        if v > m.median + LUMA_ABOVE_MEDIAN:
            xs.append(L + i % cw)
            ys.append(T + i // cw)
            hits.append(rgb[i])
    m.count = len(hits)
    if hits:
        m.label = (min(xs), min(ys), max(xs), max(ys))
        m.label_rgb = tuple(round(sum(c[i] for c in hits) / len(hits)) for i in range(3))
        m.offset = ((m.label[0] + m.label[2]) / 2 - (px[0] + px[2]) / 2,
                    (m.label[1] + m.label[3]) / 2 - (px[1] + px[3]) / 2)
    return m


def judge(m: Measure, ref_count: int) -> None:
    """Fill in why a box is not centred (none: centred)."""
    if m.reasons:
        return
    reasons = []
    if not m.count:
        reasons.append("no-label")
    else:
        if abs(m.offset[0]) > OFFSET_PX or abs(m.offset[1]) > OFFSET_PX:
            reasons.append("offset")
        l, t, r, b = m.px
        ll, lt, lr, lb = m.label
        if ll < l + INSET_PX or lt < t + INSET_PX or lr > r - INSET_PX or lb > b - INSET_PX:
            reasons.append("edge")
        if ref_count <= 0 or m.count < MIN_SHARE_OF_REF * ref_count:
            reasons.append("pixels")
    m.reasons = tuple(reasons)


def line(m: Measure, sx: float, sy: float, ref_count: int) -> str:
    verdict = "centred" if m.centred else "not centred (" + ",".join(m.reasons) + ")"
    gui = ",".join(f"{v:g}" for v in m.gui)
    px = ",".join(str(v) for v in m.px)
    text = f"{m.name}: {verdict} gui={gui} px={px} label_px={m.count}"
    if ref_count > 0:
        text += f" share={m.count / ref_count:.2f}"
    if m.label:
        lb = ",".join(str(v) for v in m.label)
        gl = f"{m.label[0] / sx:g},{m.label[1] / sy:g},{m.label[2] / sx:g},{m.label[3] / sy:g}"
        text += (f" label_box={lb} label_box_gui={gl} offset={m.offset[0]:.1f},{m.offset[1]:.1f}"
                 f" label_rgb={','.join(str(c) for c in m.label_rgb)}")
    else:
        text += " label_box=none offset=none label_rgb=none"
    text += f" box_rgb={','.join(str(c) for c in m.box_rgb)} median_luma={m.median:g}"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="button_label_check.py",
        description="Whether a button's label is drawn centred inside its box, measured on a screenshot "
                    "against a reference button the game draws itself.")
    parser.add_argument("png", help="the screenshot (hs_screenshot target=game method=grab_window)")
    parser.add_argument("--gui", required=True, help="the GUI size WxH (menulayout's header gui=)")
    parser.add_argument("--box", required=True, help="the button under test: left,top,right,bottom in GUI units")
    parser.add_argument("--ref", required=True, help="a game-drawn button: left,top,right,bottom in GUI units")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:   # argparse's own usage error
        return 2 if exc.code else 0
    try:
        gw, gh = parse_gui(args.gui)
        box = parse_box(args.box, "--box")
        ref = parse_box(args.ref, "--ref")
    except UsageError as exc:
        print(f"button_label_check: usage - {exc}", file=sys.stderr)
        return 2
    try:
        from PIL import Image
    except ImportError:
        print("button_label_check: Pillow is not installed (pip install -r tools/hs_drive_mcp/requirements.txt)",
              file=sys.stderr)
        return 2
    try:
        with Image.open(args.png) as opened:
            img = opened.convert("RGB")
    except (OSError, ValueError) as exc:
        print(f"button_label_check: cannot read {args.png}: {exc}", file=sys.stderr)
        return 2
    w, h = img.size
    sx, sy = w / gw, h / gh
    print(f"button_label_check: {args.png} image={w}x{h} gui={gw}x{gh} scale={sx:.3f},{sy:.3f}")
    if abs(sx / sy - 1.0) > ASPECT_TOLERANCE:
        print(f"button_label_check: aspect mismatch - the image is {w}x{h} and the GUI {gw}x{gh} "
              f"(x scale {sx:.3f} against y scale {sy:.3f}); take the screenshot with method=grab_window")
        return 2
    luma = img.convert("L")
    r = measure(img, luma, "ref", ref, sx, sy)
    b = measure(img, luma, "box", box, sx, sy)
    judge(r, r.count)
    judge(b, r.count)
    print(line(b, sx, sy, r.count))
    print(line(r, sx, sy, r.count))
    if not r.centred:
        print("button_label_check: the reference is not centred, so this says nothing about the box (exit 2)")
        return 2
    if not b.centred:
        print("button_label_check: the box's label is not centred (exit 1)")
        return 1
    print("button_label_check: the box's label is centred like the reference's (exit 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

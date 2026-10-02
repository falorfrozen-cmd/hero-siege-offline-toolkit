"""tools/button_label_check.py: where a button's label is drawn, from a screenshot.

ForgePact #131's Live 4 passed every numeric check while the Move all
button's label was drawn at the box's top-left corner and clipped: no member
the mod can read says where the game draws a node's `text`, so the only
instrument is the picture. The tool maps two GUI-unit boxes onto a screenshot
(`--box` under test, `--ref` a game-drawn button such as InventorySort) and
calls a box's label `centred` when the bright pixels inside it sit on its
centre, inside its edges, and are not a sliver of the reference's.

Every case draws a synthetic PNG with Pillow into a temp directory: a dark
button face with a bright block standing in for the label text. The baseline
is Live 4's own geometry (the node's label at its top-left corner beside a
centred reference), which must fail; the target is a centred label, which must
pass. The reference is the instrument's positive control: a reference with no
label proves nothing and exits 2, as do a usage error and a screenshot whose
aspect is not the GUI's. A GUI-to-image scale of 2 checks the box mapping.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from PIL import Image, ImageDraw  # noqa: F401
    PILLOW = True
except ImportError:  # pragma: no cover - the criterion forbids the skip on the dev machine
    PILLOW = False

if PILLOW:
    from tools import button_label_check  # noqa: E402

# Live 4 (ForgePact docs/stash-move-research.md § Live 4 results): the node's
# box and the backpack's Sort Tab (InventorySort), GUI 2560x1440.
NODE = (2090, 1262, 2282, 1328)
SORT = (2290, 1262, 2482, 1328)
GUI = (2560, 1440)
FACE = (38, 34, 30)      # the dark framed face both buttons are drawn with
TEXT = (230, 220, 200)   # the label's colour


def _box_text(box):
    return ",".join(f"{v:.1f}" for v in box)


def _label(draw, box, scale=1.0, width=40, height=10, dx=0, dy=0):
    """A bright block of width x height (image px) centred on box (GUI units), moved by dx, dy."""
    l, t, r, b = (v * scale for v in box)
    cx, cy = (l + r) / 2 + dx, (t + b) / 2 + dy
    draw.rectangle([round(cx - width / 2), round(cy - height / 2),
                    round(cx + width / 2) - 1, round(cy + height / 2) - 1], fill=TEXT)


@unittest.skipUnless(PILLOW, "Pillow is not installed (pip install -r tools/hs_drive_mcp/requirements.txt)")
class ButtonLabelCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def picture(self, size=GUI, scale=1.0, boxes=(NODE, SORT)):
        img = Image.new("RGB", size, (8, 8, 10))
        draw = ImageDraw.Draw(img)
        for box in boxes:
            draw.rectangle([round(v * scale) for v in (box[0], box[1])]
                           + [round(box[2] * scale) - 1, round(box[3] * scale) - 1], fill=FACE)
        return img, draw

    def run_tool(self, img, gui=GUI, box=NODE, ref=SORT, extra=()):
        path = self.dir / "shot.png"
        img.save(path)
        argv = [str(path), "--gui", f"{gui[0]}x{gui[1]}", "--box", _box_text(box), "--ref", _box_text(ref), *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = button_label_check.main(argv)
        return code, out.getvalue()

    @staticmethod
    def line(out, prefix):
        return next(l for l in out.splitlines() if l.startswith(prefix))

    # ---- baseline: Live 4's defect ---------------------------------------------

    def test_live4_geometry_fails_the_box_and_passes_the_reference(self):
        img, draw = self.picture()
        _label(draw, SORT, width=60, height=12)
        # The node's label as Live 4 drew it: 2096..2138 x 1262..1270, the box's corner.
        draw.rectangle([2096, 1262, 2138, 1270], fill=TEXT)
        code, out = self.run_tool(img)
        self.assertEqual(code, 1, out)
        self.assertTrue(self.line(out, "ref:").startswith("ref: centred"), out)
        box = self.line(out, "box:")
        self.assertTrue(box.startswith("box: not centred"), out)
        self.assertIn("offset=-69.0,-29.0", box)
        self.assertIn("label_box=2096,1262,2138,1270", box)
        self.assertIn("edge", box)   # it touches the box's top edge

    # ---- target: a centred label -----------------------------------------------

    def test_centred_label_passes(self):
        img, draw = self.picture()
        _label(draw, SORT, width=60, height=12)
        _label(draw, NODE, width=56, height=12)
        code, out = self.run_tool(img)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.line(out, "box:").startswith("box: centred"), out)
        self.assertTrue(self.line(out, "ref:").startswith("ref: centred"), out)
        self.assertIn("label_rgb=230,220,200", self.line(out, "box:"))

    def test_a_label_a_few_px_off_centre_still_passes_and_one_further_does_not(self):
        img, draw = self.picture()
        _label(draw, SORT, width=60, height=12)
        _label(draw, NODE, width=56, height=12, dx=3, dy=-3)
        self.assertEqual(self.run_tool(img)[0], 0)
        img, draw = self.picture()
        _label(draw, SORT, width=60, height=12)
        _label(draw, NODE, width=56, height=12, dx=6)
        code, out = self.run_tool(img)
        self.assertEqual(code, 1, out)
        self.assertIn("offset=5.5,-0.5", self.line(out, "box:"))

    def test_a_centred_sliver_is_not_a_label(self):
        # Centred, inside the edges, but under 40 % of the reference's pixels.
        img, draw = self.picture()
        _label(draw, SORT, width=60, height=12)
        _label(draw, NODE, width=10, height=8)
        code, out = self.run_tool(img)
        self.assertEqual(code, 1, out)
        self.assertIn("pixels", self.line(out, "box:"))

    # ---- the instrument proves nothing: exit 2 --------------------------------

    def test_a_reference_with_no_label_exits_2(self):
        img, draw = self.picture()
        _label(draw, NODE, width=56, height=12)
        code, out = self.run_tool(img)
        self.assertEqual(code, 2, out)
        self.assertTrue(self.line(out, "ref:").startswith("ref: not centred"), out)

    def test_a_reference_with_an_off_centre_label_exits_2(self):
        # The reference draws a label, but off-centre: the tool's own rule is
        # wrong for this picture, so even a centred box proves nothing.
        img, draw = self.picture()
        _label(draw, SORT, width=60, height=12, dx=20)
        _label(draw, NODE, width=56, height=12)
        code, out = self.run_tool(img)
        self.assertEqual(code, 2, out)
        self.assertTrue(self.line(out, "ref:").startswith("ref: not centred"), out)
        # And one touching the reference box's edge.
        img, draw = self.picture()
        draw.rectangle([SORT[0], SORT[1], SORT[0] + 60, SORT[1] + 11], fill=TEXT)
        _label(draw, NODE, width=56, height=12)
        code, out = self.run_tool(img)
        self.assertEqual(code, 2, out)
        self.assertTrue(self.line(out, "ref:").startswith("ref: not centred"), out)

    def test_an_aspect_mismatch_exits_2(self):
        img, draw = self.picture()
        _label(draw, SORT, width=60, height=12)
        _label(draw, NODE, width=56, height=12)
        code, out = self.run_tool(img, gui=(2560, 1600))
        self.assertEqual(code, 2, out)
        self.assertIn("aspect", out)
        self.assertNotIn("box:", out)

    def test_a_usage_error_exits_2(self):
        img, _ = self.picture()
        path = self.dir / "shot.png"
        img.save(path)
        for argv in ([str(path), "--gui", "2560", "--box", _box_text(NODE), "--ref", _box_text(SORT)],
                     [str(path), "--gui", "2560x1440", "--box", "1,2,3", "--ref", _box_text(SORT)],
                     [str(path), "--gui", "2560x1440", "--box", "5,5,1,1", "--ref", _box_text(SORT)],
                     [str(self.dir / "missing.png"), "--gui", "2560x1440", "--box", _box_text(NODE),
                      "--ref", _box_text(SORT)]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = button_label_check.main(argv)
            self.assertEqual(code, 2, (argv, out.getvalue()))

    # ---- the GUI-to-image mapping ---------------------------------------------

    def test_a_scale_of_2_maps_the_boxes(self):
        gui = (1280, 720)
        node = tuple(v / 2 for v in NODE)
        sort = tuple(v / 2 for v in SORT)
        img, draw = self.picture(size=GUI, scale=2.0, boxes=(node, sort))
        _label(draw, sort, scale=2.0, width=60, height=12)
        _label(draw, node, scale=2.0, width=56, height=12)
        code, out = self.run_tool(img, gui=gui, box=node, ref=sort)
        self.assertEqual(code, 0, out)
        self.assertIn("scale=2.000,2.000", out)
        self.assertIn("px=2090,1262,2282,1328", self.line(out, "box:"))
        # Negative control: the same label drawn where scale 1 would put it
        # (the top-left quarter of the box's image rectangle) is not centred.
        img, draw = self.picture(size=GUI, scale=2.0, boxes=(node, sort))
        _label(draw, sort, scale=2.0, width=60, height=12)
        _label(draw, node, scale=1.0, width=56, height=12)
        self.assertEqual(self.run_tool(img, gui=gui, box=node, ref=sort)[0], 1)


if __name__ == "__main__":
    unittest.main()

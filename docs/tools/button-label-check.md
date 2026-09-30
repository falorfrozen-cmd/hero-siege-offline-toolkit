# `button_label_check.py` — where a button's label is drawn, from a screenshot

`tools/button_label_check.py` measures whether a button's label is drawn
centred inside the button's box, on a screenshot of the game. It exists for
ForgePact #131. In Live 4 the in-game **Move all** button passed every numeric
check (its box, its size, its sprite read back by name), while the screenshot
showed its `Move all` label drawn at the box's top-left corner and clipped. No
member the mod can read says where the game draws a node's `text`, so the
picture is the only instrument, and this tool reads it.

Nothing here ships to a player. It is a script under `tools/`, the way
`stash_tab_counts.py` and `source_index.py` are, and ForgePact never runs or
imports it. It needs Pillow, which `tools/hs_drive_mcp/requirements.txt`
already pins.

## Usage

```powershell
py -3 tools/button_label_check.py <png> --gui 2560x1440 `
    --box 2090,1262,2282,1328 --ref 2290,1262,2482,1328
```

- `<png>`: the screenshot. Take it with hs-drive's `hs_screenshot`
  `target="game"`, `method="grab_window"`. Its pixels are the game window's
  client area, which is what the GUI maps onto (hs-drive guide § Screenshots).
  The default `grab_bbox` capture is the window's screen rectangle, frame
  included, and only matched the GUI in Live 4 by chance.
- `--gui WxH`: the GUI size, from `menulayout`'s header `gui=WxH`.
- `--box l,t,r,b`: the button under test, in GUI units, as `menulayout` prints
  its `bbox=` (the mod's `ForgePactMoveAll` node).
- `--ref l,t,r,b`: a button the game draws itself, in GUI units. For the Move
  all button this is the backpack's **Sort Tab** (`InventorySort`), whose look
  the node copies. The reference is the tool's positive control.

## The rule

Each box is mapped onto the image by the image size over the GUI size, per
axis. A GUI box's right and bottom are inclusive, as `bbox_right` and
`bbox_bottom` are. When the two scales differ by more than 1 %, the screenshot
is not of the GUI, and the tool refuses.

Inside each box, a **label pixel** is one whose luminance is more than 60
above the box's median luminance. The label is drawn light on the button's
dark face, so the median is the face. For each box the tool reports the label
pixel count, the label's bounding box (image pixels and GUI units), the offset
of that bounding box's centre from the box's centre in image pixels, and the
mean colour of the label and of the box.

A box is **`centred`** when all three hold:

- both offsets are within 4 px;
- the label's bounding box lies at least 2 px inside the box on every side (a
  label cut off by the box's edge touches it);
- its pixel count is at least 40 % of the reference's (a speck in the middle
  is not a label).

A box that fails says which of these it failed: `offset`, `edge`, `pixels`,
or `no-label`.

## Output and exit codes

```text
button_label_check: <png> image=2560x1440 gui=2560x1440 scale=1.000,1.000
box: not centred (offset,edge,pixels) gui=... px=... label_px=175 share=0.32 label_box=... label_box_gui=... offset=-69.0,-29.0 label_rgb=... box_rgb=... median_luma=20
ref: centred gui=... px=... label_px=548 share=1.00 label_box=... offset=-0.5,-1.0 ...
button_label_check: the box's label is not centred (exit 1)
```

| Exit | Meaning |
| --- | --- |
| 0 | the box and the reference are both centred |
| 1 | the reference is centred and the box is not |
| exit 2 | the reference is not centred, so the tool proved nothing about the box; or a usage error, an unreadable image, Pillow missing, or an aspect mismatch |

A live procedure reads the `ref:` line first. A reference that is not centred
is the instrument failing, never a verdict on the button.

## Calibration: Live 4's screenshot

Run on Live 4's step 3 screenshot (`20260930T162809916688Z_live2-button-placed.png`,
2560x1440 at GUI 2560x1440, on the owner's machine), with the node's box
2090,1262,2282,1328 and InventorySort's 2290,1262,2482,1328 from the same
session's `menulayout`:

- **ref** (InventorySort's `Sort Tab`): centred, 548 label pixels, label box
  2338,1286,2433,1302, offset (−0.5, −1.0).
- **box** (the mod's node): not centred (`offset,edge,pixels`), 175 label
  pixels (0.32 of the reference's), label box 2096,1262,2138,1270, offset
  (−69, −29). That is the clipped end of `Move all` at the box's top-left
  corner, the defect the owner saw. Exit 1.

The planning run's own measurement of the same screenshot read 538 reference
pixels and the same offsets. The pixel counts differ by the threshold's
boundary. The verdicts and offsets agree.

## Tests

`tests/test_button_label_check.py` draws synthetic screenshots with Pillow: a
centred label passes; Live 4's geometry fails with a centred reference; a
centred sliver under 40 % of the reference's pixels fails; a reference with
no label, an aspect mismatch and a usage error each exit 2; a GUI-to-image
scale of 2 maps the boxes, with a label drawn at the unscaled place as its
negative control. The tests skip without Pillow.

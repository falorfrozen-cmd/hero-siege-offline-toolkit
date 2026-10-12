# Drawing Our Own Sprites in the Game: What the Seraph Prototype Learned

The Seraph prototype put a custom character into the running game: an original
pixel-art body with a four-way walk cycle, energy wings, a halo, and two
animated skills drawn over the world. It was not a new class. The prototype
replaced what one White Mage character *looks like* by intercepting the game's
own draw call for that player's body. This page collects how that was done and
what it established about **getting our own art on screen**: loading, baking,
replacing a draw, drawing above the actors, and testing art offline. The next
mod that needs custom sprites can start from it.

Collected 2026-10-12, for ForgePact#158 (flight charms with custom icons, drawn
in front of scenery while flying). The source is the owner's local package
`Seraph-Implementation` (not in any repository). It has a write-up
(`HOW_IT_WORKS.md`), a step log (`docs/PROTOTYPE_LOG.md`), the C++ source
(`source/src/`, chiefly `SpriteRuntime.cpp`, `SpriteAtlas.hpp`,
`SkillVfxDraw.cpp` and `SkillRuntime.cpp`), offline tests (`source/tests/`)
and the art (`art/`). Paths below are relative to that package. It was built
and measured 2026-09-23..24. Its notes name no game build. The dates fall
after the 2026-09-18 update (`exe-281751552-pe6aaa6779-111b8000`), but that it
ran on that build is **not established**.

The measured facts about the game are also in
[`RUNTIME_DATA_MODELS.md` §22.9](../RUNTIME_DATA_MODELS.md#229-replacing-a-draw-and-drawing-above-the-actors-seraph).
That section is the shared record every module reads. This page keeps the
recipes, what was inferred, and how each applies to #158. Its sibling,
[afk-expedition-adding-content.md](afk-expedition-adding-content.md), covers
loading, layers, texture groups and GUI panels from HS-AFK-Expedition. Read §1
there for `sprite_add` itself.

Everything here is in our own words. The package says it contains no
decompiled game code, and none is quoted here. Its C++ is the owner's own
work; it is described rather than copied (`AGENTS.md` § Legal).

**Labels**
- **measured**: seen in a live game run and recorded in the package's
  `HOW_IT_WORKS.md` or `docs/PROTOTYPE_LOG.md`.
- **inferred**: read from the package's code or from GameMaker's documented
  behaviour, but not observed.
- **not established**: claimed or assumed without recorded evidence.

---

## 1. The approach: replace one draw, don't add an object

1.1 **The player's body is one `draw_surface_ext` call.** `Player_obj`'s Draw
event composes the character into a 300×300 surface, with the ground point at
its centre. That surface is the player's `playerSequenceData.sequenceSurface`.
The event then draws it with a single `draw_surface_ext`, at the player's
anchor minus 150 × scale on both axes, with jump and slope offsets already
applied. **measured**: the replacement below drew 10,582 frames in all four
directions, with 0 errors and 0 surface mismatches, and followed a camera zoom
mid-session. Source: `SpriteRuntime.cpp` header and `SurfaceHook`;
`PROTOTYPE_LOG.md` "sprite-v2".

1.2 **The built-in is detoured, filtered by surface handle.** The steps:
1. `GetNamedRoutinePointer("draw_surface_ext")`.
2. Confirm the address is executable inside the game module
   (`HeroSiege::Hooks::AddressIsExecutableInModule`).
3. Install `MmCreateHook` on it, keeping the trampoline.

The hook body's cheap filter passes everything through except a call with 8
arguments whose `args[0]` is the in-scope player's own sequence surface. Only
that call is replaced, and every other surface draw reaches the original.
Handles are compared by kind: numbers by value, `VALUE_REF` by `m_i64`. This
is a name-resolved inline detour, the route `AGENTS.md` § "Never Call an
Address You Resolved by Hand" allows. **measured** (1.1). Source:
`SpriteRuntime.cpp` `Install`, `SurfaceHook`, `SameHandle`.

1.3 **The replacement reuses the game's own arguments.** The anchor, scale,
blend, tint and alpha the game passed for its body are applied to our layers,
so jumps, slopes, zoom and fades work with no extra code. **measured** (1.1).

1.4 **Fail open, and count failures.** A `busy` flag stops the hook from
re-entering itself. Exceptions are caught, and the original is drawn instead.
After 25 errors the replacement disables itself and reports
`disabled-after-errors`, so a broken skin falls back to the vanilla body
rather than an invisible one. **inferred** (code; no error was ever hit live).

1.5 **Install late.** An early build installed hooks during module load and
crashed at start-up, because the game's localization was not ready yet. Every
hook now installs from the per-frame callback, after a sanity check succeeds.
**measured** (`HOW_IT_WORKS.md` §8). The crash was in the localization hook,
not the sprite hook, but the sprite runtime installs late too.

1.6 **Scope it to one character.** The replacement runs only for name
`SeraphTest`, save slot 5, exactly one player, and offline. Every other
character is drawn by the game unchanged. **measured**: an earlier session on
a slot-1 character stayed untouched.

## 2. Getting art into the game

2.1 **Load the whole PNG with `sprite_add`, then check its size.** The call is
`sprite_add(path, 1, false, false, 0, 0)`. It is tried first with the
absolute UTF-8 path of the module folder, then with the path relative to the
game directory (`mods/aurie/<folder>/art/<file>`). The result is accepted only
when `sprite_exists` says yes and `sprite_get_width/height` match the size the
manifest declares. Otherwise it is deleted and the import reports which file
and which size failed. **measured**: the art loaded and drew. Which of the two
paths worked was recorded per session in `sprite.json`. Source:
`SpriteRuntime.cpp` `LoadImage`.

2.2 **A JSON manifest gives every frame's rectangle.** `art/.../atlas.json`
lists each layer's file, size and scale, and every frame's `x, y, w, h` and
origin. The cells are 313/314 px, and nothing assumes a power-of-two grid. One
optional layer (`sideWalk`) was added without breaking schema version 1.
**measured** (it drew); the parser's rules are covered by offline tests (§5).
Source: `SpriteAtlas.hpp` `ParseAtlas`.

2.3 **Bake once into world-resolution cells.** The large source atlases are
used for one cut and then freed. The steps:
1. `surface_create` at the planned size, `surface_set_target`, and
   `draw_clear_alpha(0, 0)`.
2. `gpu_push_state`, `gpu_set_blendenable(false)` and
   `gpu_set_texfilter(false)`.
3. One `draw_sprite_part_ext` per frame into its planned cell, at the
   world-pixel scale.
4. `sprite_create_from_surface(surface, 0, 0, w, h, false, false, 0, 0)`,
   then `surface_free`, then `sprite_delete` of the source.

With blending off, the texels are copied straight, so a glow's alpha is not
multiplied by itself. With nearest sampling, the art sits on the game's own
pixel grid at any application-surface size. GPU state and the render target
are restored by RAII guards, even when a call throws. **measured**: the baked
art drew crisp in game. That alpha survives byte for byte is **inferred**.
Source: `SpriteRuntime.cpp` `Bake`, `GpuState`, `SurfaceTarget`.

2.4 **Scale from a measured target, not a constant.** The world scale comes
from the target body height (`body_height`, 46 px). A new skin therefore
lands at the measured in-game size whatever its source resolution. A config
reload that changes the scale re-bakes the art. **measured** (2.6). Source: `SpriteRuntime.cpp`
`Scale`, `Import`.

2.5 **Read pixels back to measure, never to guess.** `buffer_create`,
`buffer_get_surface` and `buffer_get_address` copy a surface's RGBA into
memory. That the surface is left unchanged is GameMaker's documented
behaviour, **inferred**: the sampled surface was replaced anyway, so it could
not be observed. The prototype used this two ways: to find each
baked cell's head centre, and to sample the *vanilla* body's opaque bounds
from the game's own surface. **measured**: 40 read-back samples. Source:
`SpriteRuntime.cpp` `ReadSurface`, `MeasureCells`, `SampleVanilla`.

2.6 **What was measured on the carrier** (White Mage, all **measured**; the
height and feet come from the read-back, the speed from position changes):
- The body is 46–47 px tall.
- **The feet are 16 px below the player position.** The first build put the
  feet on the position, and the art floated 16 px above the shadow until this
  was measured. The defaults are now `foot_offset = 16` and
  `body_height = 46`.
- Running speed is 205–217 px/s in all four directions (211 on average),
  measured from the player's `x`/`y` change per frame, not from the
  read-back. At
  7 fps each walk frame slid about 30 px; 12 fps, scaled with the measured
  speed, looks right.

2.7 **Collision masks for our own sprites.** A hit mask was made by drawing a
circle onto a surface, turning it into a sprite with
`sprite_create_from_surface` (origin at the centre), and calling
`sprite_collision_mask(spr, false, 1, 0, 0, d-1, d-1, 2, 0)`. That gives an
ellipse covering the full image: bbox mode 1 is the full image, so the
rectangle arguments are ignored, and kind 2 makes it an ellipse. The game's
damage objects used it as their mask. **measured**: 14 of 14 contacts lowered
enemy health. Source: `SkillVfxDraw.cpp` import.

2.8 **Damage objects of our own: two steps.** Seraph does damage through the
game's own hit code, never by writing health:
- It spawns one `Player_Damage_Parent_obj` per visible contact.
- The object carries the payload captured from the carrier's own cast, and
  the mask from 2.7.
- It keeps the object for exactly two steps, then removes it.

**measured**: 14 of 14 contacts lowered enemy health. Health was read before
and after each hit through `gml_Script_PC_GetVariableGMLWrapper` (package
`HOW_IT_WORKS.md` §6).

Why one step is not enough is **not established** live. The package's reading
of the game is that the stats load into the object after that frame's
collision pass. No recorded control shows a one-step object failing once the
hit transport was fixed. The earlier zero-damage run failed for transport
reasons, before any hit was submitted. Source: `SkillRuntime.cpp`
(`arming`, `pending`).

## 3. Drawing above every actor, under the HUD

3.1 **A world-space foreground drawn in the GUI pass.** The lance, impacts and
thorn tips must draw above every actor but still sit under the HUD. They are
drawn from a detour of `gml_Script_DrawHud`, installed with
`HeroSiege::Hooks::InstallScriptHook`, which puts in both the table route and
the inline route. The hook draws first and then calls the original, so the
HUD covers what was drawn. World coordinates map to GUI coordinates through
the active camera:

```
gx = (wx - camera_get_view_x(cam)) * k
gy = (wy - camera_get_view_y(cam)) * k
k  = display_get_gui_width() / camera_get_view_width(cam)
```

Here `cam` is `view_camera[0]`. The prototype used one factor for both axes.
That assumes the GUI and the camera view share an aspect ratio; otherwise use
`display_get_gui_height() / camera_get_view_height(cam)` for y. **measured**: the effects were seen above the
actors and below the HUD. All of Seraph's skill-effect drawing, in the body
draw and in this pre-pass while a cast was active, averaged about 0.1 ms per
draw call. Source:
`SkillRuntime.cpp` `DrawForeground`, `DrawHook`.

3.2 **Body-depth layers stay in the body's draw.** The wing rig is drawn
inside the replaced body draw (1.2): behind the body, or over the back when
facing north. So it sorts with the player exactly as the game sorts the body.
Layer order, back to front, is wings, body, halo. **measured**.

## 4. Animation state

The walk/idle state is plain C++ with no game calls (`SpriteAnimator.hpp`).
- Four-way facing follows movement, with 60° hysteresis so diagonals don't
  flicker.
- Idle holds frame 0, with a one-pixel breath.
- The walk runs at 12 fps at 211 px/s and scales with speed (5–16 fps).
- The Light/Darkness palette choice is stored in a text file in the module
  folder (`form.txt`), **never in the save**, so removing the mod leaves the
  save untouched.

**measured** (seen in game). The arithmetic is tested offline (§5).

## 5. Testing art without the game

- `tests/sprite_test.cpp` covers the real manifest: frame counts, the
  non-256-px rectangles, foot-origin placement, the walk/idle state, and
  reading an older manifest. It has 12 scenarios at the package's current
  revision. It proves frame selection
  and alignment arithmetic, not in-game appearance.
- `art/*/index.html` previews each atlas in a browser, with both palettes and
  every direction, before the game sees it.
- The VFX's C++ port is compared point by point with its JavaScript reference
  (`tests/vfx_test.cpp`, 28,808 points).
- Each session writes `sprite.json`, which counts frames replaced, errors,
  surface and identity mismatches, which load path worked, and the vanilla
  bounds. A hook that installs but draws nothing therefore shows up as a
  count, not as silence.

This matches `AGENTS.md` § "Test Before / After" and § "Prove the
Instrument": the vanilla body's own bounds are the positive control the
Seraph's placement is compared against.

## 6. What this means for ForgePact#158

Phase 1 of #158 (`ForgePact/docs/flight-charms-research.md`, Live 1)
measured three things. A charm carrying a `sprite_add` sprite under item key
`11` drew our icon in the bag but the game's ERROR placeholder on the ground.
The tooltip draws no icon for any charm. Phase 2 must also make the flying
player draw in front of scenery. The Seraph answers neither question
directly, because it never handed a sprite to the game to draw. It always
drew our art itself. Phase 2's planning (2026-10-12) then read both
mechanisms statically. The #158 research doc
(`ForgePact/docs/flight-charms-research.md`) and its hub PR will fold those
readings into RDM §19 and §22. This section says where the Seraph's techniques fit
next to them.

6.1 **Ground icon: the cause was a name lookup.** By static reading, the
ground item's init builds a sprite name, `Pickup_` plus the name of the bag
icon under key `11`, and looks it up with `asset_get_index`. When nothing
answers, it falls back to `Error_spr`. A runtime sprite has a generated name
with no `Pickup_` companion. Phase 2's plan is to write our own ground icon
onto the ground item right after its init, through the init detour ForgePact
already shares.

Two Seraph practices still apply here:
- Size the ground icon to the game's own ground sprites, which are much
  smaller than the bag icons (13x13 to 34x17 for charms, from the game's sprite
  table, a static reading made for #158 phase 2), and bake it with
  nearest sampling (2.3).
- The Seraph's draw-replacement route (1.2) remains the fallback if writing
  `sprite_index` does not hold. That route detours the one draw built-in,
  filters it to our instance, and draws our sprite with the game's arguments.
  It is not needed while the write holds.

6.2 **Drawing the flying player in front of scenery.** By static reading,
the player's Step calls `UpdateDepth` twice, and each call resets the
player's draw `layer` from its y. So a `depth` or `layer` write made earlier
in the frame does not last. Phase 2's plan is to set the room's front game
layer right after each of those calls, with the live check `flight-depth`
confirming which
end of the layer list is in front.

If that check fails, the Seraph's route is the fallback, and it does not
depend on the game's layers at all:
1. While flying, keep the player's own `draw_surface_ext` arguments from the
   body draw (1.2), and suppress that call.
2. Replay the call in the `DrawHud` pre-pass (3.1), through the camera
   transform, and multiply its xscale and yscale by k. Whether
   `sequenceSurface` still holds this frame's body when `DrawHud` runs is
   **not established**.

The player then draws above every actor and scenery piece, and under the HUD.
It has costs:
- Monsters draw under the player too.
- The name and health bar may be covered.
- Only the body surface moves. Shadow, weapon and effect draws that are
  separate from it, if any, stay where they are, and which those are is
  **not established**.

6.3 **Art for 2x2 and 1x5 charms.** Use the Seraph's manifest-and-bake
pipeline (2.2–2.4). Each item gets one source PNG, with its rectangle and
origin in a manifest. Check it offline (§5) and bake it at the grid's cell
size with nearest sampling. The art must be original, never extracted from
the game.

## 7. Not covered by the Seraph

- Item icons, in the inventory grid, the tooltip or on the ground.
- Whether a `sprite_add` or baked sprite survives a room change or a texture
  flush indefinitely. The Seraph re-imports when its scale changes; no
  long-session test is recorded.
- GPU memory cost of the baked atlases.
- Multiplayer or online. The prototype refuses to run there by design.

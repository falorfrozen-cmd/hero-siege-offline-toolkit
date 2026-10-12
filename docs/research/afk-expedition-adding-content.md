# Adding New Things to the Running Game: What HS-AFK-Expedition Learned

HS-AFK-Expedition built a whole in-game Stronghold: its own artwork drawn in a
repurposed room, an in-game panel over the game's UI, its own input handling,
spawned monsters and NPC figures, and gates made of the game's invisible wall.
This page collects what that work established about putting **new things** into
Hero Siege (sprites, layers, texture groups, GUI drawing, input, spawning,
collision), so the next mod starts from it instead of rediscovering it.
Collected 2026-10-12 for hub #498 from all 52 remote branches of
[`falorfrozen-cmd/HS-AFK-Expedition`](https://github.com/falorfrozen-cmd/HS-AFK-Expedition)
(private). Its first consumer is ForgePact#158, flight charms with custom icons.

The facts about the game itself that were **measured** are also in
[`RUNTIME_DATA_MODELS.md` §22](../RUNTIME_DATA_MODELS.md#22-adding-our-own-content-art-drawing-input-spawning-and-blockers),
the shared record every module reads. This page keeps the rest: AFK's own
recipes, the inferred and open claims, and what was superseded.

Everything here is in our own words. No game script text is quoted, and AFK's
own C++ is described rather than copied (`AGENTS.md` § Legal).

**Labels**
- **measured**: seen in a live game run; the AFK document or commit that records it is cited.
- **inferred**: read from AFK's own code or from GameMaker's documented behaviour, not observed. (Not the same as the runtime reference's *static reading*, which means read from the game's compiled code.)
- **not established**: claimed or assumed without recorded evidence, or left open.

**Pointers.** Most code lives on AFK's `origin/codex/castle-rendering-share`
(tip `f581067`), which carries AFK `main` plus later commits up to `c9da136`;
it is written **CRS** below. "main" means AFK `origin/main` (`1e41a1a`). A bare
commit hash is an AFK commit. Documents named in capitals
(`CITY_VERIFICATION_20261006` and the like) are under AFK's `docs/`.

**Game build.** Every AFK verification doc that names a build gives
`exe-281751552-pe6aaa6779-111b8000`, the 2026-09-18 update; the earlier one was
`exe-281798144-pe6a9ed3ee-111c3000` (PHASE0_NOTES). The R1/R2/R8 research
write-ups (2026-09-26..29) name no build; they postdate that update, so they
probably ran on it, but that is **not established**. Every name below is
resolved by string at runtime and can move with a game update.

**Not available.** The R8 lab branch `claude/r8-map-lab`, cited in
STRONGHOLD_DESIGN §10, is not on the remote. AFK's raw `verification/` evidence
folders are git-ignored and were never pushed.

---

## 1. Loading our own art at runtime

1.1 **`sprite_add` loads a PNG from disk at runtime.** The call is `sprite_add(path, frames, false, false, 0, 0)` (removeback=false, smooth=false, origin 0,0). A multi-frame PNG is a single row of equal-width frames. It is **measured**: the player's images were drawn on the map, including "29 shown at build" from 75 placeholders, and the showcase showed "32 custom images" with every one of 26 architecture images confirmed. Recorded in STRONGHOLD_DESIGN §6 B2 "Product check", and in STRONGHOLD_SHOWCASE_VERIFICATION. Source: CRS `plugin/StrongholdMap.inl` `LoadOurs` (~l.220-283). The same call loads F6 panel pieces in `plugin/StrongholdPanel.inl` `SpriteOf` (~l.487).

1.2 **The automatic bounding box counts every pixel above alpha 0.** Generated art (ChatGPT) often carries a faint halo of alpha 1-8 far wider than the object. The ballista tower measured 527×998 visible but 1152×1144 with its halo. Fitting by the raw box drew pieces at about half size and lifted them off the ground. AFK fixes this by re-measuring with `sprite_collision_mask(spr, false, 0, 0,0,0,0, 1, 16)`: separate-masks false, bbox mode 0, kind 1, tolerance 16. After that, `sprite_get_bbox_left/right/top/bottom` give the visible part. **measured** (values read in game). Source: commit `3be2c96` (origin/claude/stronghold-art-fit), CRS `StrongholdMap.inl` l.263-269 (`HALO = 16`). Diagnostic: `stronghold map art`.

1.3 **Origin and scale are set from the measured visible box.** For a piece that stands on the ground, `sprite_set_offset(spr, (bl+br)/2, bb)` puts the origin at bottom-centre. Other origins are centre or left-middle. Scale is the box size divided by the visible size; wall and gate pieces use "span_x" or "span_y" so neighbours join exactly. This is AFK's recipe, so it is **inferred**. It was used in every live build: `b1ccba5` reports a live check with placeholder art. Source: CRS `StrongholdMap.inl` l.271-277.

1.4 **Cropping a cell out of a PNG atlas into its own sprite.**
- Steps:
  1. `sprite_add` the whole atlas.
  2. `surface_create(cw, ch)`, then `surface_set_target`.
  3. `draw_clear_alpha(0, 0)`, then `draw_sprite_part(atlas, 0, x, y, cw, ch, 0, 0)`.
  4. `sprite_create_from_surface(surf, 0, 0, cw, ch, false, false, 0, 0)`.
  5. `surface_reset_target`, `surface_free`, then `sprite_delete` the atlas.
- AFK first checks the crop against `sprite_get_width/height` (`City::CropFits`).
- It runs from AFK's per-frame callback (Present time), not inside a draw event, and it worked there.
- **measured**: cropped level-5 workshop, temple, market, keep and homes were seen in Dev_10_rm. Recorded in CITY_VERIFICATION_20261006.md.
- Whether alpha survives byte-exactly through the surface is **inferred**; nobody measured pixel values.
- Source: commit `fb58b27`, CRS `StrongholdMap.inl` l.232-262. The atlas is 1536×1024 with six 512-wide cells; measured row gutters are in `tools/stronghold_art.py` `CITY_CUTS`.

1.5 **Free what you load.** Every own sprite is `sprite_delete`d before a rebuild (`ForgetArt`), so a changed PNG shows on the next build. Sprites meant to persist across rooms, such as the Steward's art, are loaded once per session and never deleted (`KeptArt`). This is AFK's own recipe: **inferred**. Source: CRS `StrongholdMap.inl` l.305-315, l.537-543.

1.6 **Load only a few PNGs per frame.** The F6 panel decodes at most 2 `sprite_add`s per frame, and a picture rendered to a surface lifts that budget. The aim is that opening the panel never stalls the game. That a burst of `sprite_add` would stall the game is **not established**: no stall was measured. Source: `2903b29` (origin/claude/ingame-panel), CRS `StrongholdPanel.inl` `g_LoadBudget`.

1.7 **`font_add` loads a TTF at runtime.** The call is `font_add(path, size_pt, false, false, 32, 8230)`. AFK converts design pixels to points as px × 0.75 ("points at 96 dpi"). It works: the panel was drawn with the package's TTFs at 2560×1440, which is **measured** (INGAME_PANEL_VERIFICATION, 33 GameMaker panel images). The claim that each added font takes its own texture page of "about 16 MB", and that bucketing sizes to 22/27/32/38/56 cut memory from 330 to 250 MB, is **not established**: the verification doc says texture figures "are asset calculations, not measured GPU memory". Source: `f17f840` (origin/claude/ingame-panel-2), CRS `StrongholdPanel.inl` l.505-528.

1.8 **Art-file checks done offline before the game ever sees a file.** This is an AFK recipe, **inferred** from its tool's code.
- PNG signature and chunk CRCs are checked.
- Limits: at most 32 MB and 8192 px per side.
- Object art must have an alpha channel (colour type 4 or 6). A ground texture saved as RGBA with every alpha byte at 255 is accepted. The check decompresses the rows and compares each row's filtered alpha bytes to the all-opaque pattern for its filter, without decoding pixels: about 40 ms for 1254².
- Source: `fd37421` (origin/claude/art-check-alpha), CRS `tools/stronghold_art.py` `png_info`, `opaque`, `check`.

---

## 2. Placing art in the world: layers, depth, shadows, ground

2.1 **Room art is drawn with layer sprites, not instances.**
- Calls: `layer_create(depth, name)`, `layer_sprite_create(layer, x, y, sprite)`, `layer_sprite_xscale` / `yscale`, `layer_sprite_speed`, `layer_sprite_angle`, `layer_sprite_blend`, `layer_sprite_alpha`, `layer_sprite_index`, `layer_sprite_x` / `y` and `layer_sprite_destroy`.
- **measured**: R1 Steward and markers (`930f13e`), the R8 map (STRONGHOLD_DESIGN §6 B2), the showcase and the city.
- Source: CRS `StrongholdMap.inl` `PutSprite` l.318-330; R1 lab `origin/claude/r2-defense-lab:plugin/InGameUI.inl` `NpcHere`, `MarkHere`.

2.2 **Depth follows y.** Objects in a room sort by depth, and an object's depth follows its y. AFK uses depth = −y/2 for anything standing at y. R1 read instance depths with `ui live` and placed the Steward's layer at the hero's own depth. The −y/2 rule for the game's objects was observed in R1 and stated in the design ("the figure's depth can follow the game's own rule (depth = −y/2)"). That it holds for every object is **not established**. Using it for layer sprites worked: pieces sorted with the hero and monsters in every live build, which is **measured** for the map and showcase. Source: STRONGHOLD_DESIGN §6 B1; CRS `StrongholdMap.inl` l.317, `StrongholdWindow.inl` `StewardPlace`.

2.3 **One layer per depth, named `afk_map_<depth>`.** Calls: `layer_get_id(name)`, else `layer_create`. Two sprites on the same layer keep no set draw order, so a piece that must sit in front, such as the banner emblem, gets its own layer at a slightly larger y. The ordering problem is stated in `b1ccba5`; the fix was checked live with placeholder art, but the bad ordering itself was not recorded separately. **measured (fix only)**. Source: `b1ccba5` (origin/claude/stronghold-map), CRS `StrongholdMap.inl` l.600-605.

2.4 **Fixed depths AFK used.**
- Ground 1000, courtyard tiles 999, roads 998, shadows 997.
- Projectiles and impact effects at −20000, above everything in the room.
- Wall blockers at −y1/2.
- Service actors at layers `afk_map_service_<key>`, depth −y/2.
- This is an AFK recipe: **inferred**. It rendered as intended in the city run (**measured**, CITY_VERIFICATION_20261006). Source: CRS `StrongholdMap.inl` `Ground`, `PutShadow`, `ShotLayer`.

2.5 **Layers die with the room.** Layers and layer sprites created in a room disappear when the hero leaves it ("the old room took the map's pieces with it"). AFK drops its handles on a room change and rebuilds on return. It removes its own layers by name prefix (`layer_get_all`, `layer_get_name`, `layer_destroy`). This is **measured**, implicitly, by every enter, leave and re-enter cycle (STRONGHOLD_DESIGN product check). Source: CRS `StrongholdMap.inl` `Frame` l.1157-1162, `Clear` l.546-565.

2.6 **Hiding a room's own layer.** `layer_set_visible(layer_get_id("Background"), false)` hides the unused room's background so AFK's ground shows. **inferred** from the code; it was part of the measured builds. Source: CRS `StrongholdMap.inl` `Ground` l.486.

2.7 **Ground.**
- With an own texture: `layer_background_create(layer, sprite)` plus `layer_background_htiled` / `vtiled(true)` and `layer_background_xscale` / `yscale`, on a depth-1000 layer.
- Fallback: `layer_tilemap_create(layer, 0, 0, tileset, cols, rows)` with 64 px tiles, filled through `tilemap_set` from a list of plain tile indices.
- The first fallback, `Fall_Ground_tileset2` (red autumn floor), clashed with the art. It was **superseded** by `Miner_Village_Ground_2_tileset`, tiles 1,2,4,5,6,8,15,18-20,22,25-27.
- **measured** (owner's visual judgement). Source: `46f48ae` (origin/claude/stronghold-shadows-ground), CRS `StrongholdMap.inl` `Ground`.

2.8 **Soft drop shadows.**
- Shape: a black ellipse PNG, 256×96, alpha at most 140/255, written by the Python side as `stronghold/map/shadow.png`.
- It is loaded with `sprite_add` and the origin is centred.
- It is drawn on its own layer at depth 997, just above the ground, scaled to 1.15 × the piece's visible width and nudged up by 8% of its height.
- It was added because the owner found the pieces "looked pasted on". That the result looks right is **not established**: no later visual verdict was recorded.
- Source: `46f48ae`, CRS `StrongholdMap.inl` `PutShadow` l.413-433.

2.9 **Animating layer sprites.**
- For own multi-frame sprites, AFK calls `sprite_set_speed(spr, 1, 1)` (one frame per game frame), then `layer_sprite_speed(el, k)` per element.
- For game NPC sprites it sets `layer_sprite_speed(el, 0)` and drives `layer_sprite_index` from wall-clock time: 4 fps idle, 12 fps for the hammering animation. It plays a sound on the contact frame at about 55% of the frames.
- **measured** visually in the Blacksmith run ("city animation" PNGs inspected; BLACKSMITH_NPC_VERIFICATION_20261007). Source: CRS `StrongholdMap.inl` l.278; `StrongholdSmith.inl` l.160-186.

2.10 **Projectiles and beams drawn as moving layer sprites.**
- A projectile is created at the tower and moved each frame with `layer_sprite_x` / `y`. A mortar adds a parabolic lift of 4·arc·t(1−t).
- It is rotated with `layer_sprite_angle(atan2)`. Art points right.
- A beam is stretched with `layer_sprite_xscale(dist / sprite_width)`.
- An impact sprite is spawned at the target and destroyed after `frames / 0.4` game frames.
- **measured**: "towers' shots fly" (R8; STRONGHOLD_DESIGN §6 B2).
- Source: CRS `StrongholdMap.inl` `Shoot`, `Frame` l.1171-1194.

2.11 **Tinting.** `layer_sprite_blend(el, colour)` tints a white flag with the banner colour. **inferred**: the banner is not mentioned in any verification doc. Source: CRS `StrongholdMap.inl` l.600.

2.12 **Placing a game sprite without changing it.** To stand an existing NPC sprite bottom-centre at (x, y):
- read `sprite_get_bbox_left`, `_right`, `_bottom` and `sprite_get_xoffset` / `yoffset`;
- create the layer sprite at x − ((left+right)/2 − xoff), y − (bottom − yoff).

This avoids `sprite_set_offset` on a shared game sprite, which would change it everywhere it is drawn; that side effect is **inferred** from GameMaker semantics. The placement is **measured** (city services: "All three sprites present"; CITY_SERVICES_VERIFICATION_20261007). Source: CRS `StrongholdServices.inl` `Place`, `StrongholdSmith.inl` l.66-80.

---

## 3. Texture groups and prefetch

3.1 **A sprite whose texture group is not loaded draws nothing.**
- The game streams 254 dynamic texture groups by region.
- `Guild_Master_NPC_spr` lives in `act_2_tex`. As a layer sprite in Town_01 it drew nothing until `sprite_prefetch(spr)` was called; then the user saw it.
- Sprites in `npc_tex`, such as `Tristan_NPC_spr`, are loaded everywhere and show directly.
- **measured** (R1, 2026-09-26). Source: commit `930f13e` (origin/claude/r2-defense-lab), STRONGHOLD_DESIGN §6 B1 "Constraint".

3.2 **Texture-group introspection works at runtime.**
- `texturegroup_get_names()` lists the groups, and `texturegroup_get_sprites(name)` lists the sprites in one.
- `texturegroup_get_status(name)` returns 0 unloaded, 1 loading, 2 loaded, 3 fetched.
- `sprite_get_texture(spr, 0)` with `texture_is_ready(tex)` tells whether a sprite can draw.
- **measured** (the R1 `ui tex` tool reported 254 groups). Source: r2-defense-lab `InGameUI.inl` `TextureInfo` l.326-349.

3.3 **Tilesets prefetch through their texture.** Call `texture_prefetch(tileset_get_texture(tileset))` before entering a room, and check `texture_is_ready`. The Miner Village tileset is in Act 4's group, so it is fetched when the hero sets off and again at build; the build log says if it is still loading. **inferred** from the code, part of measured builds. Source: `46f48ae`, CRS `StrongholdMap.inl` `Enter` l.1125, `Ground` l.497-503.

3.4 **Monsters spawned in an unused room are drawn once their sprites are prefetched.**
- Dev_10_rm does not load an Act's monster texture groups.
- After Create, AFK prefetches `sprite_index`, `object_get_sprite(obj)` (before creation), and every instance variable named `enemy_up/down/left/right`, `enemy_idle_*`, `enemy_attack_*`, `enemy_melee_attack_*`, `enemy_cast_*`, `enemy_hurt_*`, `enemy_death_*`, `enemy_corpse` or `shadow_sprite`. It enumerates them with `variable_instance_get_names`.
- The objects' own Create, Draw and animation code is kept.
- **measured**: "recorded Chilling Head sprites were visibly drawn with their health bars and affix effects" (CITY_VERIFICATION_20261006).
- That they do not draw *without* the prefetch is **inferred** from the NPC case in 3.1; no run recorded an un-prefetched monster failing to draw.
- Source: CRS `plugin/LiveDefense.inl` `PrefetchSprite` and `PrefetchMonster` l.217-241; docs/STRONGHOLD_CITY.md.

3.5 **Fallback game sprites are prefetched when chosen.** Every game sprite used as a fallback for missing own art is `sprite_prefetch`ed the first time it is resolved (`ArtFor`). **inferred**. Source: CRS `StrongholdMap.inl` l.287-303.

---

## 4. Drawing over the game: in-game windows and GUI

4.1 **YYToolkit's object-event callback is unavailable on this YYC build.** `CreateCallback(EVENT_OBJECT_CALL)` returns `AURIE_UNAVAILABLE`. AFK therefore draws from an **inline detour** (`MmCreateHook`) on a compiled object-event function, resolved by its name `gml_Object_<obj>_<event>`. The name resolution goes through the SDK's `HeroSiege::Hooks::ResolveNativeName`: it scans the image's read-only sections for the string and maps the function through `RtlLookupFunctionEntry`. **measured** 2026-09-26. Source: `69003a1` (r2-defense-lab `InGameUI.inl` header l.33-36); CRS `ModuleMain.cpp` `ResolveYycFunctionByName` l.1185.

4.2 **GUI event order in town, and the last one.**
- Measured order: `Loot_Manager` (Draw GUI Begin), `Controller`, `UI_Inventory_Drag`, `Menu_Controller` (Draw GUI), then `objColorBlindShader` Draw GUI End (`gml_Object_objColorBlindShader_Draw_75`) last.
- Drawing right after the last one puts the window above the whole game UI: inventory, a dragged item and menus.
- The R1 lab first planned to draw from the cursor object's Draw GUI, but the cursor object has no instance in town. That plan was **superseded** by the colour-blind shader anchor.
- **measured** (R1). Source: `930f13e`; CRS `StrongholdWindow.inl` l.10-13, l.38.

4.3 **Event-name suffixes AFK used.** `Draw_64` is Draw GUI, `Draw_74` is Draw GUI Begin and `Draw_75` is Draw GUI End (R1 `ui find`). `ui scan <suffix>` lists every compiled `gml_Object_*_<suffix>` whose object has live instances, and `ui order` places probe detours to rank events within a frame. **measured** as tools (R1). Source: r2-defense-lab `InGameUI.inl` `ScanEvents`, `FindEvents`, `OrderStart`.

4.4 **Restore the draw state after drawing.** Save `draw_get_alpha`, `draw_get_colour`, `draw_get_halign`, `draw_get_valign`, `draw_get_font` and `gpu_get_texfilter` before drawing, and restore them after. Every later GUI step expects its own state. This is AFK's rule: **inferred**. No breakage without it was recorded. Source: CRS `StrongholdPanel.inl` `DrawState` l.1132-1150; `StrongholdWindow.inl` l.217-221, l.306-310.

4.5 **GUI size equals the monitor resolution.** It was 2560×1440 on the owner's PC. AFK scales a 1920×1080 design canvas by min(gui_w/1920, gui_h/1080), centred. Earlier versions scaled by gui_h/1080 only. **measured** 2026-09-30. Source: `885ca5d` (origin/claude/window-cursor), CRS `StrongholdPanel.inl` `Draw`.

4.6 **Text.** The R1 window drew with `draw_text_transformed` at a scale of 22·s / `string_height("M")`, so text size follows the current font. The game's own fonts can be listed with `font_exists` / `font_get_name`. **measured** (R1 window "draws and reads"). Source: r2-defense-lab `InGameUI.inl` `DrawWindow` l.153-162.

4.7 **A semi-transparent window lets game labels show through.**
- At alpha 0.9, town name labels showed through the window.
- The window was made opaque.
- **measured**: owner screenshot 2026-09-27.
- Source: `91d7216` (origin/claude/stronghold-phase4b).

4.8 **Clipping.**
- `gpu_set_scissor(x, y, w, h)` clips in render-target pixels.
- `gpu_get_scissor()` returns a struct whose `w` gives render-target pixels per GUI pixel (`w / gui_w`).
- `gpu_set_texfilter(true)` smooths scaled pieces.
- Nine-slice pieces are drawn with `draw_sprite_part_ext`.
- **measured**: scrolling lists clipped correctly in 117 native panel commands and 33 panel images (INGAME_PANEL_VERIFICATION).
- Source: CRS `StrongholdPanel.inl` `ClipTo` l.1042-1051, `MeasureTarget` l.1152-1158.

4.9 **Screenshots the game takes itself.**
- `surface_create`, then `surface_set_target`, `draw_clear_alpha(0, 1)`, draw, `surface_reset_target`, `surface_save(surf, path)` and `surface_free` render the panel offscreen.
- This works while the game window is minimized, when the screen itself is 0×0.
- `screen_save(path)` captures the screen.
- **measured** (33 GameMaker panel images; INGAME_PANEL_VERIFICATION; Blacksmith snapshots).
- Source: CRS `StrongholdPanel.inl` `Shot` l.1160-1191; `StrongholdSmith.inl` l.197.

4.10 **Install late.** The window detour and file reader are installed at frame 660 (about 11 s after start), not at plugin load. The reason is not documented: **not established**. Source: CRS `StrongholdWindow.inl` `FrameInner` (`fc >= 660`), from `00efb3d`.

4.11 **Effects AFK says cannot be made at runtime.** The panel brief says shadows, glows, blur, gradients, rounded corners and textures "cannot be made in the game at run time" and must be baked into PNGs. This is a design-brief assertion, **not established**: no attempt with shaders, blend modes or primitives was recorded. Source: CRS `docs/CHATGPT_INGAME_PANEL.md` §3.

---

## 5. Input, clicks, cursor, focus

5.1 **Swallowing input through `EVENT_WNDPROC`.**
- Register `CreateCallback(module, EVENT_WNDPROC, cb, 0)`.
- In the callback, `ctx.Override(0)` stops a message from reaching the game.
- A press over the window, or F6, never reaches the game: `mouse_check_button(mb_left)` and `keyboard_check(VK_F6)` stay false. A press outside, and the control key F13, are seen.
- In town with posted input: swallowed press seen 0 of 1, control 1 of 1, swallowed F6 0 of 2.
- In Act 2 combat on 2026-09-27, 0 of 3 button clicks were seen and both outside clicks were.
- **measured**. Source: `69003a1`; STRONGHOLD_DESIGN §6 B1; r2-defense-lab `InGameUI.inl` `WndProc` l.246-274.

5.2 **Swallow a release only if its press was swallowed,** so the game never sees a button stuck down. Treat `WM_LBUTTONDBLCLK` as a press. Two clicks during one running action must run it once. AFK recipe, **inferred**; the double-click bug itself was seen live (`d0da74b`, origin/claude/window-double-click). Source: CRS `StrongholdWindow.inl` `WndProc` l.381-395.

5.3 **Map window pixels to GUI units** as `LOWORD(lparam) × gui_w / window_get_width()`, and the same for y. A minimized window reports no size; posted test input then maps 1:1. **measured** (R1 self-test). Source: r2-defense-lab `InGameUI.inl` l.118-121, l.267-268.

5.4 **Posted input reaches the game.** `PostMessageW(window_handle(), WM_LBUTTONDOWN/UP or WM_KEYDOWN/UP, ...)` reaches the game's input state, which the outside control press proved. It also works while minimized. **measured** (R1). Source: r2-defense-lab `InGameUI.inl` `Post`, `PostKey`, `TestStep`.

5.5 **A full-screen panel captures everything.**
- While open it consumes all mouse buttons and the wheel. `WM_MOUSEWHEEL` feeds `GET_WHEEL_DELTA_WPARAM` into scrolling.
- Esc closes the innermost dialog, then the panel.
- A focused text field takes `WM_CHAR`, `WM_KEYDOWN` and `WM_SYSKEYDOWN` (Back, Return, Delete, arrows with Shift, Home, End, Ctrl+A/C/X/V). It also eats the matching `WM_KEYUP` for keys whose down it ate.
- Clipboard writes need the game's window as owner.
- **measured** (117 native panel commands; INGAME_PANEL_VERIFICATION). Clipboard round-trips were skipped.
- Source: CRS `StrongholdWindow.inl` l.344-375; `StrongholdPanel.inl` l.1402-1404.

5.6 **A proximity interaction key without breaking game menus.**
- `F` is consumed only when an AFK interaction is available: a gate, actor or Steward within 120 px, with no AFK panel open.
- A game menu counts as open when any `UI_Parent_obj` instance has `enabled` true and `level` > 0; F is not taken then.
- The callback only sets an atomic. The action runs on the game frame.
- Collision changes are never made from the window callback.
- Status: native code paths are **measured** through IPC (DEFENSE_INPUT_VERIFICATION_20261007). The physical F key and native menu key isolation are **not established**: the doc lists them as still needing player verification.
- Source: CRS `StrongholdWindow.inl` l.376-380; `StrongholdMap.inl` `GateMenuOpen` l.783-795, `RequestGate`.

5.7 **The cursor: who draws it, and what finally worked.** This was a chain of attempts, each superseding the last.
- (a) Re-running `gml_Object_Screen_Cursor_obj_Draw_64` after the window failed: `Screen_Cursor_obj` has no instance in play (`d97a7b6`, then `66a4df0`).
- (b) The game hides the Windows cursor: `window_get_cursor()` is `cr_none` in play, **measured** 2026-09-30. Setting `window_set_cursor(cr_arrow)` over the window "did not last: the game puts its own setting back", **measured** (`66a4df0`, then `b358c33`).
- (c) What works: the game draws its cursor from `Menu_Controller_obj` in an earlier GUI step. AFK draws `Cursor_spr` again, last, with `draw_sprite_ext(Cursor_spr, 0, device_mouse_x_to_gui(0), device_mouse_y_to_gui(0), s, s, 0, c_white, 1)`, where s = `global.mouse_gui_scalar` (default 2). **measured**: drawn every frame above the panel at 2560×1440 (`b358c33`).
- Source: commits `d97a7b6` and `66a4df0` (origin/claude/window-cursor), `b358c33` (origin/claude/f6-cursor); CRS `StrongholdPanel.inl` `DrawGameCursor` l.530-552.

5.8 **Automatic character entry: a direct callback call broke mouse input.**
- AFK first entered a hero by calling the menu's activation scripts directly (`UiAMainMenuLocal`, `UiAChooseSaveSlot`, `UiACharacterPlay`).
- After that, mouse clicks on the inventory Extra tab and skill selection stopped working. Movement and keyboard still worked.
- Controlled comparisons: YYToolkit only plus manual select worked; AFK plus manual select worked; AFK plus automatic select failed. **measured** (DEFENSE_INPUT_VERIFICATION_20261007).
- **Superseded in 0.9.7.** AFK finds the `UI_Node_Parent_obj` instance whose `activationFunc` names that script, checks `enabled` / `hidden` / `manualDisable` and the owner's `loadInProgress`, and runs `event_perform(7, 25)` on the node (ev_other, ev_user15), with the node as self and other.
- With the fix, Extra and skill selection worked after automatic entry. **measured** (AUTO_ENTRY_VERIFICATION_20261007).
- Source: commit `e380504`; CRS `plugin/TestSession.inl` `UiActions` and `Activate` l.29-102.

5.9 **Mouse-routing diagnostics.** The window status counts mouse-button messages received and those AFK consumed. When the player reported broken clicks, AFK had consumed 0, and a physical hold reached `mouse_check_button(1)`. `input passthrough` bypasses all AFK interception. The local YYToolkit dispatcher forwards unhandled messages by itself, so do not call the original again (**inferred** from YYToolkit's code). Source: `09c8e96`; DEFENSE_INPUT_VERIFICATION_20261007.

5.10 **Bringing the game window back to front.**
- A plain `SetForegroundWindow` was refused on the owner's PC: Windows' foreground lock. **measured** 2026-10-02.
- AFK then briefly joins the foreground thread's input (`AttachThreadInput`), but never a hung window (`IsHungAppWindow`), and calls `BringWindowToTop`, `SetForegroundWindow` and `SetActiveWindow`.
- That the join fixes it is **not established**: no verification is recorded in the commit.
- Source: `5252e3f` (origin/claude/focus-attach), `81c668a`; CRS `ModuleMain.cpp` `CmdFocus` l.3111-3139.

5.11 **Closing the game safely.** `WM_CLOSE` to the first visible process window can hit YYToolkit's console, which ends the game with 0xC000013A and no normal save. Send it to the window of class `YYGameMakerYY` instead; that exits with code 0. **measured** 2026-09-28. Source: `09961fb` (origin/claude/game-session-close-window).

5.12 **Click latency is an IPC problem, not a game one.** File-polled clicks were answered in 13-15 s. A dedicated watcher thread polling every 20 ms, with a 25 ms document read, brought this to 125-187 ms. **measured**. Source: `7cea1ee` (origin/claude/f6-instant).

---

## 6. Spawning objects and NPCs

6.1 **Monsters through `instance_create_depth(x, y, depth, obj)`** come alive with the current room's stats. The Act-2 `Frost_Skeleton_Passive_obj` had 1,881,250 health at rank 1. **measured** R2 (`fb7bae5`).

6.2 **Rank and affixes are set right after creation, before the stats are built.**
- Rank: `enemyRarity`. Rank 3 has 2× health.
- Affixes: `affixList`, an array of ids, plus the `enemyAffix` flag array with `[id] = true`.
- The game then applies each affix and names the monster: Champion (0) gives ×1.2 health, Thick Skin (30) ×1.75, Extra Fast (8) speed ×2.1.
- **measured** R2/R2b. The code comment names the stat-building step as the monster's Alarm 4: **inferred**.
- Source: `57b4ad5`; CRS `LiveDefense.inl` `ApplyAffixes`, `SpawnSome`.

6.3 **Movement range must be set one frame later.** `aggroRange`, set at spawn, is reset to 300 when stats are built. AFK therefore sets `aggroRange` (and `distance`, which it also sets) one frame after creation; that the game resets `distance` too was not observed. A monster beyond `aggroRange` stays idle; raising both makes it walk to the hero. **measured** R2/R2b. Source: `57b4ad5`; CRS `LiveDefense.inl` l.459-465.

6.4 **Monsters delete themselves in a town.** A monster spawned in `Town_02_rm` removes itself within a second. **measured** R2. The cause is lifted by answering `CheckTown` false; see 6.7.

6.5 **The active box.** The game moves and kills monsters only within about one screen of the hero. Deaths happened at 650 px; 8 of 12 happened at 750 and 850. AFK appends its own ids to `Controller_obj.monsterHandleArray` (count in `monsterHandleArrayCount`) after `ActivateDeactivateProps` returns, and far monsters then keep stepping. The box distances and the append effect are **measured** R2 and R8. That the game steps only instances in that array, and that `ActivateDeactivateProps` is what rebuilds it every frame, is **inferred** from AFK's hook placement; the runtime reference's static reading ([§11.3](../RUNTIME_DATA_MODELS.md#113-the-enemy-loop)) has `EnemyStepHandleNew` rebuilding it every 30 frames, and the R2/R8 result fits either. Source: `fb7bae5`; CRS `StrongholdMap.inl` `HookAdp` l.676-697.

6.6 **Spawn cost.**
- 60 and 120 live monsters held 60 fps: mean 16.67 ms, peak 17.2 ms.
- 200 kills, each with a spark effect, peaked at 20.9 ms.
- **measured** R2/R2b.

6.7 **Making an unused room behave like a zone.** Route-hook `gml_Script_` routines and answer only while the hero is in that room:
- `CheckTown` returns false;
- `RoomIsZone` returns true;
- `GetAct` returns the reference zone's act;
- `GetMonsterLevel` and `ReturnEnemyStats` are called with argument 0 replaced by the reference room;
- `GetRoomName` returns a custom name.

Monsters there then have the zone's exact stats, and loot and XP stay the game's own. **measured** R8. The hooks are inline detours installed by name (`InstallScriptDetour`). Source: CRS `StrongholdMap.inl` l.638-698.

6.8 **NPC actors as layer sprites, not game objects.**
- Steward: `Guild_Master_NPC_spr`.
- Jeweler, Alchemist and Trader: `Broker_NPC_spr`, `Witch_NPC_spr` and `Traveling_Merchant_NPC_spr`.
- Blacksmith: `Orre_Npc_spr`, switching to `Orre_Npc_Hammering_Up_spr`, with an anvil sprite and `Hell_Spark_Particle_spr` toggled by `layer_sprite_alpha`.
- Sounds: `audio_play_sound(Interacting_snd, 0, false)` and `Blacksmiths_Mallet_snd`.
- AFK's rule is never to create a vanilla vendor or NPC object, because its Create event could start the game's own purchase flow. That consequence is **inferred**: it was never tried.
- Placement and talking are **measured** (CITY_SERVICES and BLACKSMITH_NPC verification docs). Whether the sound is audible is **not established**.
- Source: CRS `StrongholdServices.inl`, `StrongholdSmith.inl`, `StrongholdWindow.inl` l.39.

6.9 **Proximity is computed from the hero's x/y** (`GetVarNumber(hero, "x"/"y")`) against the actor, within 120 px. Every action re-checks proximity and the hero's identity (slot, name, class). The hero instance comes from AFK's `Stronghold::LoadedHero()`. **measured** ("distant refusal", "departure closes conversation"). Source: CRS `StrongholdServices.inl` `Reason`.

6.10 **Placing the hero.** On arrival AFK writes `x` and `y` on the hero instance with `variable_instance_set`, and sets `Controller_obj.zoneGenFound = true`. Moving the hero this way works: **measured**, since every map build places the hero. Why `zoneGenFound` is needed is **not established**. Source: CRS `StrongholdMap.inl` `Build` l.611-614.

6.11 **Monster XP and loot when not killed by the hero.**
- Writing health to 0 through `PC_SetVariableGMLWrapper(handle, 0)` runs the game's own death, but `DropItem` ran on only about 50%, or 25% of tower kills, and gave no XP.
- Parity needs two things. First, call `gml_Script_DropItem(self=monster, other=player)` with the player-kill arguments (the last argument true) and suppress the death's own roll. Second, call `EnemyGiveExperience(self=monster, other=player, killExperience)`.
- AFK never hits a monster younger than 60 frames, on the assumption that its drop table is built a few frames after creation. That assumption is **not established**: no run recorded a fresh monster without a drop table, and 60 frames is AFK's margin.
- The death, `DropItem` and XP results above are **measured** R2/R2b/R2c (`5fafbea`, `57b4ad5`). Included because it is the "spawned thing interacts with the game" boundary.

---

## 7. Collision and movement

7.1 **Blocking with the game's invisible wall object.**
- AFK calls `instance_create_depth(x0, y0, -y1/2, Invisible_Wall_obj)` and sets `image_xscale = (x1-x0)/32` and `image_yscale = (y1-y0)/32`. This implies a 32×32 mask, which is **inferred**.
- It also sets `addToMinimap = true`, so the native minimap draws the outline.
- The blocker shows up in collision: `collision_point` finds it at the gate centre when closed and returns no instance when open. **measured** 2026-10-07 (DEFENSE_INPUT_VERIFICATION_20261007).
- Blockers appear on the minimap: **measured** (CITY_VERIFICATION).
- Source: CRS `StrongholdMap.inl` `Blocker` l.332-345.

7.2 **Whether the hero's own movement is stopped by `Invisible_Wall_obj` is not established in AFK's records.**
- No mouse or keyboard input was sent in the city and gate runs. The hero was teleported into the passage.
- The design says walls "block", and the path grid treats them as blocked.
- Which collision the player's movement code tests (this object, a parent, `solid`, a tile mask) was never examined.
- AFK sources: CITY_VERIFICATION_20261006 ("No mouse/keyboard game input was sent"), DEFENSE_INPUT_VERIFICATION_20261007.

7.3 **The path grid.**
- `gml_Script_PathFindControllerCreate`, with self and other set to the hero, rebuilds `global.pathGrid` (an mp_grid) from the room's blockers.
- It is sized from `room_width` / `room_height`, with `global.gridSize` cells of 16.
- AFK rebuilds it after every blocker change.
- A route of 3,600 px was found across a 9600² room, and the city's four spawn-to-square routes measured 2,340-3,064 px.
- **measured** R8b and CITY_VERIFICATION. Source: CRS `StrongholdMap.inl` `RebuildGrid` l.403-409, `Probe`.

7.4 **The grid counts a monster's own cells as taken.** `mp_grid_path` from a monster's own position never finds a way; from the next free cell (`mp_grid_get_cell == 0`) it does. **measured** R8b. Source: CRS `StrongholdMap.inl` `FreeNear` l.928-943.

7.5 **The game's own chase starts only near the hero.** For a monster further than about 1000 px, AFK walks it along an `mp_grid_path` (`path_add`, then `path_get_number` / `path_get_point_x` / `y`, re-searched every second) by writing `x` / `y` each frame. It moves a "flying" monster straight at the hero, writing `x` / `y` with no grid. **measured** for ground walks (R8, R8b). The straight flyer path is **inferred**: no flyer run was recorded, and "flying" is a flag in AFK's wave plan, not a game variable. Source: CRS `StrongholdMap.inl` `Approach`, `MoveToward` l.910-970.

7.6 **Writing `x` / `y` moves an instance with no collision test of its own.** AFK's steering and teleports rely on this. This is **inferred** from GameMaker semantics. AFK never tested a write into or through a blocker.

7.7 **A sealed hero makes the path search very expensive.**
- With the hero inside closed walls, every outside monster's search fails only after flooding the whole outside field.
- A 20-monster wave froze the game for about 20 s at fps 3.
- Fix: set the game's `pathFailed = true` on each new ground monster while the hero is sealed, then clear it four monsters a frame when sealing ends. The wave then held 60 fps throughout.
- An earlier design-doc line said "about a second"; it was **superseded** by the 20 s measurement.
- **measured** 2026-09-29. Source: `700ea67` (origin/claude/enclosed-no-search); CRS `LiveDefense.inl` l.394, l.458.

7.8 **Gates open and close by creating and destroying the blocker,** then discarding cached paths, rebuilding the grid and refreshing the minimap. Closing is refused while the hero or a monster is within 32 px of the passage. **measured** for all four gates (DEFENSE_INPUT_VERIFICATION_20261007). Source: CRS `StrongholdMap.inl` `ChangeGate` l.740-760.

7.9 **Minimap upkeep in a widened room.**
- Call `gml_Script_MinimapRefresh` with the hero as self, then set `objMinimap` `minimapFinalDirty = true`, `minimapCacheColor = -1` and `minimapCacheRevealed = -1`.
- To reveal the whole map, wait for `minimapDrawReady`, then `ds_grid_resize` and `ds_grid_clear(grid, 1)` the `minimapDiscoveredGrid` to `minimapCellsX` × `minimapCellsY`, and set `minimapRevealed`, `minimapMaskSurfacePopulated`, `minimapCacheRevealed` and `minimapFinalDirty`.
- The native loader can replace the grid with a 256×256 town grid after it is ready, so AFK re-checks dimensions every 60 frames.
- Do not replace the minimap instance mid-load.
- **measured**: the final grid was 385×385 (CITY_VERIFICATION_20261006).
- `ds_exists(grid, 5)` is the grid type check on this runner; passing type 1 with a grid ref returns false. That rests on a code comment, undated: **not established** outside it.
- Source: CRS `StrongholdMap.inl` `RefreshMinimap`, `RevealCityMap` l.347-401.

---

## 8. Rooms: travel and size

8.1 **Travel with the game's own `gml_Script_RoomGoto(room)`,** with self and other set to the `Controller_obj` instance. **measured** many times. Source: CRS `StrongholdMap.inl` `Goto` l.1085-1098; `ModuleMain.cpp` `goto` l.3458-3476.

8.2 **`Dev_10_rm` is an unused room you can repurpose.**
- It is 4000×4000. `room_set_width` / `room_set_height` on its index, called before travel, widened it to 9600×9600, and the path grid followed. A later city used 6144.
- A build with 12 buildings and 5 towers took 157 ms at 60 fps.
- The game never saves the hero there: closed there, it loads in town with exit code 0.
- **measured** R8, R8b and the product check. Source: `aae3cb9` (origin/claude/stronghold-map-v2).
- AFK's rule says never resize it while the hero is in it. The reason is **not established**. Source: CRS `AGENTS.md` l.57-63.

8.3 **AFK builds 20 frames after arrival,** once the hero exists, never in the room-change frame. AFK recipe, **inferred**. Source: CRS `StrongholdMap.inl` `Frame` l.1163-1166.

8.4 **`gml_Script_GetActTown` (self = hero)** returns the act's town room, which `room_get_name` can name. **inferred**, used in measured leave runs. Source: CRS `StrongholdMap.inl` `ActTown`.

---

## 9. Effects not observed to display

9.1 **`effect_create_depth` effects were not observed to display.**
- The call was `effect_create_depth(depth, 7 /*ef_spark*/, x, y, 1, 16769024)`, at monster depth − 1 in `Act_02_01`. It threw no error: R2b "made 400 sparks with no failures".
- In a visual check on 2026-09-27, none of 56 created effects was visible.
- **measured** as "not observed": there was no positive control in that session, so this does not show that effects cannot display. The R2b "no failures" result (`57b4ad5`) is **superseded** as evidence of display: it only meant no exception.
- AFK replaced effects with layer sprites plus texture prefetch.
- Whether they can display at all, and why these did not, is **not established**. Candidates include draw order, depth, and the effect system being off on this build.
- Source: `57b4ad5`; STRONGHOLD_DESIGN §6 B2 "R2c", recorded in commit `48c0ba0`; r2-defense-lab `DefenseLab.inl` `Effect` l.309-313.

9.2 **A game sprite from an unloaded texture group draws nothing, silently.** The layer element exists (`layer_sprite_exists` returns true), but nothing is drawn until prefetch. **measured** R1. See 3.1.

---

## 10. Calls that crash, hang or are unsafe

10.1 **Entering `Act_01_06` from code with `RoomGoto` crashed the game** (R8). AFK refuses to travel to Act zones by code at all. It also refuses rooms whose name contains `menu` or `loading`, and `init_rm` (`ResearchRoomTravelAllowed`). **measured** (crash). The other refusals are AFK policy. Source: STRONGHOLD_DESIGN §6 B2; CRS `plugin/include/AfkExpedition/RuntimeState.hpp` l.50-54.

10.2 **Reading a far-out protected handle crashes the game.** `PC_GetVariableGMLWrapper` on id 999999 crashed it. A freed neighbouring handle reads as 0. A gold amount mistaken for a handle crashed the anti-cheat module. **measured** 2026-09-17 and 2026-09-24. Source: CRS `docs/PHASE0_NOTES.md` l.50-56; `docs/DESIGN.md` 0.7.0 section.

10.3 **Experience calls.**
- `EnemyGiveExperience` with **no** argument crashes the game.
- `ExperienceUpdate` called directly verifies a hash and reports a mismatch through `ReportClient`. An instance ref passed as the amount was credited as about 260k.
- **measured**. Source: PHASE0_NOTES l.150-162.

10.4 **A struct held only in C++ `RValue`s gets garbage-collected.** A parsed struct used across frames was freed by the runner's GC, and frame 2 crashed. Anchor it in a global variable. **measured** 2026-09-17. Source: PHASE0_NOTES l.181-185; CRS `ModuleMain.cpp` l.1620.

10.5 **`asset_get_index` returns a typed reference (`VALUE_REF`), not a number,** on this runner. Kind checks for a number rejected every object. Validate with `object_exists` / `sprite_exists` / `room_exists`, or convert with `real()`. **measured** 2026-09-17. Source: PHASE0_NOTES l.60-61; CRS `ModuleMain.cpp` l.235-245.

10.6 **`instance_destroy` on a monster does not run the death path or `DropItem`.** **measured** 2026-09-17. Source: PHASE0_NOTES l.514-522.

10.7 **Disk I/O on the frame thread caused a 150 ms frame.** The game folder was under OneDrive or AV scanning, and file-time polls (`GetFileAttributesExW`) blocked. Watch files from a background thread. **measured** (ForgePact profile, 2026-09-28). Source: `33f889b` (origin/claude/frame-file-watch).

10.8 **Never let a draw or frame hook throw into the game.** AFK wraps each frame in try/catch: "never let the window take the frame down". AFK rule, **inferred**. Source: CRS `StrongholdWindow.inl` `Frame`.

10.9 **Unsafe buff types.** In R3, buff types 14-17 and 401 were found unsafe, so only a vetted list is used. **measured** (STRONGHOLD_DESIGN §10 evidence). The exact failure is not stated.

---

## 11. Superseded, contradicted, or date- and build-bound

| Earlier | Later | Where |
|---|---|---|
| R1 plan to draw from the cursor object's Draw GUI | The cursor object has no instance in town; anchor on `objColorBlindShader` Draw GUI End | `69003a1` header, then `930f13e` |
| Cursor: re-run `Screen_Cursor_obj` Draw GUI | No instance in play | `d97a7b6`, then `66a4df0` |
| Cursor: `window_set_cursor(cr_arrow)` over the window | The game resets it; draw `Cursor_spr` with `mouse_gui_scalar` instead | `66a4df0`, then `b358c33` |
| `effect_create_depth` "400 sparks, no failures" | 0 of 56 visible; use layer sprites | `57b4ad5`, then STRONGHOLD_DESIGN R2c |
| Art fit by the raw sprite bbox | Re-mask with tolerance 16 | `cce1545`, then `3be2c96` |
| One PNG per piece | F6 atlases cropped to sprites via surface (`city_*` keys scale to visible width) | `fb58b27` |
| Fallback ground `Fall_Ground_tileset2` | `Miner_Village_Ground_2_tileset` | `cce1545`, then `46f48ae` |
| Map 4000² room, walls 1800 | 9600² room, walls 4800; then the city at 6144²; the showcase is a 2688² citadel | `cce1545`, then `aae3cb9`, then `fb58b27`, `cc785ca` |
| Sealed-hero freeze "about a second" (design text) | Measured about 20 s; fixed with `pathFailed` | STRONGHOLD_DESIGN, then `700ea67` |
| Auto entry by direct `UiA*` script calls (broke mouse clicks) | `event_perform(ev_other, ev_user15)` on the `UI_Node_Parent_obj` node | 0.9.6, then `e380504` (0.9.7) |
| Gates all close on a wave | Per-gate open/close with F and an occupancy check | `09c8e96` |
| Window box alpha 0.9 | Opaque (labels showed through) | `91d7216` |
| Click answered in 13-15 s | 125-187 ms (IPC thread) | `7cea1ee` |

**Build and date bound.**
- Everything above is tied to the 2026-09-17..10-08 window. Builds are named in PHASE0_NOTES (`exe-281798144-pe6a9ed3ee-111c3000`, the pre-2026-09-18 build, which §10.2-10.6's 09-17 runs used) and in the 10-06 and 10-07 docs (`exe-281751552-pe6aaa6779-111b8000`).
- Event names are resolved by string from the executable (`gml_Object_objColorBlindShader_Draw_75`, `Screen_Cursor_obj`, `Menu_Controller_obj`). So are script names and object/variable names (`monsterHandleArray`, `minimap*`, `mouse_gui_scalar`, `zoneGenFound`, `pathFailed`). Any of them can move or change with a game update.
- The castle-share README (`f581067`) says explicitly that it does not claim compatibility with every build.

---

## 12. Open questions (for a flight / no-collision feature and custom item icons)

- Which collision test the player's movement actually uses (`Invisible_Wall_obj`, a parent such as a wall/solid parent, the `solid` flag, the path grid, or tile masks). AFK never walked the hero into a blocker (7.2).
- Whether the player's movement reads `global.pathGrid` at all, or only monsters do.
- Whether `x` / `y` writes on the player each frame survive the game's own movement step, and what happens when the hero ends inside a blocker.
- Whether `effect_create_*` effects can display at all (and why the 56 did not), and whether particle systems (`part_*`) display. Neither was tried.
- Whether an item's inventory icon can be swapped for a `sprite_add` sprite. AFK never drew item icons. The panel brief only says game item sprites can be drawn by name.
- Whether a `sprite_add` sprite survives a room change and texture-group flushes indefinitely. AFK keeps "kept" sprites for a session without reported trouble, but there is no explicit test.
- The real GPU cost of `font_add` and `sprite_add` (texture pages). It was never measured.
- Why the window installs at frame 660, and why `zoneGenFound` is set.

---

## (a) Facts about the game itself

The measured ones are folded into [`RUNTIME_DATA_MODELS.md` §22](../RUNTIME_DATA_MODELS.md#22-adding-our-own-content-art-drawing-input-spawning-and-blockers).

1. `asset_get_index` returns `VALUE_REF`, not a number; validate with `*_exists` (10.5). **measured**.
2. 254 dynamic texture groups are streamed by region. A sprite from an unloaded group draws nothing until `sprite_prefetch`; `npc_tex` is always loaded; `Guild_Master_NPC_spr` is in `act_2_tex`. `texturegroup_get_status` uses 0-3 (3.1, 3.2). **measured**.
3. YYToolkit's `EVENT_OBJECT_CALL` is `AURIE_UNAVAILABLE` on this YYC build (4.1). **measured**.
4. Town GUI event order ends with `objColorBlindShader` Draw GUI End (`_Draw_75`) (4.2). **measured**.
5. GUI size equals the monitor resolution (4.5). **measured**.
6. The game hides the Windows cursor (`cr_none`) and resets `window_set_cursor`. The cursor is `Cursor_spr`, drawn by `Menu_Controller_obj` at `global.mouse_gui_scalar`. `Screen_Cursor_obj` has no instance in play (5.7). **measured**.
7. Menu activation goes through `UI_Node_Parent_obj.activationFunc`. `event_perform(7, 25)` activates a node safely; calling the `UiA*` scripts directly broke later mouse input (5.8). **measured**.
8. `effect_create_depth` effects: none of 56 was observed to display, with no positive control (9.1). **measured** as "not observed"; the cause is **not established**.
9. Monster spawn: `enemyRarity`, `affixList` plus `enemyAffix` are set before stats build; `aggroRange` is reset to 300 at stats build (so it must be set a frame later; AFK also sets `distance` then, but a reset of `distance` was not observed); monsters self-delete in towns; the active box is about 650-850 px; appending ids to `Controller_obj.monsterHandleArray` / `monsterHandleArrayCount` after `ActivateDeactivateProps` keeps far monsters stepping (6.2-6.5). **measured**. Which routine rebuilds that array, and how often, is **inferred** (see 6.5 and the runtime reference's §11.3).
10. The monster sprite variables `enemy_*`, `enemy_corpse` and `shadow_sprite` (3.4). **measured** that prefetched monsters draw; that they fail without it is **inferred** from 3.1.
11. Room routines that decide town or zone behaviour: `CheckTown`, `RoomIsZone`, `GetAct`, `GetMonsterLevel`, `ReturnEnemyStats`, `GetRoomName` (6.7). **measured**.
12. `Invisible_Wall_obj`: scale per 32 px, `addToMinimap`, found by `collision_point` (7.1). **measured**. Whether it blocks the hero is not established.
13. Path grid: `PathFindControllerCreate` builds `global.pathGrid` with `global.gridSize` 16 from the room size; a monster's own cells count as taken; the per-monster `pathFailed` flag skips the search (7.3, 7.4, 7.7). **measured**.
14. `objMinimap` variables, `gml_Script_MinimapRefresh`, and the late discovery-grid replacement (7.9). **measured**, apart from `ds_exists` type 5.
15. `Dev_10_rm` is unused, 4000², resizable before entry, and never saved as the hero's location; entering `Act_01_06` from code crashes (8.2, 10.1). **measured**.
16. `RoomGoto` with the Controller as self; `GetActTown` (8.1, 8.4). **measured** / **inferred**.
17. Crash calls: a far-out protected handle; `EnemyGiveExperience()` with no argument; a C++-only struct across frames gets GC-freed. `ExperienceUpdate` reports a hash mismatch (10.2-10.4). **measured**.
18. NPC and sound asset names used: `Guild_Master_NPC_spr`, `Tristan_NPC_spr`, `Broker_NPC_spr`, `Witch_NPC_spr`, `Traveling_Merchant_NPC_spr`, `Orre_Npc_spr`, `Orre_Npc_Hammering_Up_spr`, `Hell_Spark_Particle_spr`, `Interacting_snd`, `Blacksmiths_Mallet_snd`, `Cursor_spr`, `Miner_Village_Ground_2_tileset`, the `Fall_Stone_Fence_*` sprites, `Fuji_Gate_01_spr`, `Battlefields_Portal_spr`, `Universal_Cannonball_spr` (2.x, 6.8). All are in `hs-game-sdk` except `Miner_Village_Ground_2_tileset` (the SDK has no tileset table).
19. The runner's window class is `YYGameMakerYY`; closing YYToolkit's console kills the game with 0xC000013A (5.11). **measured**.

## (b) Techniques and recipes specific to AFK

- The halo-proof art fit: re-mask with tolerance 16, bottom-centre origin, scale to the visible box (1.2, 1.3).
- Atlas-cell to sprite through a surface (1.4). The load budget of 2 per frame (1.6). Font size bucketing (1.7). The offline PNG checks (1.8).
- One layer per depth, named by depth, with a prefix-based cleanup; the fixed depth bands; drop shadows on a 997 layer (2.3-2.5, 2.8).
- Clock-driven `layer_sprite_index` animation; bbox-compensated placement of shared game sprites; projectile and beam layer sprites (2.9, 2.10, 2.12).
- Inline detour on the last GUI event, with draw-state save and restore, and re-drawing the game cursor last (4.1, 4.4, 5.7).
- `EVENT_WNDPROC` swallowing with release pairing, F-key gating on menu state, and atomics into the game frame (5.1, 5.2, 5.6).
- Offscreen panel screenshots through a surface (4.9). The 1920×1080 canvas scaled by min ratio (4.5).
- Layout JSON plus checked art manifest plus native placement and cleanup; the castle-share boundary in `examples/castle/README.md` @ `f581067`.
- Room-as-zone detours scoped to one room (6.7); keeping far monsters alive by appending to the active list (6.5); grid walks from the first free cell (7.4, 7.5); the sealed-hero `pathFailed` hold (7.7).
- Sprite-only NPC actors with proximity and identity receipts (6.8, 6.9).
- Window focus recovery through `AttachThreadInput` (5.10). Background file watching (10.7).

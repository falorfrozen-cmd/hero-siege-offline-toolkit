# ADR 0005 — UI buttons in ForgePact poll for a press instead of binding an activation

**Status:** accepted, 2026-09-28
**Supersedes:** nothing
**Context:** ForgePact #68, "Move all into the stash", which draws a **Move all**
button in the game's stash window, left of the backpack's Sort button. The
research is `ForgePact/docs/stash-move-research.md` (§ Static reading 3: the
button, § Live 1f results, § Live 1g results, § Decision `buttonRoute`), and
[ForgePact's guide](../submodules/ForgePact/instructions.md), Known Limitations
item 39, describes the button as built.

---

## The question

The game builds its menus from UI nodes: an object such as `UI_Button_Small_obj`,
created by the game's own `UiCreateNode`, named by its `uiNodeCallstack`, and
removed by `UiRemoveNode`. A node the game makes carries an *activation*, a
script the game runs when the node is clicked. ForgePact can make a node by
name the same way. How should a click on a node ForgePact made reach the
plugin?

The toolkit's rules narrow the answer before any option is weighed: nothing is
called through a hand-resolved address (AGENTS.md, "Never Call an Address You
Resolved by Hand"), and a hook that only swaps the script table is blind to
this build's direct calls (AGENTS.md, "Prove the Instrument Before Trusting a
Negative Result").

## The options

### Bind an activation to a game script and hook it: ruled out

The node is bound, by the game's own `UiSetActivationFunc`, to a game script
the plugin hooks by name, and the hook counts a call whose self is the
button's node as a press. It was measured in Live procedure 1f on the research
build, with `UiSetFloatingToFalse` as the bound script, chosen from a static
reading as the candidate that writes only a member of its argument.

The dispatch is what the static reading said it would be: a click runs the
node's user event 15 with self the node, other the stash window and one
argument, the node's `activationArgs`, and the hook saw that call. Then the
game ended, with no dialog. Its crash log names an unset bool argument in that
user event, inside the bound script: the script reads a member that belongs to
another UI object, which a button does not carry.

So a bound activation runs a game script in a context the game never runs it
in. Every candidate script has to be read and then proved on a live click, and
the failure is a crash on a player's machine rather than a button that does
nothing. A script written for the purpose cannot be added: ForgePact adds no
GML to the game.

### Leave the activation undefined and poll the mouse: chosen

The node is created with its activation left undefined (`UiCreateNode`'s fourth
argument undefined; `UiSetActivationFunc` is never called, and no script is
hooked for the button). On its frame tick the plugin calls three builtins by
name, `mouse_check_button_pressed`, `device_mouse_x_to_gui` and
`device_mouse_y_to_gui`, and counts a left press whose GUI point lies inside
the node's `bbox_left`/`top`/`right`/`bottom`, read by name at that frame, as
one press. It measures the same thing the game's own hit test does, from the
outside.

Live procedure 1g measured it on the 1f build, with the game running
throughout. A click on the unbound node left the game running with no dialog,
the routines armed in that session counted no call with the node as self
(the hover routine `UiSetFocus` aside, which the procedure allowed), and the
poll counted it once. That no game code at all runs for such a
click is the static reading of the node's click event (an undefined activation
runs nothing), not something the session measured. A click
on the window's background beside it counted only as a press elsewhere. A
positive control, the poll counting a click on the game's own Sort button,
passed in the same session. A tab switch kept the node, `UiRemoveNode` with the
stash window as self removed it, and the stash's own close destroyed a node
still listed, so a reopen found none.

## Decision

1. A button ForgePact draws in the game is a node it creates and removes
   through the game's own node routines, called by name, with **no
   activation**. No game script is bound to it and none is hooked for it.
2. A press is read on the plugin's frame tick: a left press inside the node's
   box, both read by name at that frame. The poll only records the press; the
   frame tick takes it under the same guard as the feature's hotkey (the game
   in front, the window listed, no modifier held), never inside a game script
   call.
3. The owner chose this route on 2026-09-28 after Live 1f's crash ("Test the
   watch route (Recommended)"), on the condition that Live 1g saw the click
   and nothing crashed, and it did.

## What this gives up

- The poll duplicates the game's hit test and does not share it. What the
  stash window's step does before a node's click event was not read, so a
  window that lets another node take the click inside the button's box would
  still count it as a press. Nothing like it has been observed.
- The button does nothing the game's own input handling would give it for
  free: no controller focus and no keyboard activation. The feature's hotkey
  stays for that reason.
- A press is read at the end of a frame, where Live 1f's Sort-button control
  and Live 1g measured that the read sees a scripted click; a click on the
  shipped button, rather than the research build's probe node, is Live
  procedure 2's `button-press` check to observe.

## Consequences

- **The press path says where each click went.** Since the player build has
  no probe, `stashmoveall`'s state line carries the button's counts (`button=`,
  `presses=`, `in_node=`, `outside=`, `unread=`, `errors=`, `taken=`, `dropped=`,
  `last_drop=`), after a loss as well, so a click that moved nothing names a
  poll that saw nothing, a press outside the box, a box that did not read, a
  poll that threw, or a press the guard dropped.
- **A node that cannot be made is not a failure of the feature.** It is
  reported once and never turns the mod off; the hotkey still works.
- **A later button follows the same shape.** Its creation, removal, poll and
  guard are the ones in `ForgePact/plugin/ModuleMain.cpp`'s `stashmoveall
  button` block, whose decisions live in the game-independent
  `ForgePact/plugin/include/ForgePact/StashMoveAllMod.hpp`. Binding an
  activation instead needs a new measurement of the script it binds, on a live
  click, with a positive control, before it can ship.

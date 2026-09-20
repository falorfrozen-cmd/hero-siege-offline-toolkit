"""`hs_selfcheck`: prove the instrument before anyone trusts what it reports.

`AGENTS.md` § "Prove the Instrument Before Trusting a Negative Result" was
written after 34 hooked call sites reported zero calls across confirmed,
observed events -- every zero measured the instrument, not the game. The same
trap is open here: `hs_status` reporting `not_running` is indistinguishable
from a process snapshot that never worked, and "the backup succeeded" is
indistinguishable from a copy nobody read back.

So each check below runs a **positive control**. `process_snapshot` does not
ask whether the game is absent; it asks whether the snapshot can see this
server's own process, which is certainly there. `backup_roundtrip` does not
inspect the save code, it drives the real `saves.backup` and `saves.restore`
against a fixture and compares bytes.

Two statuses are deliberately distinct. `skipped` always carries its reason,
and a check whose code raised is `fail` with the exception name -- never
`skipped`, because "we did not look" and "we looked and it broke" are the two
answers that must not be confused. The registry is a list so a later check is
appended with `register()` instead of by editing anything here, which is how
`screenshot_screen` was added.

**No check here writes anywhere but a temporary directory of its own.**
`hs_selfcheck` is annotated `readOnlyHint: true`, which is what a client uses to
auto-approve it without prompting, and it is the tool this server's own
instructions say to run first -- so it is the one most likely to run unattended.
`check_backup_roundtrip` builds its own fixture tree for exactly that reason. A
plugin ping used to live here too and broke the rule: it wrote into the live
install's `bp_ipc\\cmd.txt` and made the running game execute a command, and an
unconsumed one was left on disk for the game to run at its *next* start. That
control now lives in `hs_wait_ready` alone, which sends the identical ping, is
annotated honestly, and returns a far richer envelope.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import capture, launcher_bridge, results, saves

#: A check returns (status, detail). status is one of these three.
STATUSES = ("pass", "fail", "skipped")

CheckFn = Callable[[], tuple[str, str]]

_REGISTRY: list[tuple[str, CheckFn, bool]] = []


def register(name: str, run: CheckFn, positive_control: bool = False) -> None:
    """Append a check, from this module or any other.

    `positive_control=True` marks a check that points the instrument at
    something already known to be there. Those are the checks `summary.healthy`
    requires to have *passed*, not merely not failed -- a run where every check
    was skipped must never report healthy, because "reports itself armed while
    doing nothing" is the exact shape `AGENTS.md` § "Prove the Instrument"
    exists to catch, and this tool is the thing a caller trusts to catch it.
    """
    _REGISTRY.append((name, run, positive_control))


def registered() -> list[tuple[str, CheckFn, bool]]:
    return list(_REGISTRY)


def positive_controls() -> list[str]:
    return [name for name, _, control in _REGISTRY if control]


def _not_windows() -> str | None:
    if os.name != "nt":
        return (f"this check reads the Windows process table; os.name is "
                f"{os.name!r}, so it was not run")
    return None


def check_engine_import() -> tuple[str, str]:
    """The engine loads and still defines every name this server calls."""
    engine = launcher_bridge.load("hs_selfcheck")
    if results.is_refusal(engine):
        return "fail", engine["detail"]
    missing = [name for name in launcher_bridge.ENGINE_SYMBOLS
               if not hasattr(engine, name)]
    if missing:
        return "fail", (
            f"{launcher_bridge.ENGINE_RELPATH} loaded but no longer defines "
            f"{', '.join(missing)}. ENGINE_SYMBOLS is out of date with the "
            "ForgePact pointer.")
    return "pass", (
        f"{launcher_bridge.ENGINE_RELPATH} loaded; all "
        f"{len(launcher_bridge.ENGINE_SYMBOLS)} pinned names resolve "
        # str() first: a non-string constant here would raise TypeError and
        # report engine_import as failing for a reason that is not the one.
        f"(upstream revision {str(getattr(engine, 'UPSTREAM_REVISION', '?'))[:7]}).")


def check_process_snapshot() -> tuple[str, str]:
    """Positive control: the snapshot must be able to see this very process."""
    reason = _not_windows()
    if reason:
        return "skipped", reason
    engine = launcher_bridge.load("hs_selfcheck")
    if results.is_refusal(engine):
        return "fail", engine["detail"]
    rows = engine.processes()
    mine = os.getpid()
    if any(int(pid) == mine for pid, _ in rows):
        return "pass", (
            f"the process snapshot returned {len(rows)} rows and contains this "
            f"server's own pid {mine}, so a zero elsewhere means absence, not "
            "a blind instrument.")
    return "fail", (
        f"the process snapshot returned {len(rows)} rows but not this server's "
        f"own pid {mine}. Every game_state reading from it is unreliable.")


def check_eac_service() -> tuple[str, str]:
    """The anti-cheat service state is readable at all."""
    reason = _not_windows()
    if reason:
        return "skipped", reason.replace("process table", "service control manager")
    engine = launcher_bridge.load("hs_selfcheck")
    if results.is_refusal(engine):
        return "fail", engine["detail"]
    state = engine.eac_service_status()
    if state == "unknown":
        return "fail", (
            "the EasyAntiCheat service state could not be read, so hs_status "
            "cannot say whether anti-cheat is inactive.")
    return "pass", f"EasyAntiCheat service state reads as {state!r}."


def check_save_dir() -> tuple[str, str]:
    """The live save directory exists and holds at least one character."""
    source = saves.save_dir()
    if not source.is_dir():
        return "fail", (
            f"no save directory at {source}. Set HS_DRIVE_SAVE_DIR if the "
            "saves live somewhere else.")
    characters = sorted(p.name for p in source.glob(saves.CHARACTER_GLOB) if p.is_file())
    total = sum(1 for p in source.iterdir() if p.is_file())
    if not characters:
        return "fail", (
            f"{source} holds {total} file(s) but no {saves.CHARACTER_GLOB}, so "
            "it is not a Hero Siege save directory.")
    return "pass", (
        f"{source} holds {total} file(s), {len(characters)} of them character "
        f"saves ({saves.CHARACTER_GLOB}).")


def check_backup_roundtrip() -> tuple[str, str]:
    """Drive the real backup and restore over a fixture and compare bytes.

    Nothing here touches the live directory: the fixture is its own temp tree,
    passed to `saves` explicitly rather than through the environment.
    """
    fixture = {
        "herosiege1.hss": b"self-check character\x00\xff",
        "shop.ini": b"[shop]\nstock=1\n",
    }
    with tempfile.TemporaryDirectory(prefix="hs-drive-selfcheck-") as tmp:
        base = Path(tmp).resolve()
        source = base / "hs2saves"
        source.mkdir()
        for name, data in fixture.items():
            (source / name).write_bytes(data)
        root = base / "backups"

        def gate() -> tuple[str, str]:
            return "not_running", "the self-check fixture is not a live game."

        made = saves.backup("selfcheck", gate=gate, source=source, root=root)
        if results.is_refusal(made):
            return "fail", f"the fixture backup was refused ({made['reason']}): {made['detail']}"

        (source / "herosiege1.hss").write_bytes(b"damaged after the backup")
        (source / "shop.ini").unlink()

        done = saves.restore(made["backup_id"], made["backup_id"], gate=gate,
                             source=source, root=root)
        if results.is_refusal(done):
            return "fail", f"the fixture restore was refused ({done['reason']}): {done['detail']}"

        wrong = [name for name, data in fixture.items()
                 if not (source / name).is_file() or (source / name).read_bytes() != data]
        if wrong:
            return "fail", (
                f"the fixture restore reported success but {', '.join(wrong)} "
                "did not come back byte-identical.")
    return "pass", (
        f"a {len(fixture)}-file fixture backed up, was damaged, and restored "
        "byte-identical through the real backup and restore paths.")


def check_screenshot_screen() -> tuple[str, str]:
    """Positive control: capture the primary screen, which is certainly there.

    A flat *game* capture is uninterpretable on its own -- exclusive fullscreen
    may capture black, and so may a broken instrument. This check separates the
    two before anyone has to reason about one: if the desktop captures with more
    than one pixel value, Pillow and the display are working, and a flat game
    capture is about the game's window.
    """
    reason = _not_windows()
    if reason:
        return "skipped", reason.replace("reads the Windows process table",
                                         "captures the Windows desktop")
    available, why = capture.pillow_status()
    if not available:
        return "skipped", why
    image = capture.grab_bbox(None)
    colours = image.convert("RGB").getcolors(maxcolors=4)
    distinct = "more than 4" if colours is None else str(len(colours))
    if capture.is_flat(image):
        return "fail", (
            f"a {image.width}x{image.height} capture of the primary screen has "
            "only 1 distinct pixel value, so this machine cannot capture at "
            "all and no screenshot from it means anything.")
    return "pass", (
        f"a {image.width}x{image.height} capture of the primary screen holds "
        f"{distinct} distinct pixel values, so a flat game capture would be "
        "about the game's window rather than about this instrument.")


register("engine_import", check_engine_import)
# Both of these point the instrument at something certainly present -- this
# server's own process, and a fixture it just wrote. They are what `healthy`
# is allowed to rest on.
register("process_snapshot", check_process_snapshot, positive_control=True)
register("eac_service", check_eac_service)
register("save_dir", check_save_dir)
register("backup_roundtrip", check_backup_roundtrip, positive_control=True)
# The third control: the desktop is as certainly present as this process and the
# fixture, so a screenshot tool that cannot capture it is blind rather than
# unlucky.
register("screenshot_screen", check_screenshot_screen, positive_control=True)


def run_checks(tool: str = "hs_selfcheck") -> dict[str, Any]:
    """Run every registered check. One failing check never stops the rest."""
    rows: list[dict[str, str]] = []
    for name, run, _ in registered():
        try:
            status, detail = run()
        except Exception as exc:  # noqa: BLE001 - a raised check is a fail, not a crash
            status, detail = "fail", f"{type(exc).__name__}: {exc}"
        if status not in STATUSES:
            status, detail = "fail", f"the check returned status {status!r}, which is not one of {STATUSES}"
        rows.append({"name": name, "status": status, "detail": detail})

    counts = {status: sum(1 for row in rows if row["status"] == status) for status in STATUSES}
    controls = positive_controls()
    proven = [row["name"] for row in rows
              if row["name"] in controls and row["status"] == "pass"]
    # Not `failed == 0`: a run where every check was skipped has zero failures
    # and has proved nothing, and `healthy` is the field a caller branches on.
    healthy = bool(controls) and len(proven) == len(controls) and counts["fail"] == 0
    return results.ok(
        tool,
        checks=rows,
        summary={
            "total": len(rows),
            "passed": counts["pass"],
            "failed": counts["fail"],
            "skipped": counts["skipped"],
            "positive_controls": controls,
            "positive_controls_proven": proven,
            "healthy": healthy,
            "note": ("healthy requires every positive control to have passed, "
                     "not merely not failed: a skipped check is not a pass, and "
                     "an all-skipped run has proved nothing."),
        },
    )

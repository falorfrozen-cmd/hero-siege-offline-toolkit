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
answers that must not be confused. The registry is a list so the follow-on
hs-drive-mcp-game workorder appends `screenshot_screen` and `ipc_ping` with
`register()` instead of editing anything here.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import launcher_bridge, results, saves

#: A check returns (status, detail). status is one of these three.
STATUSES = ("pass", "fail", "skipped")

CheckFn = Callable[[], tuple[str, str]]

_REGISTRY: list[tuple[str, CheckFn]] = []


def register(name: str, run: CheckFn) -> None:
    """Append a check. Used by this module, and by the game workorder's."""
    _REGISTRY.append((name, run))


def registered() -> list[tuple[str, CheckFn]]:
    return list(_REGISTRY)


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
        f"(upstream revision {getattr(engine, 'UPSTREAM_REVISION', '?')[:7]}).")


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

        def gate() -> str:
            return "not_running"

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


register("engine_import", check_engine_import)
register("process_snapshot", check_process_snapshot)
register("eac_service", check_eac_service)
register("save_dir", check_save_dir)
register("backup_roundtrip", check_backup_roundtrip)


def run_checks(tool: str = "hs_selfcheck") -> dict[str, Any]:
    """Run every registered check. One failing check never stops the rest."""
    rows: list[dict[str, str]] = []
    for name, run in registered():
        try:
            status, detail = run()
        except Exception as exc:  # noqa: BLE001 - a raised check is a fail, not a crash
            status, detail = "fail", f"{type(exc).__name__}: {exc}"
        if status not in STATUSES:
            status, detail = "fail", f"the check returned status {status!r}, which is not one of {STATUSES}"
        rows.append({"name": name, "status": status, "detail": detail})

    counts = {status: sum(1 for row in rows if row["status"] == status) for status in STATUSES}
    return results.ok(
        tool,
        checks=rows,
        summary={
            "total": len(rows),
            "passed": counts["pass"],
            "failed": counts["fail"],
            "skipped": counts["skipped"],
            "healthy": counts["fail"] == 0,
            "note": "a skipped check is not a pass; read its detail for the reason.",
        },
    )

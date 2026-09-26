"""hs-drive's machine-wide game lease, across real processes.

The lease exists because two sessions in two worktrees drove the one Hero Siege
install at once. So the claims that matter are cross-process ones -- four
processes racing for it, a holder that crashed, a PID that came back as
something else -- and they are tested with real child processes, not with a
mocked lock. Every child runs `tools.hs_drive_mcp.lease` itself from the repo
root, with `HS_DRIVE_LEASE_DIR` pointed at this test's temporary directory, and
answers one JSON line per request on its stdout (the package never prints; the
child's own driver code does).

Both lock branches are exercised by whichever platform runs the suite:
`msvcrt.locking` on the owner's Windows machine, `fcntl.flock` on the ubuntu CI
runner. Nothing here needs a game, and nothing here reads or writes the real
`%LOCALAPPDATA%\\HSDriveMcp\\`: the lease, the saves, the backups and
`LOCALAPPDATA` itself (so ForgePact's `forgepact.json` is absent and no real
install is ever resolved) all point into the test's own temporary tree.

The baseline (`AGENTS.md` § "Mod Development Workflow") is
`test_no_lease_anywhere_lets_a_gated_tool_through_and_reports_lease_none`: with
no record at all, each of the six gated domain functions behaves exactly as it
did before the lease existed -- it reaches its own first gate -- and only adds
`lease: "none"`.

The thirteen tests the acceptance criterion counts by name carry comments
rather than docstrings, because `unittest -v` prints a docstring's first line
in place of the ` ... ok` suffix the criterion matches on.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import (  # noqa: E402
    charselect, checks, ipc, launch, launcher_bridge, lease, procs, saves, skills, stash)
from tools.hs_drive_mcp import input as input_module  # noqa: E402

#: How long any one child may take to answer before the test gives up on it.
CHILD_TIMEOUT_S = 60

#: A child that holds or releases the lease on request: one JSON request per
#: stdin line, one JSON result per stdout line, `{"op": "exit"}` to stop.
CHILD = textwrap.dedent("""
    import json, sys
    from tools.hs_drive_mcp import lease
    for line in sys.stdin:
        request = json.loads(line)
        op = request.pop("op")
        if op == "exit":
            break
        print(json.dumps(getattr(lease, op)(**request)), flush=True)
""")

#: A racer: says `ready`, spins until the `go` file exists, acquires, prints
#: the result, then stays alive until its stdin closes -- so the winner is a
#: live holder while the others are still acquiring.
RACER = textwrap.dedent("""
    import json, os, sys, time
    from tools.hs_drive_mcp import lease
    label, go = sys.argv[1], sys.argv[2]
    print("ready", flush=True)
    while not os.path.exists(go):
        time.sleep(0.001)
    print(json.dumps(lease.acquire(label)), flush=True)
    sys.stdin.read()
""")


def not_running_gate():
    return "not_running", "the test gate says no game is running."


def running_gate():
    return "running", "the test gate says 1 hero_siege.exe process is live: [4242]."


class Recorder:
    """A stand-in for the first thing a gated tool touches. Records that it
    was reached and answers like the real one would when nothing is there."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.answer


class Child:
    """One `CHILD` process, driven request by request."""

    def __init__(self, env: dict[str, str]):
        self.proc = subprocess.Popen(
            [sys.executable, "-c", CHILD], cwd=str(ROOT), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            encoding="utf-8")

    @property
    def pid(self) -> int:
        return self.proc.pid

    def call(self, op: str, **kwargs):
        self.proc.stdin.write(json.dumps({"op": op, **kwargs}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError(f"child {self.pid} answered nothing to {op}; "
                                 f"exit code {self.proc.poll()}")
        return json.loads(line)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"op": "exit"}) + "\n")
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=CHILD_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream and not stream.closed:
                stream.close()


class LeaseBase(unittest.TestCase):
    """A temporary lease dir, save dir, backup root and `LOCALAPPDATA`."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hs-drive-lease-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.lease_dir = self.root / "lease"
        self.live = self.root / "hs2saves"
        self.live.mkdir()
        (self.live / "herosiege1.hss").write_bytes(b"fixture character")
        (self.live / "shop.ini").write_bytes(b"[shop]\n")
        self.backups = self.root / "save-backups"
        self.appdata = self.root / "appdata"
        self.appdata.mkdir()
        self.env = {
            "HS_DRIVE_LEASE_DIR": str(self.lease_dir),
            "HS_DRIVE_SAVE_DIR": str(self.live),
            "HS_DRIVE_BACKUP_DIR": str(self.backups),
            "LOCALAPPDATA": str(self.appdata),
        }
        self.enterContext(patch.dict(os.environ, self.env))
        # "Held by me" is this process's memory; every test starts holding
        # nothing, and whatever a test acquires is forgotten after it.
        self.enterContext(patch.object(lease, "_HELD_ID", None))

    def child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.env)
        env["PYTHONIOENCODING"] = "utf-8"
        return env

    def child(self) -> Child:
        child = Child(self.child_env())
        self.addCleanup(child.close)
        return child

    def held_by_a_child(self, label: str = "other-live-1"):
        child = self.child()
        taken = child.call("acquire", label=label)
        self.assertTrue(taken["ok"], taken)
        return child, taken

    def record(self) -> dict:
        return json.loads((self.lease_dir / lease.RECORD_NAME).read_text(encoding="utf-8"))

    def gated_calls(self, touched: dict[str, Recorder]):
        """The gated domain functions - the six the lease shipped with, the
        five skill tools and the five stash and bag tools - each wired so the first thing it would touch after
        the lease is a `Recorder` in `touched`."""
        def launch_call():
            with patch.object(procs, "load_engine", touched["hs_launch"]):
                return launch.hs_launch(timeout_s=1)

        def stop_call():
            return launch.hs_stop_game(gate=touched["hs_stop_game"], timeout_s=1)

        def command_call():
            return ipc.send(["ping"], gate=touched["hs_command"], timeout_s=1)

        def input_call():
            return input_module.inject([{"type": "wait", "ms": 1}],
                                       gate=touched["hs_input"])

        def select_call():
            with patch.object(procs, "gate", touched["hs_select_character"]):
                return charselect.hs_select_character(slot=1, timeout_s=1)

        def restore_call():
            return saves.restore("no-such-backup", "no-such-backup",
                                 gate=touched["hs_saves_restore"])

        # The five skill tools (`hs-drive-skill-actions`). Three reach the
        # process gate first; bind and reset refuse `route_not_measured`
        # without reaching anything, so their recorder stands in for the IPC
        # send and the injection, which must stay untouched either way.
        def skills_status_call():
            return skills.hs_skills_status(gate=touched["hs_skills_status"])

        def skill_cast_call():
            return skills.hs_skill_cast(81, slot="0,0", timeout_s=1,
                                        gate=touched["hs_skill_cast"])

        def talent_allocate_call():
            return skills.hs_talent_allocate(244, "no-such-backup",
                                             gate=touched["hs_talent_allocate"])

        def untouched(tool, call):
            def wrapped():
                with patch.object(skills.ipc, "send", touched[tool]), \
                     patch.object(skills.input_module, "inject", touched[tool]):
                    return call()
            return wrapped

        # The five stash and bag tools (`hs-drive-stash-bag-actions`). Each
        # reaches the process gate first; the IPC send and the injection are
        # the same recorder, so a send before the gate would count too.
        def stashed(tool, call):
            def wrapped():
                with patch.object(stash.ipc, "send", touched[tool]), \
                     patch.object(stash.input_module, "inject", touched[tool]):
                    return call(touched[tool])
            return wrapped

        return {"hs_launch": launch_call, "hs_stop_game": stop_call,
                "hs_command": command_call, "hs_input": input_call,
                "hs_select_character": select_call,
                "hs_saves_restore": restore_call,
                "hs_skills_status": skills_status_call,
                "hs_skill_cast": skill_cast_call,
                "hs_talent_allocate": talent_allocate_call,
                "hs_skill_bind": untouched("hs_skill_bind", lambda: skills.hs_skill_bind(
                    "0,6", "shadowBolt", "no-such-backup")),
                "hs_talent_reset": untouched("hs_talent_reset", lambda: skills.hs_talent_reset(
                    "no-such-backup")),
                "hs_give_item": stashed("hs_give_item", lambda gate: stash.hs_give_item(
                    "bag", "0-0-209564349884-14", "no-such-backup", gate=gate)),
                "hs_stash_open": stashed("hs_stash_open", lambda gate: stash.hs_stash_open(
                    "no-such-backup", timeout_s=1, gate=gate)),
                "hs_stash_close": stashed("hs_stash_close", lambda gate: stash.hs_stash_close(gate=gate)),
                "hs_stash_tab": stashed("hs_stash_tab", lambda gate: stash.hs_stash_tab(
                    "materials", "no-such-backup", gate=gate)),
                "hs_bag_tab": stashed("hs_bag_tab", lambda gate: stash.hs_bag_tab(
                    "materials", "no-such-backup", gate=gate))}

    #: The two tools whose first touch is nothing at all: they refuse
    #: `route_not_measured` whoever holds the lease, and never send.
    NEVER_TOUCH = ("hs_skill_bind", "hs_talent_reset")

    @staticmethod
    def recorders() -> dict[str, Recorder]:
        return {
            "hs_launch": Recorder((None, procs.ENGINE_MISSING,
                                   "the test says the engine source is absent.")),
            "hs_stop_game": Recorder(not_running_gate()),
            "hs_command": Recorder(not_running_gate()),
            "hs_input": Recorder(not_running_gate()),
            "hs_select_character": Recorder(not_running_gate()),
            "hs_saves_restore": Recorder(running_gate()),
            "hs_skills_status": Recorder(not_running_gate()),
            "hs_skill_cast": Recorder(not_running_gate()),
            "hs_talent_allocate": Recorder(not_running_gate()),
            "hs_skill_bind": Recorder({"ok": True, "refused": False}),
            "hs_talent_reset": Recorder({"ok": True, "refused": False}),
            "hs_give_item": Recorder(not_running_gate()),
            "hs_stash_open": Recorder(not_running_gate()),
            "hs_stash_close": Recorder(not_running_gate()),
            "hs_stash_tab": Recorder(not_running_gate()),
            "hs_bag_tab": Recorder(not_running_gate()),
        }


class RaceAndStaleTests(LeaseBase):
    def test_concurrent_acquire_from_four_processes_has_one_winner(self):
        # Four real processes, released at once by a file appearing; the OS
        # lock must let exactly one of them take the lease.
        go = self.root / "go"
        racers = []
        for index in range(4):
            proc = subprocess.Popen(
                [sys.executable, "-c", RACER, f"racer-{index}", str(go)],
                cwd=str(ROOT), env=self.child_env(), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, text=True, encoding="utf-8")
            racers.append(proc)

        def finish():
            for proc in racers:
                if proc.poll() is None:
                    proc.stdin.close()
                    try:
                        proc.wait(timeout=CHILD_TIMEOUT_S)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                proc.stdout.close()
        self.addCleanup(finish)

        for proc in racers:
            self.assertEqual(proc.stdout.readline().strip(), "ready")
        go.write_bytes(b"")
        outcomes = [json.loads(proc.stdout.readline()) for proc in racers]

        winners = [o for o in outcomes if o["ok"]]
        losers = [o for o in outcomes if not o["ok"]]
        self.assertEqual(len(winners), 1, outcomes)
        self.assertEqual([o["reason"] for o in losers], ["lease_held"] * 3, outcomes)
        winner = winners[0]
        for loser in losers:
            self.assertIn(winner["label"], loser["detail"])
            self.assertIn(winner["taken_utc"], loser["detail"])
            self.assertEqual(loser["holder_label"], winner["label"])
        self.assertEqual(self.record()["label"], winner["label"])
        self.assertEqual(self.record()["holder"]["pid"], winner["holder"]["pid"])

    def test_a_stale_lease_from_a_dead_process_is_recovered_on_acquire(self):
        # A holder that dies without releasing leaves a `held` record; its
        # process is gone, so the record is stale, gates nothing, and the next
        # acquire takes it and says so.
        child = self.child()
        taken = child.call("acquire", label="crashed-live-1")
        self.assertTrue(taken["ok"], taken)
        # Positive control first: while it runs, it is a live holder.
        self.assertEqual(lease.status()["state"], lease.HELD)
        child.proc.kill()
        child.proc.wait(timeout=CHILD_TIMEOUT_S)

        report = lease.status()
        self.assertEqual(report["state"], lease.STALE, report)
        self.assertEqual(report["record"]["holder"]["pid"], child.pid)
        self.assertIsNone(lease.guard("hs_command"))
        released = lease.release()
        self.assertEqual(released["reason"], "lease_not_held")
        self.assertIn("stale", released["detail"])

        mine = lease.acquire("recovering-live-2")
        self.assertTrue(mine["ok"], mine)
        self.assertTrue(mine["recovered_stale"])
        self.assertEqual(mine["previous"]["outcome"], "stale")
        self.assertEqual(mine["previous"]["label"], "crashed-live-1")
        self.assertEqual(mine["previous"]["pid"], child.pid)
        self.assertEqual(lease.status()["state"], lease.HELD_BY_ME)

    def test_same_pid_with_a_different_start_is_stale(self):
        # PID reuse: the recorded PID is this very (live) process, but the
        # process wearing it now was created at a different moment, so it is
        # not the holder.
        taken = lease.acquire("reused-pid-live-1")
        self.assertTrue(taken["ok"], taken)
        recorded = taken["holder"]["pid_start"]
        self.assertEqual(taken["holder"]["pid"], os.getpid())
        # Forget holding it, so the record is judged by process identity alone.
        lease._HELD_ID = None
        # Positive control: same PID, same creation stamp -- alive.
        self.assertEqual(lease.status()["state"], lease.HELD)
        self.assertIsNotNone(recorded, "this platform should have a start-time reader")
        with patch.object(lease, "process_start_for",
                          lambda pid: f"{recorded}-but-later"):
            self.assertEqual(lease.status()["state"], lease.STALE)
            self.assertIsNone(lease.guard("hs_launch"))


class GateTests(LeaseBase):
    def test_no_lease_anywhere_lets_a_gated_tool_through_and_reports_lease_none(self):
        # Baseline: no record at all. Each gated tool reaches its own first
        # gate, answers what it answered before the lease existed, and adds
        # `lease: "none"`. No record is created by asking.
        touched = self.recorders()
        expected = {"hs_launch": "engine_source_missing",
                    "hs_command": "game_not_running",
                    "hs_input": "game_not_running",
                    "hs_select_character": "game_not_running",
                    "hs_saves_restore": "game_running",
                    "hs_skills_status": "game_not_running",
                    "hs_skill_cast": "game_not_running",
                    "hs_talent_allocate": "game_not_running",
                    "hs_skill_bind": "route_not_measured",
                    "hs_talent_reset": "route_not_measured",
                    "hs_give_item": "game_not_running",
                    "hs_stash_open": "game_not_running",
                    "hs_stash_close": "game_not_running",
                    "hs_stash_tab": "game_not_running",
                    "hs_bag_tab": "game_not_running"}
        for tool, call in self.gated_calls(touched).items():
            with self.subTest(tool=tool):
                result = call()
                if tool in self.NEVER_TOUCH:
                    self.assertEqual(touched[tool].calls, 0, (tool, result))
                else:
                    self.assertEqual(touched[tool].calls >= 1, True, (tool, result))
                self.assertEqual(result.get("lease"), "none", result)
                if tool == "hs_stop_game":
                    self.assertTrue(result["ok"], result)
                    self.assertTrue(result["exited"], result)
                else:
                    self.assertEqual(result.get("reason"), expected[tool], result)
        self.assertFalse((self.lease_dir / lease.RECORD_NAME).exists())

    def test_each_gated_tool_refuses_lease_held_before_touching_the_game(self):
        # Another live process holds the lease: every gated tool refuses
        # `lease_held` and none of them reaches its first gate.
        self.held_by_a_child()
        touched = self.recorders()
        for tool, call in self.gated_calls(touched).items():
            with self.subTest(tool=tool):
                result = call()
                self.assertEqual(result.get("reason"), "lease_held", result)
                self.assertEqual(result["tool"], tool)
                self.assertEqual(touched[tool].calls, 0,
                                 f"{tool} touched the game before asking the lease")

    def test_a_refusal_names_the_holder_label_and_when_it_took_the_lease(self):
        child, taken = self.held_by_a_child("issue-14-live-2")
        refused = ipc.send(["ping"], gate=Recorder(running_gate()))
        self.assertEqual(refused["reason"], "lease_held")
        self.assertIn(f"held by issue-14-live-2 (pid {child.pid}) since "
                      f"{taken['taken_utc']}", refused["detail"])
        self.assertEqual(refused["holder_label"], "issue-14-live-2")
        self.assertEqual(refused["holder_pid"], child.pid)
        self.assertEqual(refused["taken_utc"], taken["taken_utc"])
        # hs_lease_acquire without force refuses with the same detail.
        again = lease.acquire("second-live-1")
        self.assertEqual(again["reason"], "lease_held")
        self.assertIn(f"since {taken['taken_utc']}", again["detail"])

    def test_read_only_tools_never_refuse_while_another_process_holds(self):
        self.held_by_a_child()
        report = lease.status()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["state"], lease.HELD)
        answers = {
            "hs_lease_status": report,
            "hs_saves_list": saves.list_backups(),
            "hs_saves_inspect": saves.inspect_backup("no-such-backup"),
            "hs_ipc_tail": ipc.tail(5),
        }
        # hs_selfcheck's round trip drives the real backup and restore paths
        # inside a temporary directory; the lease must not reach it.
        status, detail = checks.check_backup_roundtrip()
        self.assertEqual(status, "pass", detail)
        # hs_wait_ready sends one ping and is deliberately not gated: the
        # ping must reach the channel code, not stop at the lease.
        sends = []
        real_send = ipc.send

        def spy(*args, **kwargs):
            sends.append(kwargs.get("lease_checked"))
            return real_send(*args, **kwargs)
        engine = MagicMock()
        engine.launch_status.return_value = {}
        exe = self.root / "game" / "Hero_Siege.exe"
        (exe.parent / "bp_ipc").mkdir(parents=True)
        exe.write_bytes(b"fixture")
        with patch.object(procs, "load_engine", return_value=(engine, "", "")), \
             patch.object(launcher_bridge, "read_config",
                          return_value={"game_exe": str(exe)}), \
             patch.object(launch.ipc, "send", spy), \
             patch.object(procs, "game_pids", return_value=[4242]):
            answers["hs_wait_ready"] = launch.hs_wait_ready(timeout_s=1,
                                                            gate=running_gate)
        self.assertEqual(sends, [True])
        for tool, answer in answers.items():
            with self.subTest(tool=tool):
                self.assertNotIn(answer.get("reason"),
                                 ("lease_held", "lease_unavailable"), answer)
                self.assertNotIn("lease", answer)


class ForceAndSavesTests(LeaseBase):
    def test_force_takes_over_and_records_the_previous_holder(self):
        child, taken = self.held_by_a_child("abandoned-live-1")
        mine = lease.acquire("owner-said-take-it", slot=3, force=True)
        self.assertTrue(mine["ok"], mine)
        self.assertEqual(mine["took_over_from"]["label"], "abandoned-live-1")
        self.assertEqual(mine["took_over_from"]["pid"], child.pid)
        self.assertEqual(mine["took_over_from"]["taken_utc"], taken["taken_utc"])
        self.assertIn("restore_pending", mine["took_over_from"])
        record = self.record()
        self.assertEqual(record["previous"]["outcome"], "taken_over")
        self.assertEqual(record["previous"]["label"], "abandoned-live-1")
        self.assertEqual(record["slot"], 3)
        self.assertEqual(lease.status()["state"], lease.HELD_BY_ME)
        # The old holder is now the one refused, from its own process.
        refused = child.call("guard", tool="hs_command")
        self.assertEqual(refused["reason"], "lease_held")
        self.assertIn("owner-said-take-it", refused["detail"])
        released = child.call("release")
        self.assertEqual(released["reason"], "lease_held")
        # And re-acquiring what this process already holds is not a takeover.
        again = lease.acquire("owner-said-take-it", slot=4)
        self.assertTrue(again["already_held"], again)
        self.assertIsNone(again["took_over_from"])
        self.assertEqual(self.record()["slot"], 4)
        self.assertEqual(self.record()["taken_utc"], mine["taken_utc"])

    def test_backup_records_its_id_and_sets_restore_pending(self):
        # Negative control: a backup by a process that holds nothing writes
        # no lease record at all.
        before = saves.backup("unleased", gate=not_running_gate)
        self.assertTrue(before["ok"], before)
        self.assertFalse((self.lease_dir / lease.RECORD_NAME).exists())

        self.assertTrue(lease.acquire("backup-live-1")["ok"])
        made = saves.backup("baseline", gate=not_running_gate)
        self.assertTrue(made["ok"], made)
        record = self.record()
        self.assertEqual(record["backup_id"], made["backup_id"])
        self.assertTrue(record["restore_pending"])
        # The self-check's fixture round trip is not the session's backup.
        status, detail = checks.check_backup_roundtrip()
        self.assertEqual(status, "pass", detail)
        self.assertEqual(self.record()["backup_id"], made["backup_id"])

    def test_restore_of_the_recorded_backup_clears_restore_pending(self):
        self.assertTrue(lease.acquire("restore-live-1")["ok"])
        first = saves.backup("first", gate=not_running_gate)
        time.sleep(1.1)  # backup ids are to the second
        second = saves.backup("second", gate=not_running_gate)
        self.assertEqual(self.record()["backup_id"], second["backup_id"])

        # A restore of a different backup leaves the debt, and says so.
        other = saves.restore(first["backup_id"], first["backup_id"],
                              gate=not_running_gate)
        self.assertTrue(other["ok"], other)
        self.assertEqual(other["lease"], "held")
        self.assertTrue(other["lease_restore_pending"])
        self.assertIn(second["backup_id"], other["lease_detail"])
        self.assertTrue(self.record()["restore_pending"])

        done = saves.restore(second["backup_id"], second["backup_id"],
                             gate=not_running_gate)
        self.assertTrue(done["ok"], done)
        self.assertFalse(done["lease_restore_pending"])
        self.assertFalse(self.record()["restore_pending"])

        # After a release, an un-leased restore of the recorded backup still
        # settles it on the released record.
        third = saves.backup("third", gate=not_running_gate)
        self.assertTrue(lease.release()["ok"])
        self.assertTrue(self.record()["restore_pending"])
        late = saves.restore(third["backup_id"], third["backup_id"],
                             gate=not_running_gate)
        self.assertEqual(late["lease"], "none")
        self.assertFalse(late["lease_restore_pending"])
        self.assertFalse(self.record()["restore_pending"])
        self.assertEqual(self.record()["state"], "released")

    def test_release_while_restore_pending_succeeds_and_says_so(self):
        self.assertTrue(lease.acquire("pending-live-1")["ok"])
        made = saves.backup("baseline", gate=not_running_gate)
        released = lease.release()
        self.assertTrue(released["ok"], released)
        self.assertTrue(released["restore_pending"])
        self.assertIn(made["backup_id"], released["warning"])
        record = self.record()
        self.assertEqual(record["state"], "released")
        self.assertTrue(record["released_utc"])
        # The next session sees the debt, from status and from its acquire.
        status = lease.status()
        self.assertEqual(status["state"], lease.FREE)
        self.assertTrue(status["last"]["restore_pending"])
        self.assertIn(made["backup_id"], status["warning"])
        child = self.child()
        taken = child.call("acquire", label="next-live-1")
        self.assertTrue(taken["ok"], taken)
        self.assertIn(made["backup_id"], taken["warning"])
        self.assertEqual(taken["previous"]["outcome"], "released")
        self.assertTrue(taken["previous"]["restore_pending"])
        # A second release by a process holding nothing is not a release.
        self.assertEqual(lease.release()["reason"], "lease_held")


class RecordTests(LeaseBase):
    def test_an_unreadable_record_refuses_gated_tools_and_never_reads_as_free(self):
        self.lease_dir.mkdir()
        path = self.lease_dir / lease.RECORD_NAME
        for garbage in (b"{not json", b'{"schema": "something-else/1"}', b"\xff\xfe"):
            with self.subTest(garbage=garbage):
                path.write_bytes(garbage)
                report = lease.status()
                self.assertTrue(report["ok"])
                self.assertEqual(report["state"], lease.UNAVAILABLE, report)
                self.assertNotEqual(report["state"], lease.FREE)
                self.assertIn(str(path), report["detail"])
                touched = self.recorders()
                for tool, call in self.gated_calls(touched).items():
                    result = call()
                    self.assertEqual(result.get("reason"), "lease_unavailable",
                                     (tool, result))
                    self.assertEqual(touched[tool].calls, 0, tool)
                self.assertEqual(lease.acquire("plain-live-1")["reason"],
                                 "lease_unavailable")
                self.assertEqual(lease.release()["reason"], "lease_unavailable")
        forced = lease.acquire("forced-live-1", force=True)
        self.assertTrue(forced["ok"], forced)
        self.assertTrue(forced["replaced_unreadable"])
        self.assertEqual(lease.status()["state"], lease.HELD_BY_ME)

    def test_lease_dir_honours_the_environment_override(self):
        self.assertEqual(lease.lease_dir(), self.lease_dir)
        self.assertEqual(lease.record_path(), self.lease_dir / "lease.json")
        without = {key: value for key, value in os.environ.items()
                   if key != "HS_DRIVE_LEASE_DIR"}
        with patch.dict(os.environ, without, clear=True):
            self.assertEqual(lease.lease_dir(), self.appdata / "HSDriveMcp")
        # Taking and releasing writes exactly the record and the lock file,
        # both inside the override, and leaves no temporary file behind.
        self.assertTrue(lease.acquire("override-live-1")["ok"])
        self.assertTrue(lease.release()["ok"])
        self.assertEqual(sorted(p.name for p in self.lease_dir.iterdir()),
                         ["lease.json", "lease.lock"])
        self.assertFalse((self.appdata / "HSDriveMcp").exists())

    def test_status_reports_a_dll_swapped_since_the_lease_was_taken(self):
        # Not one of the counted thirteen: the "keep the dll, it will be
        # swapped" clash, made visible by hashing the installed plugin again.
        exe = self.root / "game" / "Hero_Siege.exe"
        dll = exe.parent / "mods" / "aurie" / "BloodPactPlugin.dll"
        dll.parent.mkdir(parents=True)
        exe.write_bytes(b"fixture")
        dll.write_bytes(b"plugin build one")
        with patch.object(launcher_bridge, "read_config",
                          return_value={"game_exe": str(exe)}):
            taken = lease.acquire("dll-live-1")
            self.assertEqual(taken["dll_status"], "hashed")
            self.assertEqual(taken["dll_sha256"], saves.file_sha256(dll))
            self.assertFalse(lease.status()["dll_changed_since_taken"])
            dll.write_bytes(b"plugin build two")
            report = lease.status()
        self.assertTrue(report["dll_changed_since_taken"])
        self.assertEqual(report["dll_sha256_now"], saves.file_sha256(dll))
        # Without a panel configuration the reason is named, not guessed.
        self.assertEqual(lease.status()["dll_status_now"], "forgepact_config_missing")


def _stdio_skip_reason():
    try:
        from tests.test_hs_drive_mcp_server import SKIP_REASON
    except Exception as exc:  # noqa: BLE001 - reported as the skip reason
        return f"tests.test_hs_drive_mcp_server did not import: {exc}"
    return SKIP_REASON


STDIO_SKIP = _stdio_skip_reason()


async def two_servers(environment):
    """Server A takes the lease; server B, a second real stdio process on the
    same lease directory, is asked for status, an acquire and a command."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from tests.test_hs_drive_mcp_server import SERVER_ARGV

    def server():
        return stdio_client(StdioServerParameters(
            command="py", args=SERVER_ARGV, cwd=str(ROOT), env=environment))

    async with server() as (read_a, write_a):
        async with ClientSession(read_a, write_a) as a:
            await a.initialize()
            taken = await a.call_tool("hs_lease_acquire", {"label": "stdio-a"})
            async with server() as (read_b, write_b):
                async with ClientSession(read_b, write_b) as b:
                    await b.initialize()
                    status = await b.call_tool("hs_lease_status", {})
                    acquire = await b.call_tool("hs_lease_acquire", {"label": "stdio-b"})
                    command = await b.call_tool("hs_command", {"lines": ["ping"]})
            released = await a.call_tool("hs_lease_release", {})
    return {name: result.structured_content for name, result in (
        ("taken", taken), ("status", status), ("acquire", acquire),
        ("command", command), ("released", released))}


class StdioTests(unittest.TestCase):
    @unittest.skipIf(STDIO_SKIP is not None, STDIO_SKIP or "")
    def test_two_stdio_servers_the_second_is_refused(self):
        from tests.test_hs_drive_mcp_server import fixture_environment
        temp = tempfile.TemporaryDirectory(prefix="hs-drive-lease-stdio-")
        self.addCleanup(temp.cleanup)
        answers = asyncio.run(two_servers(fixture_environment(Path(temp.name).resolve())))
        self.assertTrue(answers["taken"]["ok"], answers)
        self.assertEqual(answers["status"]["state"], "held", answers)
        self.assertEqual(answers["status"]["record"]["label"], "stdio-a")
        self.assertEqual(answers["acquire"]["reason"], "lease_held", answers)
        # The guard runs before the game gate: no game, and still lease_held.
        self.assertEqual(answers["command"]["reason"], "lease_held", answers)
        self.assertTrue(answers["released"]["ok"], answers)


if __name__ == "__main__":
    unittest.main()

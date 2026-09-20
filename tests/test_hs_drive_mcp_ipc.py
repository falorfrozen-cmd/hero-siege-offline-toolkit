"""ForgePact's file IPC, driven against a fake consumer instead of the game.

The plugin's channel is two files in `bp_ipc\\`: the game reads `cmd.txt`,
**deletes it**, runs each line, and appends every reply to an append-only
`out.txt` that other features are writing to at the same time. Both halves of
that are where a naive driver goes wrong, so both are tested against a thread
that behaves the way the plugin does:

* the reply is the **byte delta** after the pre-send length, not the last N
  lines -- `ForgePact/tools/ipc.ps1` says why, and this suite proves it by
  putting unrelated content in `out.txt` before the send and asserting it is
  excluded;
* "the game consumed it" is `cmd.txt` disappearing, which is the same signal
  ForgePact's own panel uses for plugin readiness. A send that was never
  consumed is a refusal naming the timeout, never a silent empty reply.

Nothing here needs Windows, Pillow, the MCP SDK or a ForgePact checkout: the
gate is injected and every path is a temporary directory, so this suite runs in
full on CI's `ubuntu-latest` as well as on the owner's machine. That is
deliberate -- it is the only one of the three new suites that can, and the IPC
rules are the ones most likely to be broken by an edit somewhere else.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hs_drive_mcp import ipc, launcher_bridge, results  # noqa: E402


def running_gate():
    return "running", "1 hero_siege.exe process(es) are live: [4242]."


def not_running_gate():
    return "not_running", "the process snapshot returned 91 rows and none of them is hero_siege.exe."


def unknown_gate():
    return "unknown", "the Windows process snapshot could not be created or read."


def engine_missing_gate():
    return "engine_missing", "ForgePact/src/offline_launcher.py was not found."


class IpcFixture(unittest.TestCase):
    """A `bp_ipc\\` beside a fake executable, with the settle poll shortened.

    The settle loop is the one place this module deliberately sleeps: it waits
    for `out.txt` to stop growing, because a slow command appends for a while
    after `cmd.txt` is consumed. Shrinking the poll keeps the suite fast without
    removing the behaviour under test -- four consecutive unchanged reads are
    still required.
    """

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="hs-drive-ipc-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.exe = self.base / "bin" / "Hero_Siege.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"not a real PE, and nothing here reads it")
        self.dir = self.exe.parent / "bp_ipc"
        self.dir.mkdir()
        self.cmd = self.dir / "cmd.txt"
        self.out = self.dir / "out.txt"
        self.enterContext(patch.object(launcher_bridge, "read_config",
                                       return_value={"game_exe": str(self.exe)}))
        self.enterContext(patch.object(ipc, "SETTLE_POLL_S", 0.01))
        self.enterContext(patch.object(ipc, "CONSUME_POLL_S", 0.01))

    def consumer(self, reply: bytes, *, delay: float = 0.0, consume: bool = True):
        """A thread that behaves like the plugin: delete `cmd.txt`, append.

        Returns the thread, already started, and registers a join so a failed
        assertion cannot leave it running into the next test.
        """
        seen: list[bytes] = []

        def run():
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if self.cmd.is_file():
                    time.sleep(delay)
                    try:
                        seen.append(self.cmd.read_bytes())
                        if consume:
                            os.remove(self.cmd)
                    except OSError:  # pragma: no cover - lost a race, retry
                        continue
                    with open(self.out, "ab") as handle:
                        handle.write(reply)
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=run, name="fake-bp-consumer", daemon=True)
        self.addCleanup(thread.join, 6.0)
        thread.start()
        return seen

    def send(self, lines, **kwargs):
        kwargs.setdefault("gate", running_gate)
        kwargs.setdefault("timeout_s", 3.0)
        return ipc.send(lines, **kwargs)


class ResolveTests(IpcFixture):
    """D6 -- the directory comes from ForgePact's own configuration."""

    def test_the_directory_is_bp_ipc_beside_the_configured_executable(self):
        self.assertEqual(ipc.resolve_dir(), self.dir)

    def test_a_missing_configuration_refuses_with_the_core_token(self):
        with patch.object(launcher_bridge, "read_config", return_value={}):
            refusal = ipc.resolve_dir()
        self.assertTrue(results.is_refusal(refusal))
        self.assertEqual(refusal["reason"], "forgepact_config_missing")

    def test_a_missing_bp_ipc_directory_names_the_one_fix(self):
        renamed = self.dir.with_name("bp_ipc_gone")
        os.rename(self.dir, renamed)
        refusal = ipc.resolve_dir()
        self.assertTrue(results.is_refusal(refusal))
        self.assertEqual(refusal["reason"], "bp_ipc_missing")
        self.assertIn("launch the modded game once", refusal["detail"])
        self.assertIn(str(self.dir), refusal["detail"])

    def test_both_tools_pass_that_refusal_straight_through(self):
        renamed = self.dir.with_name("bp_ipc_gone")
        os.rename(self.dir, renamed)
        sent, tailed = self.send(["ping"]), ipc.tail(10)
        self.assertEqual(sent["reason"], "bp_ipc_missing")
        self.assertEqual(sent["tool"], "hs_command")
        self.assertEqual(tailed["reason"], "bp_ipc_missing")
        self.assertEqual(tailed["tool"], "hs_ipc_tail")


class ValidationTests(IpcFixture):
    """D4 -- an unsendable command writes nothing at all."""

    def assert_invalid(self, lines):
        result = self.send(lines)
        self.assertEqual(result["reason"], "invalid_command", result)
        self.assertFalse(self.cmd.exists(),
                         "a rejected command still wrote cmd.txt")
        return result

    def assert_accepted(self, lines):
        """The boundary case, queued so nothing waits for a consumer.

        A validation test that could not tell "refused for length" from
        "refused for something else" would pass against an off-by-one, so the
        accepted side of every limit is asserted too.
        """
        result = self.send(lines, gate=not_running_gate, queue=True)
        self.assertTrue(result["ok"], result)
        os.remove(self.cmd)
        return result

    def test_non_ascii_is_refused_because_the_plugin_reads_raw_bytes(self):
        result = self.assert_invalid(["pïng"])
        self.assertIn("ASCII", result["detail"])

    def test_an_embedded_newline_is_refused_rather_than_split(self):
        # Splitting it would silently send two commands, one of which the
        # caller never wrote.
        self.assert_invalid(["ping\nstat"])
        self.assert_invalid(["ping\rstat"])

    def test_more_than_sixty_four_lines_is_refused(self):
        self.assertEqual(ipc.MAX_LINES, 64)
        self.assert_accepted(["ping"] * 64)
        result = self.assert_invalid(["ping"] * 65)
        self.assertIn("64", result["detail"])

    def test_more_than_four_kilobytes_is_refused(self):
        self.assertEqual(ipc.MAX_BYTES, 4096)
        self.assert_accepted(["a" * (4096 - 2)])
        result = self.assert_invalid(["a" * 5000])
        self.assertIn("4096", result["detail"])

    def test_nothing_to_send_is_refused(self):
        for lines in ([], [""], ["   "], "", None):
            self.assert_invalid(lines)


class GateTests(IpcFixture):
    """D4 -- the gate decides, and its own account of why is the detail."""

    def test_a_closed_game_refuses_unless_the_caller_asks_to_queue(self):
        result = self.send(["ping"], gate=not_running_gate)
        self.assertEqual(result["reason"], "game_not_running")
        self.assertIn("none of them is hero_siege.exe", result["detail"])
        self.assertFalse(self.cmd.exists())

    def test_queue_true_appends_for_the_next_start_without_waiting(self):
        started = time.monotonic()
        result = self.send(["density 2"], gate=not_running_gate, queue=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["queued"])
        self.assertFalse(result["consumed"])
        self.assertTrue(result["pending_left"])
        self.assertEqual(self.cmd.read_bytes(), b"density 2\r\n")
        self.assertLess(time.monotonic() - started, 2.0,
                        "a queued command waited for a consumer that cannot exist")

    def test_an_unknown_state_refuses_even_with_queue(self):
        for queue in (False, True):
            result = self.send(["ping"], gate=unknown_gate, queue=queue)
            self.assertEqual(result["reason"], "game_state_unknown", queue)
            self.assertFalse(self.cmd.exists())

    def test_an_engine_state_keeps_its_own_token(self):
        result = self.send(["ping"], gate=engine_missing_gate)
        self.assertEqual(result["reason"], "engine_source_missing")

    def test_the_gate_states_this_module_branches_on_are_the_documented_five(self):
        from tools.hs_drive_mcp import procs
        self.assertEqual(sorted(procs.GATE_STATES), sorted(ipc.HANDLED_GATE_STATES))


class SendTests(IpcFixture):
    """D2, D3, D4 -- the bytes on disk, and the reply that comes back."""

    def test_cmd_is_plain_ascii_crlf_terminated_and_carries_no_bom(self):
        # Queued, so the file is still on disk to be read back: this is the one
        # test that asserts the first bytes of cmd.txt itself.
        result = self.send(["ping", "density 2"], gate=not_running_gate, queue=True)
        self.assertEqual(result["sent"], ["ping", "density 2"])
        raw = self.cmd.read_bytes()
        self.assertEqual(raw[:4], b"ping")
        self.assertNotEqual(raw[:3], b"\xef\xbb\xbf", "cmd.txt carries a UTF-8 BOM")
        self.assertEqual(raw, b"ping\r\ndensity 2\r\n")
        self.assertTrue(raw.endswith(b"\r\n"))
        self.assertEqual(raw.decode("ascii").encode("ascii"), raw)
        self.assertEqual(result["wrote_bytes"], len(raw))

    def test_the_consumer_receives_exactly_ascii_crlf_bytes_with_no_bom(self):
        seen = self.consumer(b"pong\r\n")
        self.send(["ping", "stat"])
        self.assertEqual(len(seen), 1, "the fake consumer never saw cmd.txt")
        self.assertEqual(seen[0], b"ping\r\nstat\r\n")
        self.assertNotEqual(seen[0][:3], b"\xef\xbb\xbf")
        self.assertEqual(seen[0].decode("ascii"), "ping\r\nstat\r\n")

    def test_a_pending_command_is_appended_to_rather_than_overwritten(self):
        self.cmd.write_bytes(b"density 2\r\n")
        seen = self.consumer(b"ok\r\n")
        result = self.send(["ping"])
        self.assertTrue(result["pending_before"],
                        "a pending cmd.txt was not reported")
        self.assertEqual(seen[0], b"density 2\r\nping\r\n",
                         "the pending command was overwritten, not appended to")
        self.assertTrue(result["consumed"])

    def test_the_reply_is_the_byte_delta_and_excludes_everything_earlier(self):
        self.out.write_bytes(b"==== BloodPact plugin loaded ==== v1.3.21\r\n"
                             b"density applied\r\n")
        earlier = self.out.stat().st_size
        self.consumer(b"pong (YYTK 3.3.0)")
        result = self.send(["ping"])
        self.assertTrue(result["consumed"], result)
        self.assertEqual(result["reply"], "pong (YYTK 3.3.0)")
        self.assertNotIn("BloodPact plugin loaded", result["reply"])
        self.assertEqual(result["reply_lines"], ["pong (YYTK 3.3.0)"])
        self.assertEqual(result["out_bytes_before"], earlier)
        self.assertFalse(result["rotated"])

    def test_a_rotated_out_txt_is_reported_rather_than_read_from_a_stale_offset(self):
        self.out.write_bytes(b"x" * 400)

        def rotate():
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if self.cmd.is_file():
                    os.remove(self.cmd)
                    self.out.write_bytes(b"==== BloodPact plugin loaded ==== v1\r\n")
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=rotate, daemon=True)
        self.addCleanup(thread.join, 6.0)
        thread.start()
        result = self.send(["ping"])
        self.assertTrue(result["rotated"],
                        "out.txt shrank and the offset was used anyway")
        self.assertIn("BloodPact plugin loaded", result["reply"])

    def test_nothing_consuming_it_is_a_refusal_naming_the_timeout(self):
        result = self.send(["ping"], timeout_s=0.3)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_consumed")
        self.assertFalse(result["consumed"])
        self.assertTrue(result["pending_left"])
        self.assertIn("0.3", result["detail"])
        self.assertIn("BloodPactPlugin.dll", result["detail"])
        self.assertTrue(self.cmd.is_file(),
                        "the unconsumed command was removed; the plugin runs it at next start")

    def test_an_abort_stops_the_wait_early_and_says_what_stopped_it(self):
        # The readiness wait is the long one -- up to 90 s for a plugin that is
        # still loading -- so it hands in an abort that watches for the game
        # disappearing. A wait that cannot notice that runs its whole budget
        # after a startup crash, and then reports a timeout, which sends the
        # reader to the wrong subsystem.
        started = time.monotonic()
        result = self.send(["ping"], timeout_s=30.0,
                           abort=lambda: "the game process disappeared")
        self.assertEqual(result["reason"], "not_consumed")
        self.assertEqual(result["aborted"], "the game process disappeared")
        self.assertIn("the game process disappeared", result["detail"])
        self.assertLess(time.monotonic() - started, 5.0)

    def test_an_abort_that_stays_quiet_does_not_disturb_a_normal_send(self):
        self.consumer(b"pong\r\n")
        result = self.send(["ping"], abort=lambda: "")
        self.assertTrue(result["consumed"], result)
        self.assertEqual(result["aborted"], "")

    def test_a_command_consumed_with_no_reply_is_not_reported_as_a_reply(self):
        self.consumer(b"")
        result = self.send(["density 2"])
        self.assertTrue(result["consumed"])
        self.assertEqual(result["reply"], "")
        self.assertEqual(result["reply_lines"], [])


class TailTests(IpcFixture):
    """D5 -- an absent `out.txt` is `exists: false`, never an empty list."""

    def test_an_absent_out_txt_reports_absence_instead_of_no_lines(self):
        result = ipc.tail(20)
        self.assertTrue(result["ok"])
        self.assertFalse(result["exists"])
        self.assertNotIn("lines", result,
                         "an absent file returned a list of lines, which reads "
                         "as a plugin that answered nothing")
        self.assertEqual(result["bytes_total"], 0)

    def test_the_last_n_lines_come_back_with_the_total_size(self):
        self.out.write_bytes(b"".join(f"line {i}\r\n".encode() for i in range(50)))
        result = ipc.tail(3)
        self.assertTrue(result["exists"])
        self.assertEqual(result["lines"], ["line 47", "line 48", "line 49"])
        self.assertEqual(result["bytes_total"], self.out.stat().st_size)

    def test_a_partial_line_at_the_read_window_is_dropped_not_reported(self):
        self.out.write_bytes(b"".join(f"line {i}\r\n".encode() for i in range(400)))
        with patch.object(ipc, "TAIL_READ_BYTES", 40):
            result = ipc.tail(500)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["lines"][-1], "line 399")
        for line in result["lines"]:
            self.assertRegex(line, r"^line \d+$",
                             "a half line from the middle of the file was reported")

    def test_the_line_count_is_clamped_to_the_documented_range(self):
        self.out.write_bytes(b"one\r\ntwo\r\n")
        self.assertEqual(ipc.tail(0)["lines"], ["two"])
        self.assertEqual(ipc.tail(-5)["lines"], ["two"])
        self.assertEqual(ipc.tail(10_000)["requested"], ipc.TAIL_MAX_LINES)


if __name__ == "__main__":
    unittest.main()

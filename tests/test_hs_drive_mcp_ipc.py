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

    def consuming_loop(self, *replies: bytes, after: float = 0.0):
        """A consumer that keeps going until it has consumed one file per reply.

        `consumer` above is one-shot, which cannot answer "did anything get
        lost across two commands": the concatenation of everything *this* one
        read is every byte that actually reached the plugin.

        `after` delays the first look, so a test can be sure `send` has already
        taken its `pending_before` reading before the pending file disappears.
        Without it the consumer can win that race and the test asserts against
        a reading nobody made.
        """
        seen: list[bytes] = []

        def run():
            time.sleep(after)
            deadline = time.monotonic() + 5.0
            for reply in replies:
                while time.monotonic() < deadline:
                    if self.cmd.is_file():
                        try:
                            seen.append(self.cmd.read_bytes())
                            os.remove(self.cmd)
                        except OSError:  # pragma: no cover - lost a race, retry
                            continue
                        with open(self.out, "ab") as handle:
                            handle.write(reply)
                        break
                    time.sleep(0.01)

        thread = threading.Thread(target=run, name="fake-bp-consumer", daemon=True)
        self.addCleanup(thread.join, 6.0)
        thread.start()
        return seen

    def pending_wait_started(self) -> threading.Event:
        """An `Event` the send sets once it is waiting for `cmd.txt` to go.

        `pending_before` is read before that wait begins, so this is the point
        after which a fake plugin can take the pending file without changing
        which state the test is measuring. A `sleep` here would be a guess at how
        long `send`'s validation, gate reading and directory resolution take.
        """
        entered = threading.Event()
        real = ipc._await_consumption

        def spy(*args, **kwargs):
            entered.set()
            return real(*args, **kwargs)

        self.enterContext(patch.object(ipc, "_await_consumption", spy))
        return entered

    def clearing_consumer(self, *, stream_s: float, reply: bytes = b"pong\r\n",
                          answer_next: bool = True):
        """The plugin at load: clear the pending command, print for a while, then
        answer the next one.

        `answer_next=False` is the plugin that cleared the earlier command and
        then never came back for this one -- a channel this call has *watched*
        being read, which is a different state from one nothing reads.

        This is the shape `hs_wait_ready` after `hs_command(queue=true)` meets in
        a real session -- the queued command runs at plugin load and its output
        streams into `out.txt` for as long as it takes -- and it is the shape that
        catches a send which spends this command's own wait on the earlier one's
        settle: by the time `cmd.txt` is written the budget is gone, so the
        refusal reports a timeout that never happened.

        It waits for the send's *own* wait to start before taking the pending
        file, because a consumer that wins that race removes the file before
        `pending_before` is read -- and then the test measures a different shape
        (a plugin that was merely busy) while looking like this one.
        """
        seen: list[bytes] = []
        started = self.pending_wait_started()

        def run():
            deadline = time.monotonic() + 5.0
            started.wait(5.0)
            while time.monotonic() < deadline and not self.cmd.is_file():
                time.sleep(0.01)
            try:
                seen.append(self.cmd.read_bytes())
                os.remove(self.cmd)
            except OSError:  # pragma: no cover - it went before we read it
                return
            # Still running the earlier command: out.txt grows the whole time,
            # which is what the pre-write settle is waiting out.
            until = time.monotonic() + stream_s
            while time.monotonic() < until:
                with open(self.out, "ab") as handle:
                    handle.write(b"citrace: 1 instance\r\n")
                time.sleep(0.02)
            while answer_next and time.monotonic() < deadline:
                if self.cmd.is_file():
                    try:
                        seen.append(self.cmd.read_bytes())
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

    def interleaving_consumer(self):
        """The plugin's read-then-delete order, with the race window held open.

        The plugin reads the whole of `cmd.txt` and **then** deletes it, so
        anything appended between those two steps is deleted unread while the
        file still vanishes -- which a driver watching for the file to disappear
        reads as "consumed", and then attributes the *previous* command's output
        to this command.

        This consumer reads on first sight, signals that it has read, then holds
        the window open for up to a second waiting for the file to **grow**
        before deleting it regardless. The returned `Event` lets a test
        guarantee the read happens before `send` is called, so the race is
        reproduced on every run rather than on most of them; the growth wait
        stays well under the fixture's 3 s send timeout.
        """
        seen: list[bytes] = []
        first_read = threading.Event()

        def run():
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not self.cmd.is_file():
                time.sleep(0.01)
            try:
                seen.append(self.cmd.read_bytes())
            except OSError:  # pragma: no cover - it went before we read it
                return
            first_read.set()
            grew = len(seen[0])
            window = time.monotonic() + 1.0
            while time.monotonic() < window:
                if self.cmd.is_file() and self.cmd.stat().st_size > grew:
                    break
                time.sleep(0.01)
            try:
                os.remove(self.cmd)
            except OSError:  # pragma: no cover - already gone
                pass
            with open(self.out, "ab") as handle:
                handle.write(b"prev reply\r\n")
            while time.monotonic() < deadline:
                if self.cmd.is_file():
                    try:
                        seen.append(self.cmd.read_bytes())
                        os.remove(self.cmd)
                    except OSError:  # pragma: no cover - lost a race, retry
                        continue
                    with open(self.out, "ab") as handle:
                        handle.write(b"pong\r\n")
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=run, name="fake-bp-consumer", daemon=True)
        self.addCleanup(thread.join, 6.0)
        thread.start()
        return seen, first_read

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

    def test_a_queued_command_still_appends_to_a_pending_file(self):
        """Baseline: with the game closed nothing can be mid-read of `cmd.txt`,
        so the pending-file wait must not reach this path -- a caller who asked
        to queue must not be made to wait for a consumer that cannot exist, and
        the command already in the file must still be there afterwards."""
        self.cmd.write_bytes(b"density 2\r\n")
        started = time.monotonic()
        result = self.send(["ping"], gate=not_running_gate, queue=True)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["queued"])
        self.assertTrue(result["pending_before"])
        self.assertTrue(result["pending_left"])
        self.assertEqual(self.cmd.read_bytes(), b"density 2\r\nping\r\n")
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

    def test_a_pending_command_is_never_overwritten_or_lost(self):
        """Baseline: both commands reach the plugin, exactly once each.

        This is the invariant the old
        `test_a_pending_command_is_appended_to_rather_than_overwritten` was
        protecting, stated without encoding the append: what actually reached
        the plugin is the concatenation of everything it read, and that must
        start with the pending bytes and carry this send's bytes once. True
        whether the pending file is appended to or waited out and replaced.
        """
        self.cmd.write_bytes(b"density 2\r\n")
        seen = self.consuming_loop(b"ok\r\n", b"pong\r\n", after=0.2)
        result = self.send(["ping"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["pending_before"],
                        "a pending cmd.txt was not reported")
        self.assertTrue(result["consumed"])
        reached = b"".join(seen)
        self.assertTrue(reached.startswith(b"density 2\r\n"),
                        f"the pending command was lost: {reached!r}")
        self.assertEqual(reached.count(b"ping\r\n"), 1,
                         "this command reached the plugin the wrong number of "
                         f"times: {reached!r}")

    def test_a_pending_command_is_consumed_before_this_one_is_written(self):
        """The race in finding #6, reproduced, then closed.

        The plugin reads the whole file and *then* deletes it, so a line
        appended in between is deleted unread while the file still vanishes --
        `consumed: true`, and `out.txt`'s byte delta is the *earlier* command's
        output reported as this one's reply. Nothing downstream can tell that
        from a real answer, which is why a label on the success detail is not
        enough: the pending command is waited out, `out.txt` is allowed to
        settle, and this command is then written fresh into a file the plugin
        cannot already have opened.
        """
        self.cmd.write_bytes(b"density 2\r\n")
        seen, first_read = self.interleaving_consumer()
        self.assertTrue(first_read.wait(5.0), "the consumer never read cmd.txt")
        result = self.send(["ping"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["pending_before"])
        # The reply first: a wrong one here is the bug's whole payload, and
        # nothing downstream can tell it from a real answer.
        self.assertNotIn("prev reply", result["reply"],
                         "the earlier command's output was reported as this "
                         "command's reply")
        self.assertEqual(result["reply"], "pong\r\n")
        self.assertEqual(seen[0], b"density 2\r\n",
                         "this command was appended to a file the plugin had "
                         "already read, so it was deleted unread")
        self.assertEqual(seen[1:], [b"ping\r\n"])
        self.assertIn("earlier command", result["detail"])
        self.assertIn("consumed first", result["detail"])

    def test_clearing_a_pending_command_does_not_spend_this_command_s_own_wait(self):
        """The wait for someone else's command is not this command's budget.

        Waiting a pending command out and letting `out.txt` settle takes as long
        as the earlier command takes to print. When that time came out of the
        same `deadline` as the wait for *this* command, the send wrote `cmd.txt`
        with nothing left and refused `not_consumed` on its first poll -- a
        timeout of ~0 s reported as the caller's `timeout_s`, and the refusal
        then named two explanations ("never loaded", "a different copy") that
        the same call had just disproved by watching the plugin consume the
        earlier command on this very channel. `AGENTS.md` § "Prove the
        Instrument Before Trusting a Negative Result": a negative produced by
        this module's own budget accounting is not evidence about the game.
        """
        self.cmd.write_bytes(b"citrace collect\r\n")
        seen = self.clearing_consumer(stream_s=0.6)
        result = self.send(["ping"], timeout_s=0.3)
        self.assertTrue(result["ok"],
                        "clearing the earlier command spent this command's own "
                        f"wait, so it was never really waited for: {result}")
        self.assertEqual(result["reply"], "pong\r\n")
        self.assertNotIn("citrace:", result["reply"],
                         "the earlier command's output was counted into this "
                         "command's reply, so out.txt was not settled first")
        self.assertTrue(result["pending_before"])
        self.assertEqual(seen, [b"citrace collect\r\n", b"ping\r\n"])

    def test_a_channel_seen_consuming_an_earlier_command_is_not_reported_unobserved(self):
        """A live channel that ignored *this* command is a different diagnosis.

        The plugin consumed the pending command here, so "nothing is reading
        this channel" is measurably false: the fix is not to go and compare
        install paths, it is that this command's own wait expired while the
        plugin was busy. Reporting the second-copy paragraph for this state is
        the mislabelled negative `AGENTS.md` § "Check a Permission Where It Is
        Used" (last bullet) warns about, with the control already fired.
        """
        self.cmd.write_bytes(b"citrace collect\r\n")
        seen = self.clearing_consumer(stream_s=0.05, answer_next=False)
        result = self.send(["ping"], timeout_s=0.3)
        self.assertEqual(seen, [b"citrace collect\r\n"],
                         "the fake plugin did not clear the earlier command, so "
                         "this is not the state under test")
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "not_consumed")
        detail = result["detail"]
        self.assertIn("observed consuming an earlier command", detail)
        self.assertNotIn("not observed", detail,
                         "the plugin was watched consuming a command on this "
                         "channel and the refusal still called it unobserved")
        self.assertNotIn("different copy", detail,
                         "a channel this call proved is being read was reported "
                         "as possibly belonging to another copy of the game")
        self.assertTrue(result["observed_consumption"])
        self.assertTrue(result["pending_before"])
        self.assertTrue(result["pending_left"])
        self.assertEqual(result["wrote_bytes"], len(b"ping\r\n"))
        self.assertEqual(self.cmd.read_bytes(), b"ping\r\n",
                         "this command was not written fresh after the earlier "
                         "one was consumed")

    def test_a_pending_command_nobody_consumes_means_this_one_is_not_written(self):
        """A pending file that never goes is the same "nothing is reading this
        channel" state as an unconsumed send -- same token, and `wrote_bytes: 0`,
        because writing after a timed-out wait is the `queue=true` behaviour the
        caller did not ask for."""
        self.cmd.write_bytes(b"density 2\r\n")
        result = self.send(["ping"], timeout_s=0.3)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "not_consumed")
        self.assertEqual(result["wrote_bytes"], 0)
        self.assertEqual(self.cmd.read_bytes(), b"density 2\r\n",
                         "this command was written into a file the plugin may "
                         "already have read")
        self.assertTrue(result["pending_before"])
        self.assertTrue(result["pending_left"])
        self.assertFalse(result["consumed"])
        self.assertIn("not written", result["detail"])

        # The same refusal when the wait is cut short instead of timing out --
        # the shape `hs_wait_ready` hands in, which watches for the game going
        # away. Still nothing written.
        started = time.monotonic()
        aborted = self.send(["ping"], timeout_s=30.0,
                            abort=lambda: "the game process disappeared")
        self.assertEqual(aborted["reason"], "not_consumed")
        self.assertEqual(aborted["aborted"], "the game process disappeared")
        self.assertEqual(aborted["wrote_bytes"], 0)
        self.assertIn("not written", aborted["detail"])
        self.assertEqual(self.cmd.read_bytes(), b"density 2\r\n")
        self.assertLess(time.monotonic() - started, 5.0)

    def test_an_unconsumed_command_names_the_second_copy_possibility(self):
        """Nothing consuming `cmd.txt` is "not observed on this channel", not
        "the plugin never read it".

        The gate says `running` by image name; `bp_ipc\\` comes from the
        configured executable. The plugin derives its own channel from its own
        module path, so a second copy of the game running produces this exact
        reading with the plugin fully loaded -- and the reader needs the
        configured path to compare against `pids`.
        """
        result = self.send(["ping"], timeout_s=0.3)
        self.assertEqual(result["reason"], "not_consumed")
        detail = result["detail"]
        self.assertIn("not observed", detail)
        self.assertIn("different copy", detail)
        self.assertIn(str(self.exe), detail,
                      "the detail does not name the configured executable, so "
                      "nothing can be compared with the running processes")
        self.assertNotIn("plugin never read", detail,
                         "a negative measured on one channel was reported as a "
                         "conclusion about the plugin")
        # The negative control for the test above: nothing was consumed here, so
        # this is the one refusal where the second-copy paragraph belongs.
        self.assertFalse(result["observed_consumption"])

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

"""Launch, readiness and stop -- with ForgePact's engine under the test's control.

Three things are asserted here that no amount of reading the code proves:

1. **The launch goes through ForgePact's own engine.** `launch_game` is called
   with the path the panel's configuration names and a `validate_extra`
   callable, and the tool persists nothing: the fixture `%LOCALAPPDATA%` tree is
   compared byte for byte afterwards. Owner decision D3 chose this engine over
   HS-Offline-Launcher's module precisely because that module writes the user's
   launcher configuration.
2. **The four readiness outcomes are never conflated.** "the process is up",
   "the plugin answered", "the plugin consumed the ping and said nothing" and
   "nothing consumed it at all" are separate phases with separate fields,
   because a tool that reports itself ready while its own positive control has
   not fired is the shape `AGENTS.md` § "Prove the Instrument" exists to catch
   -- and here the instrument is the readiness check itself. `ready` is
   therefore true for `plugin_ready` alone.
3. **`TerminateProcess` is unreachable for a process this server did not
   start.** `AGENTS.md` § "Drive a Tauri App Yourself" -- never kill a process
   you did not start. The graceful `WM_CLOSE` path is always allowed; the forced
   one needs `force=true`, a PID in this process's launched set, *and* a
   graceful wait that already timed out. The negative control (a PID that is not
   in the set) asserts the call was not made at all.

The baseline/target pair `AGENTS.md` § "Mod Development Workflow" asks for:
`EngineRefusalTests` is the baseline -- a refused launch must leave the machine
exactly as it was, with the engine's own `Popen` never reached -- and
`ReadinessTests.test_a_consumed_ping_is_the_plugin_ready_phase` is the target.
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENGINE_SOURCE = ROOT / "ForgePact" / "src" / "offline_launcher.py"

SKIP_REASON = None
if os.name != "nt":
    SKIP_REASON = (f"launching, window enumeration and TerminateProcess are "
                   f"Windows-only; os.name is {os.name!r}")
elif not ENGINE_SOURCE.is_file():
    SKIP_REASON = (f"{ENGINE_SOURCE} is absent; run "
                   "`git submodule update --init ForgePact`")

if SKIP_REASON is None:
    from tools.hs_drive_mcp import capture, ipc, launch, launcher_bridge, procs, results


def gate_running():
    return "running", "1 hero_siege.exe process(es) are live: [4242]."


def gate_not_running():
    return "not_running", "the process snapshot returned 84 rows and none of them is hero_siege.exe."


def gate_sequence(*states):
    """A gate that walks a script and then holds on its last answer."""
    remaining = list(states)

    def gate():
        state = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return state, f"the scripted gate reported {state!r}."

    return gate


def hwnd_of(handle):
    """A window handle as the integer the real Win32 call receives.

    The wrappers pass `ctypes.c_void_p` rather than a bare int, because an
    unprototyped ctypes call narrows a Python int to 32 bits and would truncate
    a 64-bit HWND. A fake therefore has to unwrap it the way the API does --
    and getting this wrong is how a stub ends up unable to represent the call it
    stands in for.
    """
    return int(getattr(handle, "value", handle) or 0)


class FakeUser32:
    """Enough of user32 for enumeration and `WM_CLOSE`, and nothing more.

    The wrappers under test pass real `ctypes` pointers, so this fills them the
    way the real API does rather than being handed pre-digested window
    dictionaries -- a stub that cannot represent the call's actual shape cannot
    catch a mistake in making it.
    """

    def __init__(self, windows):
        self.windows = list(windows)
        self.posted: list[tuple[int, int]] = []

    def _window(self, hwnd):
        for window in self.windows:
            if window["hwnd"] == hwnd_of(hwnd):
                return window
        raise AssertionError(f"the code under test invented hwnd {hwnd}")

    def EnumWindows(self, callback, extra):  # noqa: N802 - the Win32 name
        for window in self.windows:
            callback(window["hwnd"], extra)
        return 1

    def GetWindowThreadProcessId(self, hwnd, pointer):  # noqa: N802
        pointer.contents.value = self._window(hwnd)["pid"]
        return 4711

    def IsWindowVisible(self, hwnd):  # noqa: N802
        return 1 if self._window(hwnd)["visible"] else 0

    def IsIconic(self, hwnd):  # noqa: N802
        return 1 if self._window(hwnd)["minimized"] else 0

    def GetWindowRect(self, hwnd, pointer):  # noqa: N802
        left, top, right, bottom = self._window(hwnd)["rect"]
        rect = pointer.contents
        rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom
        return 1

    def PostMessageW(self, hwnd, message, wparam, lparam):  # noqa: N802
        self.posted.append((hwnd_of(hwnd), int(message)))
        return 1


class FakeKernel32:
    """`OpenProcess` / `TerminateProcess` / `CloseHandle`, and a call log.

    The log is the point: several assertions here are that
    `TerminateProcess` was **not** called.
    """

    def __init__(self, open_fails: bool = False):
        self.open_fails = open_fails
        self.terminated: list[int] = []
        self.opened: list[int] = []
        self.closed: list[int] = []

    def OpenProcess(self, access, inherit, pid):  # noqa: N802
        self.opened.append(int(pid))
        return 0 if self.open_fails else 0x1000 + int(pid)

    def TerminateProcess(self, handle, code):  # noqa: N802
        self.terminated.append(int(handle) - 0x1000)
        return 1

    def CloseHandle(self, handle):  # noqa: N802
        self.closed.append(int(handle))
        return 1


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class LaunchFixture(unittest.TestCase):
    """A modded install fixture, and every poll shortened."""

    def setUp(self):
        engine = launcher_bridge.load()
        self.assertFalse(results.is_refusal(engine), engine)
        self.engine = engine

        temp = tempfile.TemporaryDirectory(prefix="hs-drive-launch-")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

        self.exe = self.base / "game" / "bin" / "Hero_Siege.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"not a real PE; every reader of it is mocked")
        aurie = self.exe.parent / "mods" / "aurie"
        aurie.mkdir(parents=True)
        self.chain_files = {
            "aurieCore": self.exe.parent / "AurieCore.dll",
            "yytk": aurie / "YYToolkit.dll",
            "plugin": aurie / "BloodPactPlugin.dll",
        }
        for path in self.chain_files.values():
            path.write_bytes(b"mod fixture")
        self.ipc_dir = self.exe.parent / "bp_ipc"
        self.ipc_dir.mkdir()
        self.cmd = self.ipc_dir / "cmd.txt"
        self.out = self.ipc_dir / "out.txt"

        # `patched` reads the PE section table through the engine; the fixture is
        # not a PE, so that one fact is supplied instead of faked on disk.
        self.enterContext(patch.object(launcher_bridge, "mod_chain",
                                       side_effect=self.mod_chain))
        self.enterContext(patch.object(launcher_bridge, "read_config",
                                       return_value={"game_exe": str(self.exe)}))
        self.enterContext(patch.object(launch, "_LAUNCHED", set()))
        self.enterContext(patch.object(launch, "PROCESS_POLL_S", 0.01))
        self.enterContext(patch.object(ipc, "CONSUME_POLL_S", 0.01))
        self.enterContext(patch.object(ipc, "SETTLE_POLL_S", 0.01))

    def mod_chain(self, exe):
        """The real four facts, with `patched` read off the fixture's name."""
        if exe is None:
            return dict.fromkeys(launcher_bridge.MOD_CHAIN_KEYS, False)
        exe = Path(exe)
        aurie = exe.parent / "mods" / "aurie"
        return {
            "patched": exe.is_file(),
            "aurieCore": (exe.parent / "AurieCore.dll").is_file(),
            "yytk": (aurie / "YYToolkit.dll").is_file(),
            "plugin": (aurie / "BloodPactPlugin.dll").is_file(),
        }

    def launch_ok(self, pid=4242):
        """A stand-in for a successful `launch_game`, recording its arguments."""
        return MagicMock(return_value={
            "ok": "Modded Hero Siege launch requested through the built-in "
                  "HS Offline Launcher.",
            "pid": pid,
            "launch": {"phase": "started", "message": "started", "pid": pid,
                       "attempt": 1},
        })

    def consumer(self, reply: bytes, *, delay: float = 0.0):
        """The plugin's half of the channel: delete `cmd.txt`, append a reply.

        `reply=b""` is the consumer that consumes and answers nothing, which is
        the input the readiness report used to call `plugin_ready`.
        """
        def run():
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if self.cmd.is_file():
                    time.sleep(delay)
                    try:
                        os.remove(self.cmd)
                    except OSError:  # pragma: no cover - lost a race
                        continue
                    with open(self.out, "ab") as handle:
                        handle.write(reply)
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=run, name="fake-bp-consumer", daemon=True)
        self.addCleanup(thread.join, 9.0)
        thread.start()

    def pending_wait_started(self) -> threading.Event:
        """An `Event` `ipc.send` sets once it is waiting for `cmd.txt` to go.

        `pending_before` is read just before that wait starts, so this is the
        point after which a fake plugin may take the pending file without
        changing which state the test is measuring.
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
        """The plugin at load: run the queued command, print, then answer the ping.

        This is what `hs_wait_ready` after `hs_command(queue=true)` actually
        meets: the queued command is consumed when the plugin loads and its
        output streams into `out.txt` for as long as it runs. `reply=b""` is not
        offered -- the point of this consumer is that the ping *is* answered, so
        anything but `plugin_ready` at the end is this server's own accounting.
        `answer_next=False` stops after the queued command, which is the channel
        that has been watched being read and still did not take the ping.

        It waits for the send's own pending wait to start before taking the
        queued file: a consumer that wins that race removes it before
        `pending_before` is read, and the test then measures a plugin that was
        merely busy while looking like this one. A `sleep` in its place would be
        a guess at how long a real `procs.game_pids()` snapshot takes.
        """
        started = self.pending_wait_started()

        def run():
            deadline = time.monotonic() + 8.0
            started.wait(8.0)
            while time.monotonic() < deadline and not self.cmd.is_file():
                time.sleep(0.01)
            try:
                os.remove(self.cmd)
            except OSError:  # pragma: no cover - lost a race
                return
            until = time.monotonic() + stream_s
            while time.monotonic() < until:
                with open(self.out, "ab") as handle:
                    handle.write(b"citrace: 1 instance\r\n")
                time.sleep(0.02)
            while answer_next and time.monotonic() < deadline:
                if self.cmd.is_file():
                    try:
                        os.remove(self.cmd)
                    except OSError:  # pragma: no cover - lost a race
                        continue
                    with open(self.out, "ab") as handle:
                        handle.write(reply)
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=run, name="fake-bp-consumer", daemon=True)
        self.addCleanup(thread.join, 9.0)
        thread.start()


class EngineCallTests(LaunchFixture):
    """C2 -- the engine is called with the panel's path, and nothing persists."""

    def test_the_configured_path_and_a_validate_extra_callable_are_passed(self):
        launch_game = self.launch_ok()
        with patch.object(self.engine, "launch_game", launch_game):
            result = launch.hs_launch(wait_for_plugin=False, gate=gate_running)
        self.assertTrue(result["ok"], result)
        launch_game.assert_called_once()
        args, kwargs = launch_game.call_args
        self.assertEqual(Path(args[0]), self.exe)
        self.assertTrue(callable(kwargs["validate_extra"]),
                        "the plugin preflight was not handed to the engine")
        self.assertEqual(result["pid"], 4242)
        self.assertEqual(result["exe_path"], str(self.exe))
        self.assertFalse(result["exe_path_override"])

    def test_an_explicit_exe_path_overrides_for_one_call_and_persists_nothing(self):
        other = self.base / "second copy" / "bin" / "Hero_Siege.exe"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"a second install")
        aurie = other.parent / "mods" / "aurie"
        aurie.mkdir(parents=True)
        for name in ("AurieCore.dll",):
            (other.parent / name).write_bytes(b"mod fixture")
        for name in ("YYToolkit.dll", "BloodPactPlugin.dll"):
            (aurie / name).write_bytes(b"mod fixture")

        local = self.base / "LocalAppData"
        (local / "Hero_Siege").mkdir(parents=True)
        (local / "Hero_Siege" / "forgepact.json").write_text(
            '{"game_exe": "' + str(self.exe).replace("\\", "\\\\") + '"}',
            encoding="utf-8")
        before = self.snapshot(local)

        launch_game = self.launch_ok(pid=77)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            with patch.object(self.engine, "launch_game", launch_game):
                result = launch.hs_launch(exe_path=str(other), wait_for_plugin=False,
                                          gate=gate_running)

        self.assertEqual(Path(launch_game.call_args[0][0]), other)
        self.assertTrue(result["exe_path_override"])
        self.assertEqual(self.snapshot(local), before,
                         "hs_launch wrote to %LOCALAPPDATA%; an explicit "
                         "exe_path must persist nothing")

    def test_the_default_path_reads_the_panel_configuration_and_writes_nothing(self):
        local = self.base / "LocalAppData2"
        (local / "Hero_Siege").mkdir(parents=True)
        config = local / "Hero_Siege" / "forgepact.json"
        config.write_text('{"game_exe": ' + repr(str(self.exe)).replace("'", '"')
                          + "}", encoding="utf-8")
        before = self.snapshot(local)
        launch_game = self.launch_ok()
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
            with patch.object(launcher_bridge, "read_config",
                              wraps=launcher_bridge.read_config):
                with patch.object(self.engine, "launch_game", launch_game):
                    result = launch.hs_launch(wait_for_plugin=False, gate=gate_running)
        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(launch_game.call_args[0][0]), self.exe)
        self.assertEqual(self.snapshot(local), before)

    def test_a_missing_panel_configuration_refuses_before_any_launch(self):
        launch_game = self.launch_ok()
        with patch.object(launcher_bridge, "read_config", return_value={}):
            with patch.object(self.engine, "launch_game", launch_game):
                result = launch.hs_launch(gate=gate_running)
        self.assertEqual(result["reason"], "forgepact_config_missing")
        self.assertEqual(result["phase"], "preflight")
        launch_game.assert_not_called()

    @staticmethod
    def snapshot(root: Path) -> dict[str, bytes]:
        return {str(path.relative_to(root)): path.read_bytes()
                for path in sorted(root.rglob("*")) if path.is_file()}


class PreflightTests(LaunchFixture):
    """C3 -- the mod chain is checked by the engine, through `validate_extra`."""

    def test_an_incomplete_mod_chain_refuses_and_never_reaches_popen(self):
        os.remove(self.chain_files["plugin"])
        os.remove(self.chain_files["yytk"])
        popen = MagicMock()
        with patch.object(self.engine, "validate_game", return_value=(True, "ok")):
            with patch.object(self.engine, "launch_safety_blocker", return_value=""):
                with patch.object(self.engine.subprocess, "Popen", popen):
                    result = launch.hs_launch(gate=gate_running)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["reason"], "mod_chain_incomplete")
        self.assertEqual(result["phase"], "preflight")
        self.assertIn("yytk", result["detail"])
        self.assertIn("plugin", result["detail"])
        self.assertNotIn("aurieCore", result["detail"])
        self.assertEqual(sorted(result["missing"]), ["plugin", "yytk"])
        popen.assert_not_called()

    def test_the_preflight_callable_alone_reports_the_same_four_facts(self):
        preflight = launch.ModChainPreflight(self.exe)
        self.assertEqual(preflight(), "")
        self.assertEqual(preflight.missing, [])
        os.remove(self.chain_files["aurieCore"])
        self.assertIn("aurieCore", launch.ModChainPreflight(self.exe)())

    def test_a_complete_chain_lets_the_engine_through_to_popen(self):
        # The control for the test above: the same wiring with nothing missing
        # must reach the engine's Popen, or the assertion above measures nothing.
        popen = MagicMock()
        popen.return_value.pid = 909
        with patch.object(self.engine, "validate_game", return_value=(True, "ok")):
            with patch.object(self.engine, "launch_safety_blocker", return_value=""):
                with patch.object(self.engine, "start_steam_if_needed",
                                  return_value=(True, "steam ready")):
                    with patch.object(self.engine, "find_steam_runtime",
                                      return_value=self.exe.parent / "steam_api64.dll"):
                        with patch.object(self.engine.subprocess, "Popen", popen):
                            result = launch.hs_launch(wait_for_plugin=False,
                                                      gate=gate_running)
        popen.assert_called_once()
        self.assertEqual(result["pid"], 909)
        self.assertIn(909, launch.launched_pids())


class EngineRefusalTests(LaunchFixture):
    """C4 -- the baseline: a refused launch reports the engine's own words."""

    def test_an_engine_refusal_is_launcher_refused_with_the_message_verbatim(self):
        message = "EAC is currently active. Close the protected game/session first"
        launch_game = MagicMock(return_value={
            "err": message,
            "launch": {"phase": "error", "message": message, "pid": 0, "attempt": 3},
        })
        gate = MagicMock(side_effect=gate_running)
        with patch.object(self.engine, "launch_game", launch_game):
            result = launch.hs_launch(gate=gate)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "launcher_refused")
        self.assertEqual(result["phase"], "launch")
        self.assertEqual(result["error"], message)
        self.assertEqual(result["launch"]["phase"], "error")
        self.assertEqual(gate.call_count, 0,
                         "readiness polling ran after a refused launch")

    def test_a_launch_lock_refusal_is_reported_the_same_way(self):
        launch_game = MagicMock(return_value={
            "err": "A launch request is already in progress",
            "launch": {"phase": "starting", "message": "", "pid": 0, "attempt": 1},
        })
        with patch.object(self.engine, "launch_game", launch_game):
            result = launch.hs_launch(gate=gate_running)
        self.assertEqual(result["reason"], "launcher_refused")
        self.assertIn("already in progress", result["error"])


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class ReadinessTests(LaunchFixture):
    """C5 -- process, plugin and timeout, as three separate answers."""

    def do_launch(self, *, states=("not_running", "running"), timeout_s=0.5, **kwargs):
        launch_game = self.launch_ok()
        with patch.object(self.engine, "launch_game", launch_game):
            return launch.hs_launch(gate=gate_sequence(*states),
                                    timeout_s=timeout_s, **kwargs)

    def launch_and_wait(self, *, timeout_s=0.5, **kwargs):
        """Both entry points, asserted to agree: `hs_wait_ready` is the same
        poll without the launch, so a difference between them is a bug."""
        launched = self.do_launch(timeout_s=timeout_s, **kwargs)
        waited = launch.hs_wait_ready(gate=gate_sequence("running"),
                                      timeout_s=timeout_s, **kwargs)
        return launched, waited

    def assert_common_fields(self, result):
        for key in ("pid", "elapsed_s", "launch", "phase", "ready", "plugin"):
            self.assertIn(key, result, result)
        self.assertIn("phase", result["launch"])

    def test_a_consumed_ping_is_the_plugin_ready_phase(self):
        self.consumer(b"pong (YYTK 3.3.0)\r\n")
        launched = self.do_launch(timeout_s=2.0)
        self.assert_common_fields(launched)
        self.assertEqual(launched["phase"], "plugin_ready", launched)
        self.assertTrue(launched["ready"])
        self.assertIn("pong", launched["plugin_reply"])
        self.assertEqual(launched["pid"], 4242)

        self.consumer(b"pong (YYTK 3.3.0)\r\n")
        waited = launch.hs_wait_ready(gate=gate_running, timeout_s=2.0)
        self.assert_common_fields(waited)
        self.assertEqual(waited["phase"], "plugin_ready", waited)
        self.assertIn("pong", waited["plugin_reply"])

    def test_a_consumed_ping_without_pong_is_not_ready(self):
        """The positive control not firing is not readiness.

        This state used to report `plugin_ready, ready: true` -- for a ping the
        plugin consumed and never answered, which the self-check's own plugin
        probe called a `fail` on the identical condition. `ready` is documented as
        "whether a command would be answered", and if the plugin's `Out()`
        writes are failing then every later `hs_command` returns an empty
        reply, which an agent that branched on `ready: true` cannot tell from
        "the command did nothing". `AGENTS.md` § "Prove the Instrument Before
        Trusting a Negative Result".

        Two consumers, because the failure has two shapes: one that appends
        nothing at all, and one that appends a line which is not a `pong` --
        the player build's own answer to a command it does not accept.
        """
        for appended in (b"", b"command unavailable in player build: ping\r\n"):
            with self.subTest(appended=appended):
                self.consumer(appended)
                launched = self.do_launch(timeout_s=2.0)
                self.consumer(appended)
                waited = launch.hs_wait_ready(gate=gate_running, timeout_s=2.0)
                for result in (launched, waited):
                    self.assert_common_fields(result)
                    self.assertEqual(result["phase"],
                                     "plugin_consumed_without_pong", result)
                    self.assertIs(result["ready"], False, result)
                    self.assertEqual(result["plugin"], "consumed_without_pong")
                    self.assertEqual(result["plugin_reply"], appended.decode())
                    detail = result["detail"]
                    self.assertIn("control did not fire", detail)
                    self.assertIn(f"{len(appended)} byte", detail)
                    self.assertIn("cannot be trusted", detail)

    def test_an_unconsumed_ping_is_not_observed_not_plugin_absent(self):
        """Nothing consuming `cmd.txt` is an observation, not a conclusion.

        The report used to say "so the BloodPact plugin is not loaded", and the
        two halves of that inference come from different installs: the gate
        says `running` by image name, while `bp_ipc\\` is resolved from the
        configured executable. The plugin derives its own channel from its own
        module path, so the owner's documented two-copy setup produces this
        exact reading with the plugin fully loaded. `AGENTS.md` § "Check a
        Permission Where It Is Used" -- write a negative down as "not
        observed", not "does not happen".
        """
        launched, waited = self.launch_and_wait()
        for result in (launched, waited):
            self.assert_common_fields(result)
            self.assertEqual(result["phase"], "timeout_waiting_for_plugin", result)
            self.assertEqual(result["plugin"], "not_consumed")
            detail = result["detail"]
            self.assertIn("not observed", detail)
            self.assertTrue(str(self.cmd) in detail or str(self.ipc_dir) in detail,
                            f"the detail names no channel path: {detail}")
            self.assertIn("different copy", detail)
            self.assertNotIn("is not loaded", detail,
                             "a negative measured on one channel was reported "
                             "as a conclusion about the plugin")

    def test_a_queued_command_cleared_first_does_not_starve_the_ping(self):
        """The session this exists to prevent, end to end.

        `hs_command(queue=true)` leaves a command in `cmd.txt`; the plugin runs
        it at load, printing for as long as it takes, and only then polls again.
        When the wait for that command and the wait for the ping shared one
        budget, the ping was written with the budget already gone and
        `hs_wait_ready` reported `timeout_waiting_for_plugin, ready: false` --
        sending the driver off to compare install paths for a plugin that had
        just consumed a command on that exact channel, in this call. The ping
        here *is* answered, so anything but `plugin_ready` is this server's own
        accounting rather than the game.
        """
        # The queued command prints for longer than the whole budget, which is
        # what a `citrace collect` at load does; nothing is left for the ping if
        # the two waits come out of one deadline.
        self.cmd.write_bytes(b"citrace collect\r\n")
        self.clearing_consumer(stream_s=1.2)
        result = launch.hs_wait_ready(gate=gate_running, timeout_s=1.0)
        self.assert_common_fields(result)
        self.assertEqual(result["phase"], "plugin_ready", result)
        self.assertTrue(result["ready"])
        self.assertIn("pong", result["plugin_reply"])

    def test_a_ping_the_live_channel_ignored_is_not_a_missing_plugin(self):
        """A channel seen consuming a command is not an unobserved channel.

        Same wait, same phase, different diagnosis: the plugin cleared the queued
        command and then did not take the ping in time, so the detail must not
        hand back the "never loaded, or a different copy" pair -- both were
        disproved inside this call. `AGENTS.md` § "Check a Permission Where It Is
        Used", last bullet.
        """
        self.cmd.write_bytes(b"citrace collect\r\n")
        self.clearing_consumer(stream_s=0.05, answer_next=False)
        result = launch.hs_wait_ready(gate=gate_running, timeout_s=1.0)
        self.assertEqual(result["phase"], "timeout_waiting_for_plugin", result)
        self.assertFalse(result["ready"])
        detail = result["detail"]
        self.assertIn("observed consuming an earlier command", detail)
        self.assertNotIn("different copy", detail,
                         "a channel this wait proved is being read was reported "
                         "as possibly belonging to another copy of the game")
        self.assertNotIn("not observed", detail)

    def test_no_bp_ipc_directory_stops_at_process_running(self):
        os.rename(self.ipc_dir, self.ipc_dir.with_name("bp_ipc_gone"))
        launched, waited = self.launch_and_wait()
        for result in (launched, waited):
            self.assert_common_fields(result)
            self.assertEqual(result["phase"], "process_running", result)
            self.assertEqual(result["plugin"], "no_bp_ipc")
            self.assertFalse(result["ready"])
            self.assertIn("bp_ipc", result["detail"])

    def test_a_plugin_that_never_consumes_is_its_own_phase(self):
        launched, waited = self.launch_and_wait()
        for result in (launched, waited):
            self.assert_common_fields(result)
            self.assertEqual(result["phase"], "timeout_waiting_for_plugin", result)
            self.assertFalse(result["ready"])
            self.assertEqual(result["plugin"], "not_consumed")

    def test_a_process_that_never_appears_is_not_a_plugin_timeout(self):
        result = launch.hs_wait_ready(gate=gate_sequence("not_running"), timeout_s=0.2)
        self.assertEqual(result["phase"], "timeout_waiting_for_process")
        self.assertFalse(result["ready"])
        self.assertFalse(self.cmd.exists(),
                         "a ping was written for a game that is not running")

    def test_a_process_that_disappears_during_the_wait_says_so(self):
        gate = gate_sequence("running", "running", "not_running")
        with patch.object(self.engine, "launch_status",
                          return_value={"phase": "error", "pid": 0, "attempt": 1,
                                        "message": "The game exited during startup."}):
            result = launch.hs_wait_ready(gate=gate, timeout_s=3.0)
        self.assertEqual(result["phase"], "process_exited", result)
        self.assertFalse(result["ready"])
        self.assertIn("exited during startup", result["detail"])

    def test_require_plugin_false_reports_the_process_without_probing(self):
        result = launch.hs_wait_ready(gate=gate_running, require_plugin=False,
                                      timeout_s=2.0)
        self.assertEqual(result["phase"], "process_running")
        self.assertEqual(result["plugin"], "not_checked")
        self.assertTrue(result["ready"])
        self.assertFalse(self.cmd.exists())

    def test_the_default_gate_is_the_shared_process_gate(self):
        # The injected gate above is a test seam; this proves the tool reaches
        # `procs.gate` when nothing is injected, so the seam cannot hide a
        # tool wired to nothing.
        with patch.object(procs, "game_state_detail",
                          return_value=("not_running", "no game row")):
            result = launch.hs_wait_ready(timeout_s=0.2)
        self.assertEqual(result["phase"], "timeout_waiting_for_process")


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class StopTests(LaunchFixture):
    """C6 -- `WM_CLOSE` always, `TerminateProcess` almost never."""

    def windows(self):
        return [
            {"hwnd": 11, "pid": 4242, "visible": True, "minimized": False,
             "rect": (0, 0, 1920, 1080)},
            {"hwnd": 12, "pid": 4242, "visible": False, "minimized": False,
             "rect": (0, 0, 10, 10)},
            {"hwnd": 13, "pid": 77, "visible": True, "minimized": True,
             "rect": (0, 0, 800, 600)},
            {"hwnd": 14, "pid": 999, "visible": True, "minimized": False,
             "rect": (0, 0, 640, 480)},
        ]

    def stop(self, *, states, pids, force=False, launched=(), kernel=None):
        user = FakeUser32(self.windows())
        kernel = kernel if kernel is not None else FakeKernel32()
        with patch.object(capture, "user32", return_value=user):
            with patch.object(launch, "kernel32", return_value=kernel):
                with patch.object(procs, "game_pids", side_effect=lambda *a, **k: list(pids)):
                    with patch.object(launch, "_LAUNCHED", set(launched)):
                        result = launch.hs_stop_game(force=force, timeout_s=0.3,
                                                     gate=gate_sequence(*states))
        return result, user, kernel

    def test_wm_close_goes_to_every_visible_window_of_every_game_pid(self):
        result, user, kernel = self.stop(states=("running", "not_running"),
                                         pids=[4242, 77])
        self.assertEqual(sorted(hwnd for hwnd, _ in user.posted), [11, 13],
                         "the invisible window or another process's window was posted to")
        self.assertEqual({message for _, message in user.posted}, {launch.WM_CLOSE})
        self.assertTrue(result["exited"])
        self.assertFalse(result["forced"])
        self.assertEqual(sorted(result["pids_closed"]), [77, 4242])
        self.assertEqual(kernel.terminated, [])

    def test_a_game_that_is_not_running_is_already_stopped(self):
        result, user, kernel = self.stop(states=("not_running",), pids=[])
        self.assertTrue(result["ok"])
        self.assertTrue(result["exited"])
        self.assertEqual(result["pids_closed"], [])
        self.assertEqual(user.posted, [])
        self.assertEqual(kernel.terminated, [])

    def test_an_unknown_state_is_reported_rather_than_acted_on(self):
        result, user, kernel = self.stop(states=("unknown",), pids=[])
        self.assertFalse(result["exited"])
        self.assertEqual(result["game_state"], "unknown")
        self.assertEqual(user.posted, [])
        self.assertEqual(kernel.terminated, [])
        self.assertIn("scripted gate", result["detail"])

    def test_force_is_refused_for_a_process_this_server_did_not_start(self):
        result, user, kernel = self.stop(states=("running",), pids=[4242],
                                         force=True, launched=(999,))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_launched_here")
        self.assertIn("4242", result["detail"])
        self.assertEqual(kernel.terminated, [],
                         "TerminateProcess was called for a process this server "
                         "did not start")
        self.assertEqual([hwnd for hwnd, _ in user.posted], [11],
                         "the graceful close is always allowed, and did not run")
        self.assertFalse(result["forced"])

    def test_force_terminates_only_after_the_graceful_wait_timed_out(self):
        result, user, kernel = self.stop(states=("running",), pids=[4242],
                                         force=True, launched=(4242,))
        self.assertEqual(kernel.terminated, [4242])
        self.assertTrue(result["forced"])
        self.assertEqual(result["terminated"], [4242])
        self.assertEqual(kernel.opened, [4242])
        self.assertEqual(len(kernel.closed), 1, "the process handle leaked")

    def test_a_graceful_close_never_terminates_even_with_force(self):
        result, user, kernel = self.stop(states=("running", "not_running"),
                                         pids=[4242], force=True, launched=(4242,))
        self.assertTrue(result["exited"])
        self.assertFalse(result["forced"])
        self.assertEqual(kernel.terminated, [],
                         "force terminated a process that had already closed")

    def test_a_snapshot_that_breaks_mid_wait_is_never_read_as_still_running(self):
        # The gate goes running -> unknown after the close was posted. Saying
        # "still there" would be the sentinel-equals-real-value bug, and the
        # force path must not run against a pid list that is empty only because
        # nothing could be read.
        result, user, kernel = self.stop(states=("running", "unknown"),
                                         pids=[4242], force=True, launched=(4242,))
        self.assertEqual([hwnd for hwnd, _ in user.posted], [11])
        self.assertFalse(result["exited"])
        self.assertEqual(result["game_state"], "unknown")
        self.assertIn("can no longer be determined", result["detail"])
        self.assertEqual(kernel.terminated, [])
        self.assertFalse(result["forced"])

    def test_a_window_that_will_not_close_is_reported_not_forced_silently(self):
        result, user, kernel = self.stop(states=("running",), pids=[4242])
        self.assertFalse(result["exited"])
        self.assertFalse(result["forced"])
        self.assertEqual(kernel.terminated, [])
        self.assertIn("force", result["detail"])

    def test_a_failed_open_process_is_reported_rather_than_read_as_success(self):
        kernel = FakeKernel32(open_fails=True)
        result, _, kernel = self.stop(states=("running",), pids=[4242], force=True,
                                      launched=(4242,), kernel=kernel)
        self.assertEqual(kernel.terminated, [])
        self.assertFalse(result["exited"])
        self.assertIn("OpenProcess", str(result["errors"]))


@unittest.skipIf(SKIP_REASON is not None, SKIP_REASON or "")
class WindowEnumerationTests(unittest.TestCase):
    """The helper both `hs_stop_game` and `hs_screenshot` are built on.

    It is asserted here as well as in the screenshot suite because the stop path
    would otherwise depend on it without ever testing the pointer marshalling
    it does -- and `GetWindowThreadProcessId` filling a `DWORD` through a
    pointer is exactly the sort of call that silently returns everyone's
    windows when it is written wrong.
    """

    def windows(self):
        return [
            {"hwnd": 21, "pid": 5, "visible": True, "minimized": False,
             "rect": (0, 0, 100, 100)},
            {"hwnd": 22, "pid": 5, "visible": True, "minimized": False,
             "rect": (0, 0, 400, 400)},
            {"hwnd": 23, "pid": 5, "visible": False, "minimized": False,
             "rect": (0, 0, 900, 900)},
            {"hwnd": 24, "pid": 6, "visible": True, "minimized": True,
             "rect": (10, 10, 110, 110)},
        ]

    def enumerate(self, pids):
        user = FakeUser32(self.windows())
        with patch.object(capture, "user32", return_value=user):
            return capture.visible_windows_for_pids(pids)

    def test_only_visible_windows_of_the_named_pids_come_back(self):
        found = self.enumerate([5])
        self.assertEqual([window["hwnd"] for window in found], [21, 22])
        self.assertEqual({window["pid"] for window in found}, {5})

    def test_each_window_carries_its_rect_area_and_minimized_flag(self):
        largest = max(self.enumerate([5]), key=lambda window: window["area"])
        self.assertEqual(largest["hwnd"], 22)
        self.assertEqual(largest["bbox"], (0, 0, 400, 400))
        self.assertEqual(largest["area"], 160_000)
        self.assertFalse(largest["minimized"])
        self.assertTrue(self.enumerate([6])[0]["minimized"])

    def test_an_unknown_pid_enumerates_to_nothing(self):
        self.assertEqual(self.enumerate([12345]), [])

    def test_the_real_enumeration_sees_this_process_s_own_windows_or_none(self):
        # A positive control for the real user32 path: it must return a list
        # without raising, and every entry must belong to a pid that was asked
        # for. A console session legitimately has no visible window, so an
        # empty list is allowed -- but a raised exception or someone else's
        # window is not.
        found = capture.visible_windows_for_pids([os.getpid()])
        self.assertIsInstance(found, list)
        for window in found:
            self.assertEqual(window["pid"], os.getpid())


if __name__ == "__main__":
    unittest.main()

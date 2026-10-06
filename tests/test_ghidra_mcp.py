"""tools/ghidra_mcp.py: the `ghidra` MCP server's launcher.

Every case runs on temp-directory fixtures: a fake Ghidra tree of empty jars, a
fake project, and a stand-in HTTP server. Nothing here starts Java, reads the
real Ghidra project, or touches port 8089.

What is pinned is the launcher's own contract, the part a careless edit could
quietly break:
- it never puts the project copy or its server files inside a git tree;
- the server binds to loopback, has script execution stripped from its
  environment, and has its file endpoints confined to the project's directory;
- the classpath carries the release jar first and Ghidra's jar directories, and
  goes through an @argfile rather than the command line;
- only a GhidraMCP server of the pinned version counts as "ours" on the port;
- `.mcp.json` starts it the way `hs-drive` is started, and Codex gets the same.
Each acceptance has a negative control beside it.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import ghidra_mcp  # noqa: E402


def _cfg(base: Path, **over) -> ghidra_mcp.Config:
    values = dict(
        ghidra=base / "ghidra_12.1.4_PUBLIC",
        home=base / "tools" / "ghidra-mcp",
        source_project=base / "projects" / "HeroSiege.gpr",
        project=base / "projects" / "mcp" / "HeroSiege.gpr",
        program="/Hero_Siege.exe",
        port=8089,
    )
    values.update(over)
    return ghidra_mcp.Config(**values)


def _fake_ghidra(root: Path) -> None:
    for kind, module in (("Framework", "Generic"), ("Features", "Base"), ("Processors", "x86"), ("Extensions", "Other")):
        lib = root / "Ghidra" / kind / module / "lib"
        lib.mkdir(parents=True)
        (lib / f"{module}.jar").write_bytes(b"")


def _complete(cfg: ghidra_mcp.Config) -> None:
    """Everything `problems()` asks for, as empty stand-ins."""
    _fake_ghidra(cfg.ghidra)
    cfg.bridge.parent.mkdir(parents=True)
    cfg.bridge.write_bytes(b"")
    cfg.jar.write_bytes(b"")
    cfg.project.parent.mkdir(parents=True)
    cfg.project.write_text("")


class ConfigTests(unittest.TestCase):
    def test_defaults_follow_the_conventional_paths(self):
        with tempfile.TemporaryDirectory() as d:
            user = Path(d)
            (user / "tools" / "ghidra_12.0.1_PUBLIC").mkdir(parents=True)
            (user / "tools" / "ghidra_12.1.4_PUBLIC").mkdir()
            cfg = ghidra_mcp.load_config({"USERPROFILE": str(user)})
            self.assertEqual(cfg.ghidra, user / "tools" / "ghidra_12.1.4_PUBLIC")
            self.assertEqual(cfg.source_project, user / "ghidra_projects" / "HeroSiege.gpr")
            self.assertEqual(cfg.project, user / "ghidra_projects" / "mcp" / "HeroSiege.gpr")
            self.assertNotEqual(cfg.project, cfg.source_project)
            self.assertEqual(cfg.url, "http://127.0.0.1:8089")

    def test_env_overrides_each_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ghidra_mcp.load_config({
                "USERPROFILE": d, "GHIDRA_INSTALL_DIR": "G", "HS_GHIDRA_MCP_HOME": "H",
                "HS_GHIDRA_MCP_PROJECT": "P.gpr", "HS_GHIDRA_MCP_PORT": "9001",
            })
            self.assertEqual((cfg.ghidra, cfg.home, cfg.project, cfg.port), (Path("G"), Path("H"), Path("P.gpr"), 9001))

    def test_missing_pieces_are_named_with_their_fix(self):
        with tempfile.TemporaryDirectory() as d:
            found = ghidra_mcp.problems(_cfg(Path(d)))
            self.assertEqual(len(found), 3)
            self.assertTrue(any("GHIDRA_INSTALL_DIR" in p for p in found))
            self.assertTrue(all("setup" in p for p in found[1:]))


class GitRefusalTests(unittest.TestCase):
    def test_refuses_a_path_inside_a_git_tree(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            (repo / "sub").mkdir(parents=True)
            (repo / ".git").write_text("gitdir: elsewhere")  # a worktree's .git is a file
            with self.assertRaises(SystemExit) as cm:
                ghidra_mcp.refuse_inside_git(repo / "sub" / "HeroSiege.gpr", "project copy")
            self.assertIn("Legal", str(cm.exception))

    def test_allows_a_path_outside_any_git_tree(self):
        with tempfile.TemporaryDirectory() as d:
            ghidra_mcp.refuse_inside_git(Path(d) / "mcp" / "HeroSiege.gpr", "project copy")

    def test_setup_refuses_a_home_inside_this_repository(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d), home=ROOT / ".claude" / "scratch" / "ghidra-mcp")
            with self.assertRaises(SystemExit):
                ghidra_mcp.setup(cfg, refresh_project=False)
            self.assertFalse(cfg.home.exists())


class ServerCommandTests(unittest.TestCase):
    def test_binds_loopback_and_uses_an_argfile_classpath(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            cfg = _cfg(base)
            _fake_ghidra(cfg.ghidra)
            cfg.home.mkdir(parents=True)
            cmd = ghidra_mcp.server_command(cfg)
            self.assertEqual(cmd[cmd.index("--bind") + 1], "127.0.0.1")
            self.assertEqual(cmd[cmd.index("--project") + 1], str(cfg.project))
            self.assertIn(f"@{cfg.argfile}", cmd)
            self.assertFalse(any(".jar" in a for a in cmd), "the classpath belongs in the argfile")
            cp = cfg.argfile.read_text(encoding="utf-8")
            self.assertTrue(cp.startswith('-classpath "'))
            entries = cp.split('"')[1].split(os.pathsep)
            self.assertEqual(Path(entries[0]).name, ghidra_mcp.JAR)
            names = {Path(e).name for e in entries}
            self.assertEqual(names, {ghidra_mcp.JAR, "Generic.jar", "Base.jar", "x86.jar"})
            self.assertNotIn("Other.jar", names)  # Extensions is not on the server's classpath

    def test_environment_strips_scripts_and_confines_files(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            os.environ["GHIDRA_MCP_ALLOW_SCRIPTS"] = "1"
            os.environ["GHIDRA_MCP_BIND_ADDRESS"] = "0.0.0.0"
            try:
                env = ghidra_mcp.server_env(cfg)
            finally:
                del os.environ["GHIDRA_MCP_ALLOW_SCRIPTS"], os.environ["GHIDRA_MCP_BIND_ADDRESS"]
            self.assertNotIn("GHIDRA_MCP_ALLOW_SCRIPTS", env)
            self.assertNotIn("GHIDRA_MCP_BIND_ADDRESS", env)
            self.assertEqual(env["GHIDRA_MCP_FILE_ROOT"], str(cfg.project.parent))
            self.assertIn("PATH", env)  # control: the rest of the environment passes through


class _Health(http.server.BaseHTTPRequestHandler):
    body = b"{}"

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):
        pass


class HealthTests(unittest.TestCase):
    def _serve(self, payload: dict) -> int:
        handler = type("H", (_Health,), {"body": json.dumps(payload).encode()})
        srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def test_accepts_the_pinned_headless_version(self):
        port = self._serve({"status": "healthy", "version": f"{ghidra_mcp.VERSION}-headless", "program_loaded": True})
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(ghidra_mcp.health(_cfg(Path(d), port=port))["program_loaded"])

    def test_rejects_another_service_on_the_port(self):
        port = self._serve({"status": "healthy", "version": "5.14.2"})
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d), port=port)
            self.assertIsNone(ghidra_mcp.health(cfg))
            # Everything else present, so start() reaches the port check: it must
            # neither adopt the foreign service nor launch a server beside it.
            _complete(cfg)
            self.assertEqual(ghidra_mcp.problems(cfg), [])
            with self.assertRaises(SystemExit) as cm:
                ghidra_mcp.start(cfg)
            self.assertIn("not as GhidraMCP", str(cm.exception))


_HOLD_LOCK = """
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from tools import ghidra_mcp
cfg = ghidra_mcp.Config(None, Path(sys.argv[2]), Path("s.gpr"), Path("p.gpr"), "/x", 1)
with ghidra_mcp.spawn_lock(cfg, timeout=5):
    print("held", flush=True)
    time.sleep(float(sys.argv[3]))
"""


class _Proc:
    pid = 4242

    def __init__(self, code):
        self.code = code
        self.killed = False

    def poll(self):
        return self.code

    def kill(self):
        self.killed = True


class StartRaceTests(unittest.TestCase):
    """PR #449 review: sessions starting together must launch one server, and a
    launch that never turns healthy must not leave a server running behind it."""

    def _held_elsewhere(self, home: Path, seconds: float) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", _HOLD_LOCK, str(ROOT), str(home), str(seconds)],
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait)
        self.assertEqual(proc.stdout.readline().strip(), "held")
        return proc

    def test_lock_excludes_another_process_until_it_lets_go(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            self._held_elsewhere(cfg.home, 2)
            with self.assertRaises(SystemExit):
                with ghidra_mcp.spawn_lock(cfg, timeout=0.5):
                    pass
            # control: the same call, given time for the holder to finish, gets it
            t = time.monotonic()
            with ghidra_mcp.spawn_lock(cfg, timeout=10):
                pass
            self.assertLess(time.monotonic() - t, 10)

    def test_start_rechecks_health_once_the_lock_is_held(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            up = {"version": f"{ghidra_mcp.VERSION}-headless", "program_loaded": True}
            with mock.patch.object(ghidra_mcp, "health", side_effect=[None, up]), \
                    mock.patch.object(ghidra_mcp, "launch") as launch:
                self.assertEqual(ghidra_mcp.start(cfg), up)
            launch.assert_not_called()
            # control: still nothing after the lock, so this session launches
            with mock.patch.object(ghidra_mcp, "health", side_effect=[None, None]), \
                    mock.patch.object(ghidra_mcp, "launch", return_value=up) as launch:
                ghidra_mcp.start(cfg)
            launch.assert_called_once()

    def _launch(self, cfg, proc, healths, clock):
        _complete(cfg)
        with mock.patch.object(ghidra_mcp, "_request", return_value=None), \
                mock.patch.object(ghidra_mcp, "health", side_effect=healths), \
                mock.patch.object(ghidra_mcp.subprocess, "Popen", return_value=proc), \
                mock.patch.object(ghidra_mcp.time, "monotonic", side_effect=clock), \
                mock.patch.object(ghidra_mcp.time, "sleep"):
            return ghidra_mcp.launch(cfg, wait=30)

    def test_an_exited_launch_still_finds_a_healthy_server(self):
        with tempfile.TemporaryDirectory() as d:
            up = {"version": f"{ghidra_mcp.VERSION}-headless"}
            proc = _Proc(1)
            self.assertEqual(self._launch(_cfg(Path(d)), proc, [None, None, up], [0, 1, 2]), up)
            self.assertFalse(proc.killed)

    def test_a_launch_past_its_deadline_is_killed(self):
        with tempfile.TemporaryDirectory() as d:
            proc = _Proc(None)
            with self.assertRaises(SystemExit) as cm:
                self._launch(_cfg(Path(d)), proc, [None, None], [0, 5, 31])
            self.assertTrue(proc.killed)
            self.assertIn("killed it", str(cm.exception))
            # control: one that already exited is reported, not killed
            proc = _Proc(1)
            with self.assertRaises(SystemExit) as cm:
                self._launch(_cfg(Path(d) / "b"), proc, [None], [0, 31])
            self.assertFalse(proc.killed)
            self.assertIn("exited with 1", str(cm.exception))


class StopTests(unittest.TestCase):
    """`stop` finds the server by the process holding the port and kills it only
    if that process runs GhidraMCP's server on this project copy (PR #449
    review: a pid file went stale, or was never written)."""

    def _stop(self, cfg, pid, cmdline):
        with mock.patch.object(ghidra_mcp, "listener_pid", return_value=pid), \
                mock.patch.object(ghidra_mcp, "command_line", return_value=cmdline), \
                mock.patch.object(ghidra_mcp.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0)) as run:
            return ghidra_mcp.stop(cfg), run

    def test_kills_the_server_on_this_project(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            cmd = f"java -Xmx4g {ghidra_mcp.SERVER_CLASS} --bind 127.0.0.1 --project {cfg.project}"
            rc, run = self._stop(cfg, 777, cmd)
            self.assertEqual(rc, 0)
            self.assertIn("777", run.call_args.args[0])
            self.assertNotIn("/T", run.call_args.args[0])  # the process, not a tree

    def test_kills_nothing_when_another_process_holds_the_port(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = _cfg(Path(d))
            for cmd in ("C:\\Windows\\notepad.exe",  # a reused pid
                        f"java {ghidra_mcp.SERVER_CLASS} --project C:\\elsewhere\\Other.gpr"):  # another project
                rc, run = self._stop(cfg, 777, cmd)
                self.assertEqual(rc, 1)
                run.assert_not_called()

    def test_kills_nothing_when_the_port_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            rc, run = self._stop(_cfg(Path(d)), None, "")
            self.assertEqual(rc, 0)
            run.assert_not_called()


class WiringTests(unittest.TestCase):
    def test_mcp_json_and_codex_start_it_like_hs_drive(self):
        servers = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(servers["ghidra"], {"command": "py", "args": ["-3", "-m", "tools.ghidra_mcp"]})
        self.assertEqual(servers["hs-drive"]["args"][:2], ["-3", "-m"])
        codex = (ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('[mcp_servers.ghidra]\ncommand = "py"\nargs = ["-3", "-m", "tools.ghidra_mcp"]', codex)

    def test_pinned_release_digests_are_full_sha256(self):
        self.assertEqual(set(ghidra_mcp.SHA256), {ghidra_mcp.ZIP, ghidra_mcp.WHEEL})
        for digest in ghidra_mcp.SHA256.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

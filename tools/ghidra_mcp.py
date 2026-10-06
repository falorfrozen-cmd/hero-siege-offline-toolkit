#!/usr/bin/env python3
"""ghidra_mcp.py -- the `ghidra` MCP server: Hero Siege's Ghidra project over MCP.

`.mcp.json` starts this as `py -3 -m tools.ghidra_mcp`. It serves
[bethington/ghidra-mcp](https://github.com/bethington/ghidra-mcp) (Apache-2.0),
pinned below, in two parts:

- a **headless Java server** (`GhidraMCPHeadlessServer`, from the release jar)
  that opens a Ghidra project and answers REST calls on 127.0.0.1:8089. It is
  shared: the first session to need it starts it detached, and every later
  session, worktree or Codex run talks to the same one. A Ghidra project takes
  one lock, so one server per project is the only arrangement that lets
  concurrent sessions in `.claude/worktrees/` all use it.
- the release's **Python stdio bridge** (`bridge-mcp-ghidra`), which this
  process runs in the foreground with the agent's stdin/stdout.

The server opens a **copy** of the research project, never the project itself
(`~/ghidra_projects/mcp/HeroSiege.gpr` from `~/ghidra_projects/HeroSiege.gpr`),
so its lock, its saves and any rename it makes never block or alter the project
that `ForgePact/tools/ghidra/DecompileTo.java` and the GUI use. Refresh the copy
with `setup --refresh-project` after `ImportSymbols.java` changes the source.

Why this server and not pyghidra-mcp: that one refuses every call on a program
Ghidra does not mark as auto-analyzed, and our project is imported with
`-noanalysis` on purpose (307,150 functions; a full pass takes hours). This one
decompiles on demand, like `DecompileTo.java` does.

Subcommands (all paths overridable, see `Config`):

    py -3 -m tools.ghidra_mcp            # stdio MCP server (what .mcp.json runs)
    py -3 -m tools.ghidra_mcp status     # resolved paths, server health
    py -3 -m tools.ghidra_mcp start      # start the shared server, wait for it
    py -3 -m tools.ghidra_mcp stop       # stop the server on this project copy
    py -3 -m tools.ghidra_mcp setup [--refresh-project]
        # download + sha256-check the pinned release, make the bridge venv,
        # copy the project. Downloads: ask the owner first.

Everything this writes (jar, venv, log, lock, project copy) lives outside any
git checkout; it refuses otherwise, because the project copy and the server's
caches hold decompiled game code. Decompiled output reaching the agent is fine;
it reaching a tracked file is not (AGENTS.md § "Legal").

The server binds to loopback only, keeps script execution off
(`GHIDRA_MCP_ALLOW_SCRIPTS` is removed from its environment), and confines its
file-path endpoints to the project copy's directory (`GHIDRA_MCP_FILE_ROOT`).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.decomp_index import git_tree_of  # noqa: E402

VERSION = "6.0.0"
RELEASE = f"https://github.com/bethington/ghidra-mcp/releases/download/v{VERSION}"
JAR = f"GhidraMCP-{VERSION}.jar"
ZIP = f"GhidraMCP-{VERSION}.zip"
WHEEL = f"ghidra_mcp_bridge-{VERSION}-py3-none-any.whl"
# The release's own digests (GitHub asset `digest` fields), checked on download.
SHA256 = {
    ZIP: "867731de27d5143632a010943b907a6485dd54d0e19729e2f85ee9f692c99873",
    WHEEL: "71939a890009826664720166d8f786f3a2ea2460f7effcd83c73759ba4241334",
}
SERVER_CLASS = "com.xebyte.headless.GhidraMCPHeadlessServer"
# Ghidra's own jar directories the headless server needs, as in the release's
# docker/entrypoint.sh.
JAR_DIRS = ("Framework", "Features", "Processors")


@dataclass
class Config:
    ghidra: Path | None
    home: Path
    source_project: Path
    project: Path
    program: str
    port: int

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def jar(self) -> Path:
        return self.home / JAR

    @property
    def bridge(self) -> Path:
        scripts = "Scripts" if os.name == "nt" else "bin"
        exe = "bridge-mcp-ghidra.exe" if os.name == "nt" else "bridge-mcp-ghidra"
        return self.home / "venv" / scripts / exe

    @property
    def log(self) -> Path:
        return self.home / "server.log"

    @property
    def argfile(self) -> Path:
        return self.home / "server.args"


def _newest_ghidra(tools: Path) -> Path | None:
    found = sorted(p for p in tools.glob("ghidra_*_PUBLIC") if p.is_dir())
    return found[-1] if found else None


def load_config(env: dict[str, str] | None = None) -> Config:
    """Defaults follow AGENTS.md's conventional paths; each has an env override."""
    env = os.environ if env is None else env
    user = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    tools = user / "tools"
    projects = user / "ghidra_projects"
    ghidra = env.get("GHIDRA_INSTALL_DIR")
    return Config(
        ghidra=Path(ghidra) if ghidra else _newest_ghidra(tools),
        home=Path(env.get("HS_GHIDRA_MCP_HOME") or tools / f"ghidra-mcp-{VERSION}"),
        source_project=Path(env.get("HS_GHIDRA_SOURCE_PROJECT") or projects / "HeroSiege.gpr"),
        project=Path(env.get("HS_GHIDRA_MCP_PROJECT") or projects / "mcp" / "HeroSiege.gpr"),
        program=env.get("HS_GHIDRA_MCP_PROGRAM") or "/Hero_Siege.exe",
        port=int(env.get("HS_GHIDRA_MCP_PORT") or 8089),
    )


def refuse_inside_git(path: Path, what: str) -> None:
    tree = git_tree_of(path)
    if tree is not None:
        raise SystemExit(
            f"ghidra_mcp: refusing to use {path} as the {what}: {tree} is a git tree. "
            "The project copy and the server's files hold decompiled game code and stay "
            "outside every repository (AGENTS.md § Legal)."
        )


def problems(cfg: Config) -> list[str]:
    """What is missing before the server can start, each with its fix."""
    out = []
    if cfg.ghidra is None or not (cfg.ghidra / "Ghidra").is_dir():
        out.append(f"no Ghidra install at {cfg.ghidra} (set GHIDRA_INSTALL_DIR)")
    if not cfg.jar.is_file() or not cfg.bridge.is_file():
        out.append(f"no GhidraMCP {VERSION} in {cfg.home} (run: py -3 -m tools.ghidra_mcp setup)")
    if not cfg.project.is_file():
        out.append(f"no project copy at {cfg.project} (run: py -3 -m tools.ghidra_mcp setup)")
    return out


def classpath(cfg: Config) -> list[Path]:
    assert cfg.ghidra is not None
    jars = [cfg.jar]
    for kind in JAR_DIRS:
        jars += sorted((cfg.ghidra / "Ghidra" / kind).glob("*/lib/*.jar"))
    return jars


def java_exe(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    home = env.get("JAVA_HOME")
    if home:
        exe = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if exe.is_file():
            return str(exe)
    return shutil.which("java") or "java"


def server_command(cfg: Config) -> list[str]:
    """The java command line. The classpath goes in an @argfile: Ghidra's jar list
    is long enough to threaten Windows' 32 KB command-line limit."""
    cp = os.pathsep.join(str(p) for p in classpath(cfg))
    cfg.argfile.write_text(f'-classpath "{cp}"\n'.replace("\\", "/"), encoding="utf-8")
    return [
        java_exe(), "-Xmx4g", f"-Dghidra.home={cfg.ghidra}", "-Dapplication.name=GhidraMCP",
        f"@{cfg.argfile}", SERVER_CLASS,
        "--bind", "127.0.0.1", "--port", str(cfg.port), "--project", str(cfg.project),
    ]


def server_env(cfg: Config) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("GHIDRA_MCP_ALLOW_SCRIPTS", None)
    env.pop("GHIDRA_MCP_BIND_ADDRESS", None)
    env["GHIDRA_MCP_FILE_ROOT"] = str(cfg.project.parent)
    return env


def _request(cfg: Config, path: str, body: dict | None = None, timeout: float = 3) -> dict | None:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(cfg.url + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def health(cfg: Config) -> dict | None:
    """The /health of a GhidraMCP headless server of the pinned version, or None.
    Another service on the port (the GUI plugin, another tool, another version)
    is None. Which *project* it serves is `adopt`'s question, not this one's."""
    h = _request(cfg, "/health")
    if not h or h.get("version") != f"{VERSION}-headless":
        return None
    return h


def adopt(cfg: Config) -> dict | None:
    """`health`, but only for the server on *this* project copy.

    A headless server on another project (one started by hand on the original
    research project, or another checkout's `HS_GHIDRA_MCP_PROJECT`) answers
    /health just the same, and adopting it would send every call, writes
    included, to that project (PR #449 review). So the process holding the port
    must run the server class on this copy; otherwise refuse, never adopt.
    """
    h = health(cfg)
    if h is None:
        return None
    pid = listener_pid(cfg.port)
    if pid is None or not is_our_server(command_line(pid), cfg):
        raise SystemExit(f"ghidra_mcp: port {cfg.port} is held by a GhidraMCP server (pid {pid}) that is "
                         f"not serving {cfg.project}; refusing to use it (stop it, or set HS_GHIDRA_MCP_PORT)")
    return h


@contextlib.contextmanager
def spawn_lock(cfg: Config, timeout: float):
    """Hold `<home>/server.lock` exclusively, across processes.

    Sessions start together (Claude Code and Codex, two worktrees), and `/health`
    stays silent for the ~9 s a cold JVM takes to boot, so without this each one
    sees no server and launches its own against the same port and project. The
    OS releases the lock if its holder dies, so a crashed session cannot wedge it.
    """
    cfg.home.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with open(cfg.home / "server.lock", "a+b") as f:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise SystemExit(f"ghidra_mcp: another session held {f.name} for {timeout:.0f}s")
                time.sleep(0.2)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def launch(cfg: Config, wait: float) -> dict:
    """Start the server and wait for it. Call only while holding `spawn_lock`."""
    missing = problems(cfg)
    if missing:
        raise SystemExit("ghidra_mcp: cannot start the server:\n  " + "\n  ".join(missing))
    refuse_inside_git(cfg.project, "project copy")
    refuse_inside_git(cfg.home, "server directory")
    if _request(cfg, "/health") is not None:
        raise SystemExit(f"ghidra_mcp: port {cfg.port} answers, but not as GhidraMCP {VERSION} "
                         "headless (set HS_GHIDRA_MCP_PORT)")
    flags = 0
    if os.name == "nt":  # outlive this session; no console window
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    with open(cfg.log, "ab") as log:
        proc = subprocess.Popen(server_command(cfg), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                env=server_env(cfg), creationflags=flags, start_new_session=os.name != "nt")
    deadline = time.monotonic() + wait
    # An exit is not the end: a server launched outside this lock (by hand, or
    # an older launcher) may own the port, so keep asking until the deadline.
    while (h := adopt(cfg)) is None:
        if time.monotonic() > deadline:
            code = proc.poll()
            if code is None:  # ours and never healthy: don't leave it holding the project
                proc.kill()
            state = f"exited with {code}" if code is not None else f"not healthy after {wait:.0f}s; killed it"
            raise SystemExit(f"ghidra_mcp: server {state}; see {cfg.log}")
        time.sleep(1)
    return h


def start(cfg: Config, wait: float = 120) -> dict:
    """Return the server's health, starting the shared server first if needed."""
    h = adopt(cfg)
    if h is None or not h.get("program_loaded"):
        # The program load runs under the lock too, so sessions don't race to load it.
        with spawn_lock(cfg, timeout=wait + 330):
            h = adopt(cfg)  # another session may have finished while we waited
            if h is None:
                h = launch(cfg, wait)
            if not h.get("program_loaded"):
                r = _request(cfg, "/load_program_from_project", {"path": cfg.program}, timeout=300)
                if not r or not r.get("success"):
                    raise SystemExit(f"ghidra_mcp: could not load {cfg.program}: {r}")
                h = health(cfg) or h
    return h


def listener_pid(port: int) -> int | None:
    """The pid listening on 127.0.0.1:<port>, or None."""
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            cols = line.split()
            if len(cols) == 5 and cols[1] == f"127.0.0.1:{port}" and cols[3] == "LISTENING":
                return int(cols[4])
        return None
    out = subprocess.run(["lsof", "-nP", f"-iTCP@127.0.0.1:{port}", "-sTCP:LISTEN", "-t"],
                         capture_output=True, text=True).stdout.split()
    return int(out[0]) if out else None


def command_line(pid: int) -> str:
    if os.name == "nt":
        ps = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
        return subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True).stdout.strip()
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def is_our_server(cmdline: str, cfg: Config) -> bool:
    """A GhidraMCP headless server on *this* project copy, by what it runs."""
    norm = (lambda s: s.lower().replace("\\", "/")) if os.name == "nt" else (lambda s: s)
    return SERVER_CLASS in cmdline and norm(str(cfg.project)) in norm(cmdline)


def stop(cfg: Config) -> int:
    """Stop the server for this project copy, never anything else.

    It is found by the process listening on the port, and killed only if that
    process runs GhidraMCP's server class on this project copy. A pid file was
    tried first and failed both ways (PR #449 review): a launcher killed before
    `/health` answered left the server unrecorded, and a stale pid survives a
    crash or reboot to name an unrelated process.
    """
    pid = listener_pid(cfg.port)
    if pid is None:
        print(f"ghidra_mcp: nothing listens on 127.0.0.1:{cfg.port}; killed nothing")
        return 0
    if not is_our_server(command_line(pid), cfg):
        print(f"ghidra_mcp: pid {pid} holds port {cfg.port} but is not the GhidraMCP server for "
              f"{cfg.project}; killed nothing")
        return 1
    if os.name == "nt":
        rc = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True).returncode
    else:
        rc = subprocess.run(["kill", str(pid)]).returncode
    print(f"ghidra_mcp: stopped server pid {pid}" if rc == 0 else f"ghidra_mcp: could not stop pid {pid}")
    return 0 if rc == 0 else 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(name: str, dest: Path) -> Path:
    out = dest / name
    if not out.is_file() or _sha256(out) != SHA256[name]:
        print(f"downloading {RELEASE}/{name}")
        urllib.request.urlretrieve(f"{RELEASE}/{name}", out)
    if _sha256(out) != SHA256[name]:
        out.unlink()
        raise SystemExit(f"ghidra_mcp: {name} does not match its pinned sha256; refusing it")
    return out


def copy_project(cfg: Config, refresh: bool) -> None:
    src_rep = cfg.source_project.with_suffix(".rep")
    dst_rep = cfg.project.with_suffix(".rep")
    if cfg.project.is_file() and not refresh:
        print(f"project copy present: {cfg.project}")
        return
    if health(cfg) is not None:
        raise SystemExit("ghidra_mcp: stop the server before refreshing its project (stop)")
    if not cfg.source_project.is_file() or not src_rep.is_dir():
        raise SystemExit(f"ghidra_mcp: no source project at {cfg.source_project}")
    cfg.project.parent.mkdir(parents=True, exist_ok=True)
    if dst_rep.exists():
        shutil.rmtree(dst_rep)
    # The .gpr and .rep only: a source .lock belongs to whoever has it open.
    shutil.copy2(cfg.source_project, cfg.project)
    shutil.copytree(src_rep, dst_rep)
    print(f"copied {cfg.source_project} -> {cfg.project}")


def setup(cfg: Config, refresh_project: bool) -> int:
    refuse_inside_git(cfg.home, "server directory")
    refuse_inside_git(cfg.project, "project copy")
    cfg.home.mkdir(parents=True, exist_ok=True)
    if not cfg.jar.is_file():
        import zipfile
        with zipfile.ZipFile(_fetch(ZIP, cfg.home)) as z:
            cfg.jar.write_bytes(z.read(f"GhidraMCP/lib/{JAR}"))
    wheel = _fetch(WHEEL, cfg.home)
    if not cfg.bridge.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(cfg.home / "venv")], check=True)
        py = cfg.bridge.parent / ("python.exe" if os.name == "nt" else "python")
        subprocess.run([str(py), "-m", "pip", "install", "-q", str(wheel)], check=True)
    copy_project(cfg, refresh_project)
    left = problems(cfg)
    print("ready" if not left else "still missing:\n  " + "\n  ".join(left))
    return 0 if not left else 1


def status(cfg: Config) -> int:
    for k in ("ghidra", "home", "source_project", "project", "program", "url"):
        print(f"{k:15} {getattr(cfg, k)}")
    for p in problems(cfg):
        print(f"missing        {p}")
    print(f"{'server':15} {health(cfg) or 'not running'}")
    return 0


def serve(cfg: Config) -> int:
    """stdio MCP: make sure the shared server is up, then hand stdio to the bridge.
    Nothing may be printed to stdout before the bridge owns it."""
    start(cfg)
    env = dict(os.environ, GHIDRA_MCP_URL=cfg.url)
    return subprocess.run([str(cfg.bridge), "--transport", "stdio"], env=env).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ghidra_mcp", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    sub.add_parser("status")
    sub.add_parser("start")
    sub.add_parser("stop")
    s = sub.add_parser("setup")
    s.add_argument("--refresh-project", action="store_true", help="re-copy the source project")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.cmd in (None, "serve"):
        return serve(cfg)
    if args.cmd == "status":
        return status(cfg)
    if args.cmd == "start":
        print(json.dumps(start(cfg)))
        return 0
    if args.cmd == "stop":
        return stop(cfg)
    return setup(cfg, args.refresh_project)


if __name__ == "__main__":
    sys.exit(main())

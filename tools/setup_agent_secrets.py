#!/usr/bin/env python3
"""Ask for the personal access tokens the shared MCP servers need, once per machine.

`.mcp.json` (Claude Code) and `.codex/config.toml` (Codex) name tokens only by
environment variable, so no token is ever in the repository. This script asks
for each one that is not set yet and saves it as a persistent **user**
environment variable, which every program started afterwards inherits: Claude
Code, Codex, a terminal. Where you keep the tokens between machines is up to
you; this only puts them where the tools look.

    py -3 tools/setup_agent_secrets.py            # ask for anything missing
    py -3 tools/setup_agent_secrets.py --force    # ask again for every token
    py -3 tools/setup_agent_secrets.py --list     # set / SESSION (this shell only) / MISSING; never values

Input is not echoed. An empty answer skips that token. Restart Claude Code and
Codex afterwards: a process reads its environment only at launch.

On Windows the value goes to HKCU\\Environment, and only a value found there
counts as set: one set for the current shell alone is offered for saving.
Elsewhere the script asks for nothing and saves nothing; it prints the
`export` line for each missing token, to add to your shell profile yourself.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Secret:
    name: str
    server: str
    how: str
    #: Offer the gh CLI's own token when the answer is empty.
    gh_fallback: bool = False


#: Every `${VAR}` a server in `.mcp.json` reads must be listed here;
#: tests/test_agent_tooling_sync.py checks that.
SECRETS = (
    Secret(
        "GITHUB_MCP_PAT",
        "github",
        "a GitHub personal access token (github.com/settings/tokens)",
        gh_fallback=True,
    ),
    Secret(
        "FIGMA_API_KEY",
        "figma",
        "a Figma personal access token (Figma > Settings > Security > Personal access tokens)",
    ),
)


def _persisted(name: str) -> bool:
    """Whether a newly launched program will see `name`. On Windows that is
    the user's registry environment only: a value set for this shell session
    alone (`$env:NAME = ...`, a CI variable) dies with it, so it must not
    count. Elsewhere the script cannot tell where a variable came from, so it
    goes by this process's environment."""
    if sys.platform != "win32":
        return bool(os.environ.get(name))
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return bool(value)
    except OSError:
        return False


def _save(name: str, value: str) -> None:
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    # Tell running programs (Explorer, new terminals) the environment changed.
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None
    )
    print(f"  Saved {name} for your Windows user.")


def _gh_token() -> str | None:
    if not shutil.which("gh"):
        return None
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="ask again even for tokens already set")
    parser.add_argument("--list", action="store_true", help="report which tokens are set, and ask nothing")
    args = parser.parse_args(argv)

    changed = False
    for secret in SECRETS:
        present = _persisted(secret.name)
        session_only = not present and bool(os.environ.get(secret.name))
        if args.list:
            state = "set" if present else ("SESSION" if session_only else "MISSING")
            print(f"{secret.name:16} {state:8} ({secret.server} MCP server)")
            continue
        if present and not args.force:
            print(f"{secret.name} is already set; skipping (--force to replace it).")
            continue
        print(f"\n{secret.name}: {secret.how}, for the `{secret.server}` MCP server.")
        if sys.platform != "win32":
            # Nothing is written outside Windows, so asking for the token
            # would only pretend to save it.
            print("  Add this to your shell profile (~/.bashrc, ~/.zshrc), then open a new shell:\n"
                  f"    export {secret.name}='<the token>'")
            continue
        if session_only:
            print("  It is set in this shell only, so newly started programs will not see it.")
        prompt = "  Paste it (input hidden"
        if session_only:
            prompt += ", Enter to save this session's value"
        elif secret.gh_fallback:
            prompt += ", Enter to use your gh CLI login"
        else:
            prompt += ", Enter to skip"
        value = getpass.getpass(prompt + "): ").strip()
        if not value and session_only:
            value = os.environ[secret.name]
        elif not value and secret.gh_fallback:
            value = _gh_token() or ""
            if value:
                print("  Using `gh auth token`. It goes stale if you `gh auth refresh` or log in again; re-run with --force then.")
        if not value:
            print("  Skipped.")
            continue
        _save(secret.name, value)
        changed = True

    if changed:
        print("\nRestart Claude Code and Codex so they pick the new values up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

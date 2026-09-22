"""`py -3 -m tools.hs_drive_mcp` -- the stdio entry point Claude Code starts.

`tools/` has no `__init__.py`; `tools.hs_drive_mcp` resolves under namespace
package rules when the repo root is the working directory, which is the
arrangement `.mcp.json` relies on.
"""
from .server import main

if __name__ == "__main__":
    main()

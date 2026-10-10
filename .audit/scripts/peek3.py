"""Schema of a saved workflow run record (keys and value types only)."""
import glob, json, os
fs = glob.glob(os.path.expanduser("~/.claude/projects/*hero-siege-offline-toolkit*/*/workflows/wf_*.json"))
print(len(fs))
d = json.load(open(fs[-1], encoding="utf-8"))


def shape(x, depth=0):
    if depth > 3: return type(x).__name__
    if isinstance(x, dict): return {k: shape(v, depth + 1) for k, v in list(x.items())[:25]}
    if isinstance(x, list): return [shape(x[0], depth + 1), f"len={len(x)}"] if x else []
    if isinstance(x, str): return f"str({len(x)})"
    return type(x).__name__
print(json.dumps(shape(d), indent=1)[:3000])

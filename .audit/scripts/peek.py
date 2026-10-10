"""Print the schema of a few transcript files (no content). Local only, no model calls."""
import json, glob, os, sys

ROOT = os.path.expanduser(r"~/.claude/projects/C--Users-stann-Projects-hero-siege-offline-toolkit")
S = os.path.join(ROOT, "d5a2db65-0c8e-4e2b-8c21-483c793fb70f")

for p in glob.glob(os.path.join(ROOT, "a44d5f49-*", "subagents", "*.meta.json"))[:1]:
    print("META", open(p, encoding="utf-8").read()[:600])
print("WF dir:", os.listdir(os.path.join(S, "workflows"))[:5])
wsub = os.path.join(S, "subagents", "workflows")
runs = os.listdir(wsub)
print("WF subagent runs:", runs[:3], len(runs))
r0 = os.path.join(wsub, runs[0])
print("files in run:", os.listdir(r0)[:6], len(os.listdir(r0)))
metas = [f for f in os.listdir(r0) if f.endswith(".meta.json")]
if metas:
    print("WF META", open(os.path.join(r0, metas[0]), encoding="utf-8").read()[:600])

f = glob.glob(os.path.join(ROOT, "a44d5f49-*", "subagents", "*.jsonl"))[0]
types = {}
shown = False
for line in open(f, encoding="utf-8"):
    d = json.loads(line)
    t = d.get("type")
    types[t] = types.get(t, 0) + 1
    if t == "assistant" and not shown:
        shown = True
        m = d["message"]
        print({k: v for k, v in m.items() if k != "content"})
        print(sorted(d.keys()))
print(types)

"""Per workflow-run analysis: duration, agents, achieved concurrency, role breakdown. Local only."""
import collections, csv, os, re, statistics as st
D = os.path.join(os.path.dirname(__file__), "..", "data")
ctx = list(csv.DictReader(open(os.path.join(D, "per_context.csv"), encoding="utf-8")))
wf = [r for r in ctx if r["kind"] == "workflow"]
for r in wf:
    for k in ("start", "end", "dur"): r[k] = float(r[k] or 0)
    for k in ("inp", "cr", "cw", "out", "n_req", "first_ctx"): r[k] = int(r[k])
    r["bill"] = r["inp"] + r["cr"] + r["cw"] + r["out"]


def role(r):
    d = r["desc"]
    a = r["agent"]
    if a != "workflow-subagent":
        return a
    base = re.split(r"[:\s(]", d)[0] or "?"
    return "untyped:" + base

runs = collections.defaultdict(list)
for r in wf:
    runs[(r["session"], r["run"])].append(r)

out = ["# Workflow runs\n", f"runs: {len(runs)}; agents: {len(wf)}\n"]
rows = []
for k, rs in runs.items():
    s = min(r["start"] for r in rs); e = max(r["end"] for r in rs)
    busy = sum(r["dur"] for r in rs)
    rows.append(dict(n=len(rs), wall=e - s, busy=busy, conc=busy / max(1, e - s), bill=sum(r["bill"] for r in rs)))
for f in ("n", "wall", "busy", "conc", "bill"):
    v = sorted(x[f] for x in rows)
    out.append(f"- {f}: median {v[len(v)//2]:.4g}, mean {sum(v)/len(v):.4g}, p90 {v[9*len(v)//10]:.4g}, max {v[-1]:.4g}")
out.append(f"- total run wall h {sum(x['wall'] for x in rows)/3600:.1f}; total agent-busy h {sum(x['busy'] for x in rows)/3600:.1f}")

roles = collections.defaultdict(list)
for r in wf:
    roles[role(r)].append(r)
out += ["\n## Agents by role (workflow)\n", "| role | n | median req | median dur s | total busy h | billed | share of wf billed | first ctx med | models |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
allb = sum(r["bill"] for r in wf)
for k, rs in sorted(roles.items(), key=lambda kv: -sum(r["bill"] for r in kv[1]))[:30]:
    b = sum(r["bill"] for r in rs)
    m = collections.Counter(x for r in rs for x in r["models"].split("|"))
    out.append(f"| {k} | {len(rs)} | {st.median(r['n_req'] for r in rs):.0f} | {st.median(r['dur'] for r in rs):.0f} | {sum(r['dur'] for r in rs)/3600:.1f} | {b/1e6:.0f}M | {100*b/allb:.1f}% | {st.median(r['first_ctx'] for r in rs)/1e3:.0f}k | {', '.join(f'{a}:{c}' for a,c in m.most_common(2))} |")

# description samples for untyped agents
desc = collections.Counter(re.sub(r"\d+", "N", r["desc"]) for r in wf if r["agent"] == "workflow-subagent")
out.append("\n## Untyped (workflow-subagent) description patterns\n")
for k, v in desc.most_common(25):
    out.append(f"- `{k}`: {v}")
# reviewer fan-out per round
pat = collections.Counter(re.sub(r"\d+", "N", r["desc"]) for r in wf if r["agent"] != "workflow-subagent")
out.append("\n## Typed workflow agent description patterns\n")
for k, v in pat.most_common(30):
    out.append(f"- `{k}`: {v}")
open(os.path.join(D, "wfruns.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))

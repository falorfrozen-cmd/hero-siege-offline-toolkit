"""List-price cost by role, using tools/workorder_audit.py's MODEL_PRICES (repo's own table, 2026-10).

Cache writes at 1.25x input (5m) as that tool does; 1h writes at 2x input (ASSUMPTION, labelled).
Unpriced models (deepseek-*) are excluded and counted. Not an invoice: subscription billing.
"""
import collections, csv, os, re, statistics as st
D = os.path.join(os.path.dirname(__file__), "..", "data")
P = {"claude-fable-5-1": (10.0, 50.0, 0.25), "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
     "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20), "claude-haiku-5-5": (0.10, 0.50, 0.01),
     "claude-haiku-4-5-20251001": (1.0, 5.0, 0.10)}
LONG = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05))}
ctx = {r["file"]: r for r in csv.DictReader(open(os.path.join(D, "per_context.csv"), encoding="utf-8"))}
PHASE = {"planner", "implementer", "verifier", "scribe", "live-operator"}
sa = collections.defaultdict(set)
for r in ctx.values(): sa[(r["project"], r["session"])].add(r["agent"])
wo = {k for k, v in sa.items() if v & PHASE}


def role(r):
    if r["kind"] == "main": return "driver (main)"
    a = r["agent"]
    if a == "workflow-subagent": return "untyped:" + re.split(r"[:\s(]", r["desc"])[0]
    return re.sub(r"-(medium|xhigh|max)$", "", a)

cost = collections.Counter(); comp = collections.defaultdict(collections.Counter); unpriced = 0
sess_cost = collections.Counter()
for q in csv.DictReader(open(os.path.join(D, "per_request.csv"), encoding="utf-8")):
    r = ctx[q["file"]]
    if (r["project"], r["session"]) not in wo: continue
    m = q["model"]
    if m not in P: unpriced += 1; continue
    inp, cr, cw, cw1h, out = (int(q[k]) for k in ("inp", "cr", "cw", "cw1h", "out"))
    pi, po, pr = P[m]
    if m in LONG and inp + cr + cw > LONG[m][0]: pi, po, pr = LONG[m][1]
    parts = dict(input=inp * pi, cache_read=cr * pr, cache_write=(cw - cw1h) * pi * 1.25 + cw1h * pi * 2.0, output=out * po)
    ro = role(r)
    for k, v in parts.items(): comp[ro][k] += v / 1e6
    c = sum(parts.values()) / 1e6
    cost[ro] += c; sess_cost[(r["project"], r["session"])] += c
tot = sum(cost.values())
out = [f"# List-price cost (workorder sessions; {len(wo)} sessions; unpriced requests skipped: {unpriced})\n",
       f"Total ${tot:,.0f}; per session median ${st.median(sess_cost.values()):,.0f}, mean ${tot/len(sess_cost):,.0f}, max ${max(sess_cost.values()):,.0f}\n",
       "| role | $ | share | cache-read $ | cache-write $ | output $ | input $ |", "|---|---:|---:|---:|---:|---:|---:|"]
for ro, c in cost.most_common(25):
    x = comp[ro]
    out.append(f"| {ro} | {c:,.0f} | {100*c/tot:.1f}% | {x['cache_read']:,.0f} | {x['cache_write']:,.0f} | {x['output']:,.0f} | {x['input']:,.0f} |")
allc = collections.Counter()
for x in comp.values(): allc.update(x)
out.append(f"\nComponents overall: " + ", ".join(f"{k} ${v:,.0f} ({100*v/tot:.0f}%)" for k, v in allc.most_common()))
open(os.path.join(D, "cost.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))

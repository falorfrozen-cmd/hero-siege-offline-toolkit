"""Attribute cache-write tokens: first request (spawn), after an idle gap beyond TTL (expiry), or growth. Local only."""
import collections, csv, os
D = os.path.join(os.path.dirname(__file__), "..", "data")
ctx = {r["file"]: r for r in csv.DictReader(open(os.path.join(D, "per_context.csv"), encoding="utf-8"))}
PHASE = {"planner", "implementer", "verifier", "scribe", "live-operator"}
sa = collections.defaultdict(set)
for r in ctx.values(): sa[(r["project"], r["session"])].add(r["agent"])
wo = {k for k, v in sa.items() if v & PHASE}
agg = collections.defaultdict(collections.Counter)
prev = {}
gapn = collections.Counter()
for q in csv.DictReader(open(os.path.join(D, "per_request.csv"), encoding="utf-8")):
    r = ctx[q["file"]]
    if (r["project"], r["session"]) not in wo: continue
    kind = r["kind"]
    cw = int(q["cw"]); t = float(q["ts"] or 0)
    ttl = 3600 if int(q["cw1h"]) or kind == "main" else 300
    p = prev.get(q["file"])
    if p is None:
        agg[kind]["spawn/first"] += cw
    elif t - p > ttl and cw > 0.5 * (int(q["cr"]) + cw):
        agg[kind]["after TTL gap"] += cw; gapn[kind] += 1
    else:
        agg[kind]["growth"] += cw
    prev[q["file"]] = t
out = ["# Cache-write attribution (tokens)\n", "| context | spawn/first request | after idle gap > TTL (expiry) | incremental growth | expiry events |", "|---|---:|---:|---:|---:|"]
for k, c in agg.items():
    tot = sum(c.values())
    out.append(f"| {k} | {c['spawn/first']/1e6:.0f}M ({100*c['spawn/first']/tot:.0f}%) | {c['after TTL gap']/1e6:.0f}M ({100*c['after TTL gap']/tot:.0f}%) | {c['growth']/1e6:.0f}M ({100*c['growth']/tot:.0f}%) | {gapn[k]} |")
open(os.path.join(D, "cachew.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))

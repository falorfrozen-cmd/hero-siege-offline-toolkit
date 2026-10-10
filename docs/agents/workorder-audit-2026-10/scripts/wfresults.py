"""Outcomes, round verdicts and reviewer yield from saved workflow run records. Local only, aggregates."""
import collections, glob, json, os, statistics as st
D = os.path.join(os.path.dirname(__file__), "..", "data")
fs = glob.glob(os.path.expanduser("~/.claude/projects/*hero-siege-offline-toolkit*/*/workflows/wf_*.json"))
outc = collections.Counter(); verd = collections.Counter(); keys = collections.Counter()
blk_by = collections.Counter(); nb_by = collections.Counter(); rounds_n = []; dur = []; agents = []
rev_runs = collections.Counter(); rev_blk_rounds = collections.Counter()
for f in fs:
    try: d = json.load(open(f, encoding="utf-8"))
    except Exception: continue
    if "workorder" not in (d.get("workflowName") or "") and "workorder" not in (d.get("scriptPath") or ""): continue
    r = d.get("result") or {}
    outc[r.get("outcome") if isinstance(r, dict) else "none"] += 1
    if d.get("durationMs"): dur.append(d["durationMs"] / 60000)
    if d.get("agentCount"): agents.append(d["agentCount"])
    rs = r.get("rounds") if isinstance(r, dict) else None
    if not isinstance(rs, list): continue
    rounds_n.append(len(rs))
    reviewers = list(((d.get("args") or {}).get("reviewers") or {}).keys())
    for rd in rs:
        verd[str(rd.get("verifier"))] += 1
        srcs = set()
        for b in rd.get("blocking") or []:
            if isinstance(b, dict):
                for k in b: keys[k] += 1
                s = b.get("reviewer") or b.get("source") or b.get("by") or "?"
                blk_by[s] += 1; srcs.add(s)
        for b in rd.get("nonBlocking") or []:
            if isinstance(b, dict): nb_by[b.get("reviewer") or b.get("source") or "?"] += 1
        for rv in reviewers:
            rev_runs[rv] += 1
            if rv in srcs: rev_blk_rounds[rv] += 1
out = [f"# Workflow results ({len(fs)} records)\n", "Outcomes: " + ", ".join(f"{k}:{v}" for k, v in outc.most_common()),
       "Verifier verdict per round: " + ", ".join(f"{k}:{v}" for k, v in verd.most_common()),
       f"Rounds per launch: median {st.median(rounds_n) if rounds_n else '-'}, max {max(rounds_n) if rounds_n else '-'}",
       f"Launch duration min: median {st.median(dur):.0f}, p90 {sorted(dur)[9*len(dur)//10]:.0f}; agents/launch median {st.median(agents)}",
       "Blocking-item keys: " + ", ".join(f"{k}:{v}" for k, v in keys.most_common(12)),
       "\n| reviewer | rounds where configured | rounds with ≥1 BLOCKING from it | yield | blocking items | non-blocking items |", "|---|---:|---:|---:|---:|---:|"]
for rv in sorted(set(rev_runs) | set(blk_by), key=lambda k: -rev_runs[k]):
    out.append(f"| {rv} | {rev_runs[rv]} | {rev_blk_rounds[rv]} | {100*rev_blk_rounds[rv]/max(1,rev_runs[rv]):.0f}% | {blk_by[rv]} | {nb_by[rv]} |")
open(os.path.join(D, "wfresults.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))

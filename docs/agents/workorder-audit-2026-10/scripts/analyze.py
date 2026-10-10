"""Aggregate .audit/data/per_context.csv into the audit's tables. Local only."""
import collections
import csv
import datetime as dt
import os
import statistics as st

D = os.path.join(os.path.dirname(__file__), "..", "data")
ctx = list(csv.DictReader(open(os.path.join(D, "per_context.csv"), encoding="utf-8")))
for r in ctx:
    for k in ("n_req", "inp", "cr", "cw", "cw1h", "out", "first_ctx", "max_ctx", "last_ctx", "tool_calls",
              "agent_calls", "tr_chars", "tr_max", "human_msgs", "compactions", "gaps_over_5m", "first_user_chars"):
        r[k] = int(float(r[k] or 0))
    for k in ("start", "end", "dur", "span", "gap_time_over_5m"):
        r[k] = float(r[k] or 0)

PHASE = {"planner", "planner-medium", "planner-xhigh", "planner-max", "implementer", "implementer-medium",
         "verifier", "consultant", "consultant-max", "scribe", "live-operator"}
REVIEW = {"sdk-contract-reviewer", "tauri-command-reviewer", "decompile-output-guard", "docs-sync-reviewer",
          "instrument-blindness-reviewer"}

by_sess = collections.defaultdict(list)
for r in ctx:
    by_sess[(r["project"], r["session"])].append(r)

wo = {}
for k, rs in by_sess.items():
    agents = {r["agent"] for r in rs}
    if agents & PHASE:
        wo[k] = rs


def tot(rs, f):
    return sum(r[f] for r in rs)


def billed(rs):
    return tot(rs, "inp") + tot(rs, "cr") + tot(rs, "cw") + tot(rs, "out")


def fmt(n):
    return f"{n/1e6:.2f}M" if n >= 1e6 else (f"{n/1e3:.0f}k" if n >= 1e3 else str(n))


def pct(a, b):
    return f"{100*a/b:.0f}%" if b else "-"


out = []
P = out.append
allr = ctx
P(f"# Transcript aggregates\n\nContexts: {len(allr)}; sessions: {len(by_sess)}; workorder sessions (spawned a phase agent): {len(wo)}")
dates = [r["start"] for r in allr if r["start"]]
P(f"Window: {dt.datetime.utcfromtimestamp(min(dates)):%Y-%m-%d} .. {dt.datetime.utcfromtimestamp(max(dates)):%Y-%m-%d}")
P(f"All: requests {tot(allr,'n_req')}, input {fmt(tot(allr,'inp'))}, cache-read {fmt(tot(allr,'cr'))}, cache-write {fmt(tot(allr,'cw'))} (1h {fmt(tot(allr,'cw1h'))}), output {fmt(tot(allr,'out'))}")
wr = [r for rs in wo.values() for r in rs]
P(f"Workorder sessions: requests {tot(wr,'n_req')} ({pct(tot(wr,'n_req'),tot(allr,'n_req'))}), billed tokens {fmt(billed(wr))} ({pct(billed(wr),billed(allr))} of all)")

# By agent type
P("\n## By context type (workorder sessions)\n")
P("| agent | contexts | requests | req/ctx med | input | cache-read | cache-write | cw-1h | output | first-ctx med | max-ctx med | dur med (min) | tool calls med | tool-result chars med | models | efforts |")
P("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
ga = collections.defaultdict(list)
for r in wr:
    ga[r["agent"] if r["kind"] != "workflow" else r["agent"] + " (wf)"].append(r)
for a, rs in sorted(ga.items(), key=lambda kv: -billed(kv[1])):
    med = lambda f: st.median([r[f] for r in rs])
    models = collections.Counter(m for r in rs for m in r["models"].split("|"))
    efforts = collections.Counter(e for r in rs for e in r["efforts"].split("|"))
    P(f"| {a} | {len(rs)} | {tot(rs,'n_req')} | {med('n_req'):.0f} | {fmt(tot(rs,'inp'))} | {fmt(tot(rs,'cr'))} | {fmt(tot(rs,'cw'))} | {fmt(tot(rs,'cw1h'))} | {fmt(tot(rs,'out'))} | {fmt(med('first_ctx'))} | {fmt(med('max_ctx'))} | {med('dur')/60:.1f} | {med('tool_calls'):.0f} | {fmt(med('tr_chars'))} | {', '.join(f'{k}:{v}' for k,v in models.most_common(3))} | {', '.join(f'{k}:{v}' for k,v in efforts.most_common(3))} |")

# Per workorder session
P("\n## Per workorder session\n")
P("| project/session | start | wall h | main reqs | main max ctx | main cr | main cw | spawns | wf agents | phase spawns | reviewer spawns | billed total | out total | compactions | human msgs |")
P("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
rows = []
for (proj, sess), rs in wo.items():
    main = [r for r in rs if r["kind"] == "main"]
    subs = [r for r in rs if r["kind"] != "main"]
    start = min(r["start"] for r in rs if r["start"])
    end = max(r["end"] for r in rs if r["end"])
    rows.append(((proj, sess), start, end, main, subs, rs))
rows.sort(key=lambda x: x[1])
summ = []
for (proj, sess), start, end, main, subs, rs in rows:
    m = main[0] if main else None
    ph = sum(1 for r in subs if r["agent"] in PHASE)
    rv = sum(1 for r in subs if r["agent"] in REVIEW)
    wf = sum(1 for r in subs if r["kind"] == "workflow")
    short = proj.replace("C--Users-stann-Projects-hero-siege-offline-toolkit", "hub").replace("--claude-worktrees-", "wt:")
    summ.append(dict(key=f"{short}/{sess[:8]}", start=start, wall=(end - start) / 3600, billed=billed(rs), out=tot(rs, "out"),
                     spawns=len(subs), ph=ph, rv=rv, wf=wf, main_req=m["n_req"] if m else 0,
                     main_bill=billed(main), sub_bill=billed(subs)))
    P(f"| {short}/{sess[:8]} | {dt.datetime.utcfromtimestamp(start):%m-%d %H:%M} | {(end-start)/3600:.1f} | {m['n_req'] if m else '-'} | {fmt(m['max_ctx']) if m else '-'} | {fmt(m['cr']) if m else '-'} | {fmt(m['cw']) if m else '-'} | {len(subs)} | {wf} | {ph} | {rv} | {fmt(billed(rs))} | {fmt(tot(rs,'out'))} | {tot(rs,'compactions')} | {m['human_msgs'] if m else '-'} |")

P("\n## Distribution across workorder sessions\n")
for f in ("wall", "billed", "out", "spawns", "ph", "rv", "main_req"):
    v = sorted(s[f] for s in summ)
    q = lambda p: v[min(len(v) - 1, int(p * len(v)))]
    P(f"- {f}: n={len(v)} median={v[len(v)//2]:.4g} mean={sum(v)/len(v):.4g} p90={q(0.9):.4g} max={v[-1]:.4g}")
mb = sum(s["main_bill"] for s in summ)
sb = sum(s["sub_bill"] for s in summ)
P(f"- main-context share of billed tokens: {pct(mb, mb+sb)}; subagent+workflow share: {pct(sb, mb+sb)}")

# Spawn tax: first-request context per agent type
P("\n## Spawn tax (first request of each context = fixed spawn context)\n")
P("| agent | n | first-ctx median | first-ctx p10 | first-ctx p90 | sum of first-ctx | first-request cache-read share |")
P("|---|---:|---:|---:|---:|---:|---:|")
import itertools
req = list(csv.DictReader(open(os.path.join(D, "per_request.csv"), encoding="utf-8")))
wo_files = {r["file"] for r in wr}
first = collections.defaultdict(list)
firstcr = collections.defaultdict(lambda: [0, 0])
for q in req:
    if q["i"] == "0" and q["file"] in wo_files and q["kind"] != "main":
        a = q["agent"]
        c = int(q["inp"]) + int(q["cr"]) + int(q["cw"])
        first[a].append(c)
        firstcr[a][0] += int(q["cr"])
        firstcr[a][1] += c
for a, v in sorted(first.items(), key=lambda kv: -sum(kv[1])):
    v.sort()
    P(f"| {a} | {len(v)} | {fmt(st.median(v))} | {fmt(v[len(v)//10])} | {fmt(v[min(len(v)-1, 9*len(v)//10)])} | {fmt(sum(v))} | {pct(*firstcr[a])} |")

# Cache health by context kind
P("\n## Cache health (workorder sessions)\n")
P("| context | cache-read | cache-write | read:write | uncached input | requests with cw>20k after first |")
P("|---|---:|---:|---:|---:|---:|")
big_cw = collections.Counter()
for q in req:
    if q["file"] in wo_files and q["i"] != "0" and int(q["cw"]) > 20000:
        big_cw[q["kind"]] += 1
for k in ("main", "subagent", "workflow"):
    rs = [r for r in wr if r["kind"] == k]
    if rs:
        P(f"| {k} | {fmt(tot(rs,'cr'))} | {fmt(tot(rs,'cw'))} | {tot(rs,'cr')/max(1,tot(rs,'cw')):.1f} | {fmt(tot(rs,'inp'))} | {big_cw[k]} |")

# Main-context gaps > 5 min and wall decomposition
P("\n## Main (driver) context: idle gaps\n")
mains = [r for r in wr if r["kind"] == "main"]
P(f"- driver contexts: {len(mains)}; gaps >5 min between consecutive driver requests: {tot(mains,'gaps_over_5m')} totalling {sum(r['gap_time_over_5m'] for r in mains)/3600:.1f} h; driver compactions: {tot(mains,'compactions')}")

open(os.path.join(os.path.dirname(__file__), "..", "data", "aggregates.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out[:4]))

"""Tool-call durations and wall-clock decomposition for workorder sessions. Local only.

For every tool_use in a context, duration = timestamp(tool_result) - timestamp(assistant entry
carrying the tool_use). For the driver (main) context, every inter-request interval is
attributed to: model (request ts -> last entry of that response), tool wait (by tool name),
or human wait (a typed user message arrived), else 'other'.
"""
import collections
import csv
import glob
import json
import os
import statistics as st
import datetime as dt

HOME = os.path.expanduser("~")
PROJ = os.path.join(HOME, ".claude", "projects")
D = os.path.join(os.path.dirname(__file__), "..", "data")
ctx = list(csv.DictReader(open(os.path.join(D, "per_context.csv"), encoding="utf-8")))
PHASE = {"planner", "planner-medium", "planner-xhigh", "planner-max", "implementer", "implementer-medium",
         "verifier", "consultant", "consultant-max", "scribe", "live-operator"}
sess_agents = collections.defaultdict(set)
for r in ctx:
    sess_agents[(r["project"], r["session"])].add(r["agent"])
wo = {k for k, v in sess_agents.items() if v & PHASE}
files = [(r["file"], r["kind"], r["agent"]) for r in ctx if (r["project"], r["session"]) in wo]


def T(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


dur = collections.defaultdict(list)          # (kind, tool) -> [seconds]
bash_cmd = collections.defaultdict(list)     # first token of Bash command -> secs (subagents)
wait = collections.Counter()                  # driver wall decomposition
wf_names = collections.Counter()
skill_names = collections.Counter()
agent_prompt_chars = collections.defaultdict(list)
agent_result_chars = collections.defaultdict(list)
wf_result_chars = []
for rel, kind, agent in files:
    path = os.path.join(PROJ, rel)
    pending = {}   # tool_use_id -> (ts, name, extra)
    entries = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("timestamp")
        if not t:
            continue
        x = T(t)
        if d.get("type") == "assistant":
            for c in d["message"].get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    extra = ""
                    if c["name"] == "Bash":
                        extra = (inp.get("command") or "").strip().split("\n")[0][:60]
                    if c["name"] in ("Agent", "Task"):
                        agent_prompt_chars[inp.get("subagent_type", "general-purpose")].append(len(inp.get("prompt", "")))
                        extra = inp.get("subagent_type", "general-purpose")
                    if c["name"] == "Workflow":
                        extra = inp.get("name") or (inp.get("scriptPath") or "")[-40:] or "inline"
                        wf_names[extra] += 1
                    if c["name"] == "Skill":
                        skill_names[inp.get("skill")] += 1
                    pending[c["id"]] = (x, c["name"], extra)
            entries.append((x, "a"))
        elif d.get("type") == "user":
            content = d["message"].get("content")
            if isinstance(content, list):
                had = False
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                        t0, name, extra = pending.pop(c["tool_use_id"])
                        dur[(kind, name)].append(x - t0)
                        cc = c.get("content")
                        n = len(cc) if isinstance(cc, str) else sum(len(y.get("text", "")) for y in (cc or []) if isinstance(y, dict))
                        if name in ("Agent", "Task"):
                            agent_result_chars[extra].append(n)
                        if name == "Workflow":
                            wf_result_chars.append(n)
                        if name == "Bash" and kind != "main":
                            bash_cmd[extra.split(" ")[0] if extra else "?"].append(x - t0)
                        entries.append((x, "tool:" + name))
                        had = True
                if not had:
                    entries.append((x, "user"))
            elif isinstance(content, str) and not d.get("isMeta"):
                s = content.lstrip()
                if s.startswith("<task-notification"):
                    entries.append((x, "bg-notification"))
                elif s.startswith("<ci-monitor-event") or s.startswith("<system-reminder"):
                    entries.append((x, "system-event"))
                else:
                    entries.append((x, "human"))
    if kind == "main":
        # attribute each gap to the event that ends it
        entries.sort()
        for (a, _), (b, ev) in zip(entries, entries[1:]):
            g = b - a
            if ev == "a":
                wait["model"] += g
            elif ev.startswith("tool:"):
                wait[ev] += g
            elif ev in ("human", "bg-notification", "system-event"):
                wait[ev] += g
            else:
                wait["other-user"] += g

out = ["# Timing (workorder sessions)\n", "## Driver wall-clock decomposition (sum over 106 driver contexts)\n",
       "| bucket | hours | share |", "|---|---:|---:|"]
total = sum(wait.values())
for k, v in wait.most_common(14):
    out.append(f"| {k} | {v/3600:.1f} | {100*v/total:.1f}% |")
out.append(f"| total | {total/3600:.1f} | |")
out += ["\n## Tool durations\n", "| context | tool | n | median s | p90 s | total h |", "|---|---|---:|---:|---:|---:|"]
for (kind, name), v in sorted(dur.items(), key=lambda kv: -sum(kv[1]))[:30]:
    v.sort()
    out.append(f"| {kind} | {name} | {len(v)} | {st.median(v):.1f} | {v[9*len(v)//10]:.1f} | {sum(v)/3600:.1f} |")
out += ["\n## Subagent Bash time by command head\n", "| cmd | n | median s | total h |", "|---|---:|---:|---:|"]
for k, v in sorted(bash_cmd.items(), key=lambda kv: -sum(kv[1]))[:20]:
    out.append(f"| `{k}` | {len(v)} | {st.median(v):.1f} | {sum(v)/3600:.1f} |")
out += ["\n## Agent tool: delegation prompt and returned result sizes (chars)\n",
        "| subagent_type | n | prompt median | prompt p90 | result median | result p90 |", "|---|---:|---:|---:|---:|---:|"]
for k in sorted(agent_prompt_chars, key=lambda k: -len(agent_prompt_chars[k])):
    p = sorted(agent_prompt_chars[k]); r = sorted(agent_result_chars.get(k, [0]))
    out.append(f"| {k} | {len(p)} | {st.median(p):.0f} | {p[9*len(p)//10]} | {st.median(r):.0f} | {r[9*len(r)//10]} |")
if wf_result_chars:
    w = sorted(wf_result_chars)
    out.append(f"\nWorkflow tool results: n={len(w)} median {st.median(w):.0f} chars, p90 {w[9*len(w)//10]}, max {w[-1]}")
out.append("\nWorkflow invocations by name/script: " + ", ".join(f"{k}:{v}" for k, v in wf_names.most_common(10)))
out.append("\nSkill invocations: " + ", ".join(f"{k}:{v}" for k, v in skill_names.most_common(10)))
open(os.path.join(D, "timing.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))

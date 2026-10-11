"""Which files agents Read, and which criteria/test commands they run, by role. Local only; aggregates."""
import collections, csv, json, os, re
HOME = os.path.expanduser("~"); PROJ = os.path.join(HOME, ".claude", "projects")
D = os.path.join(os.path.dirname(__file__), "..", "data")
ctx = list(csv.DictReader(open(os.path.join(D, "per_context.csv"), encoding="utf-8")))
PHASE = {"planner", "implementer", "verifier", "scribe", "live-operator"}
sess = collections.defaultdict(set)
for r in ctx: sess[(r["project"], r["session"])].add(r["agent"])
wo = {k for k, v in sess.items() if v & PHASE}


def role(r):
    if r["kind"] == "main": return "driver"
    a = r["agent"]
    if a == "workflow-subagent": return "untyped:" + re.split(r"[:\s(]", r["desc"])[0]
    if a.endswith("-reviewer") or a == "decompile-output-guard": return "reviewer"
    return re.sub(r"-(medium|xhigh|max)$", "", a)

cat_reads = collections.defaultdict(collections.Counter)    # role -> category -> count
cat_chars = collections.defaultdict(collections.Counter)
whole_reads = collections.Counter()
cmd = collections.defaultdict(collections.Counter)
per_ctx_plan_reads = collections.defaultdict(list)


def category(p):
    p = p.replace("\\", "/").lower()
    if p.endswith("-plan.md"): return "workorder -plan.md"
    if p.endswith("-context.md"): return "workorder -context.md"
    if "/.claude/agents/" in p or "/.claude/skills/" in p: return ".claude agents/skills"
    if p.endswith("agents.md") or p.endswith("claude.md"): return "AGENTS/CLAUDE.md"
    if "instructions.md" in p: return "submodule instructions.md"
    if "/tool-results/" in p or "/tasks/" in p: return "persisted tool output"
    if "/docs/" in p: return "docs/"
    return "source/other"

for r in ctx:
    if (r["project"], r["session"]) not in wo: continue
    ro = role(r)
    pending = {}
    pr = 0
    for line in open(os.path.join(PROJ, r["file"]), encoding="utf-8", errors="replace"):
        d = json.loads(line)
        if d.get("type") == "assistant":
            for c in d["message"].get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    i = c.get("input") or {}
                    if c["name"] == "Read":
                        cat = category(i.get("file_path", ""))
                        pending[c["id"]] = cat
                        cat_reads[ro][cat] += 1
                        if cat.startswith("workorder"):
                            pr += 1
                            if not i.get("offset") and not i.get("limit"): whole_reads[ro] += 1
                    elif c["name"] in ("Bash", "PowerShell"):
                        s = i.get("command", "")
                        for k, rx in (("run_criteria", r"run_criteria\.py"), ("pytest/unittest", r"pytest|unittest"),
                                      ("npm/node test", r"npm (run )?test|node --test"), ("cmake/msbuild build", r"cmake --build|msbuild"),
                                      ("cargo", r"\bcargo\b"), ("plan_lint", r"plan_lint"), ("section.py", r"section\.py"),
                                      ("round_delta", r"round_delta"), ("git diff", r"git diff"), ("cat/sed/head on plan", r"(cat|sed|head|tail).*-(plan|context)\.md")):
                            if re.search(rx, s): cmd[ro][k] += 1
        elif d.get("type") == "user":
            cont = d["message"].get("content")
            if isinstance(cont, list):
                for c in cont:
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in pending:
                        cc = c.get("content")
                        n = len(cc) if isinstance(cc, str) else sum(len(y.get("text", "")) for y in (cc or []) if isinstance(y, dict))
                        cat_chars[ro][pending.pop(c["tool_use_id"])] += n
    per_ctx_plan_reads[ro].append(pr)

out = ["# Reads and commands by role (workorder sessions)\n", "## Read calls by category: count / chars returned\n"]
cats = sorted({c for v in cat_reads.values() for c in v})
out.append("| role | " + " | ".join(cats) + " | whole-file reads of workorder files |")
out.append("|---|" + "---:|" * (len(cats) + 1))
for ro in sorted(cat_reads, key=lambda k: -sum(cat_chars[k].values())):
    out.append(f"| {ro} | " + " | ".join(f"{cat_reads[ro][c]} / {cat_chars[ro][c]/1e6:.1f}M" for c in cats) + f" | {whole_reads[ro]} |")
out.append("\n## Workorder-file Read calls per context (median / mean)\n")
for ro, v in sorted(per_ctx_plan_reads.items()):
    v = sorted(v)
    if sum(v): out.append(f"- {ro}: n={len(v)} median {v[len(v)//2]} mean {sum(v)/len(v):.1f} max {v[-1]}")
out.append("\n## Commands by role\n")
ks = sorted({k for v in cmd.values() for k in v})
out.append("| role | " + " | ".join(ks) + " |"); out.append("|---|" + "---:|" * len(ks))
for ro in sorted(cmd):
    out.append(f"| {ro} | " + " | ".join(str(cmd[ro][k]) for k in ks) + " |")
open(os.path.join(D, "reads.md"), "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))

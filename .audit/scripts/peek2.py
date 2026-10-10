"""Count attachment/system entry subtypes and user-string prefixes in workorder contexts (no content)."""
import collections, csv, glob, json, os
HOME = os.path.expanduser("~"); PROJ = os.path.join(HOME, ".claude", "projects")
D = os.path.join(os.path.dirname(__file__), "..", "data")
ctx = list(csv.DictReader(open(os.path.join(D, "per_context.csv"), encoding="utf-8")))
att = collections.Counter(); sysc = collections.Counter(); pref = collections.Counter(); hookkeys = collections.Counter()
hook_ms = collections.defaultdict(list)
sample = [r for r in ctx if r["kind"] != "main"][:400] + [r for r in ctx if r["kind"] == "main"][:60]
for r in sample:
    for line in open(os.path.join(PROJ, r["file"]), encoding="utf-8", errors="replace"):
        d = json.loads(line)
        t = d.get("type")
        if t == "attachment":
            a = d.get("attachment") or {}
            at = a.get("type"); att[at] += 1
            if at and "hook" in at:
                for k in a: hookkeys[k] += 1
                for k in ("durationMs", "duration_ms", "duration"):
                    if k in a: hook_ms[(at, a.get("hookName") or a.get("hookEvent"))].append(a[k])
        elif t == "system":
            sysc[d.get("subtype")] += 1
            for k in ("durationMs", "hookDurationMs"):
                if k in d: hook_ms[("system:" + str(d.get("subtype")), d.get("hookEvent") or "")].append(d[k])
        elif t == "user" and r["kind"] == "main":
            c = d["message"].get("content")
            if isinstance(c, str) and not d.get("isMeta"):
                pref[c.strip()[:18]] += 1
print("attachments", att.most_common(25)); print("system", sysc.most_common(15)); print("hook keys", hookkeys.most_common(20))
print("user string prefixes", pref.most_common(15))
for k, v in sorted(hook_ms.items(), key=lambda kv: -len(kv[1]))[:12]:
    v = sorted(float(x) for x in v); print(k, len(v), "median", v[len(v)//2], "sum s", sum(v)/1000)

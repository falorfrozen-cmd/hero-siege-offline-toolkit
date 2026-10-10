"""Aggregate per-request usage from Claude Code transcripts for this project.

Local only: reads ~/.claude/projects/*hero-siege-offline-toolkit*, makes no model
calls, writes aggregates (no message content) to .audit/data/.

Dedup: one API response can be persisted as several entries (one per content
block); we key on message.id (fallback requestId) and keep the entry with the
largest output_tokens.
"""
import collections
import csv
import datetime as dt
import glob
import json
import os
import sys

HOME = os.path.expanduser("~")
PROJ = os.path.join(HOME, ".claude", "projects")
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUT, exist_ok=True)

TTL_5M = 300


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def classify(path):
    """Return (session_id, context_kind, run_id) for a transcript path."""
    parts = path.replace("\\", "/").split("/")
    if "subagents" in parts:
        i = parts.index("subagents")
        session = parts[i - 1]
        if i + 1 < len(parts) and parts[i + 1] == "workflows":
            return session, "workflow", parts[i + 2]
        return session, "subagent", None
    return os.path.splitext(parts[-1])[0], "main", None


def read_meta(path):
    m = path[:-len(".jsonl")] + ".meta.json"
    if os.path.exists(m):
        try:
            return json.load(open(m, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def tool_result_chars(content):
    n = 0
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                cc = c.get("content")
                if isinstance(cc, str):
                    n += len(cc)
                elif isinstance(cc, list):
                    for x in cc:
                        if isinstance(x, dict) and x.get("type") == "text":
                            n += len(x.get("text", ""))
    return n


def scan(path):
    reqs = {}
    order = []
    tool_uses = collections.Counter()
    agent_spawns = []  # (subagent_type, prompt_chars)
    tr_chars = 0
    tr_max = 0
    human_msgs = 0
    compactions = []
    first_user_chars = None
    last_ts = None
    first_ts = None
    events = []  # (ts, kind) kind in {'req','tool_result','human'}
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get("type")
        tstamp = d.get("timestamp")
        if tstamp:
            x = ts(tstamp)
            first_ts = x if first_ts is None else min(first_ts, x)
            last_ts = x if last_ts is None else max(last_ts, x)
        if t == "system" and d.get("subtype") == "compact_boundary":
            compactions.append(d.get("compactMetadata", {}))
        if t == "user":
            msg = d.get("message", {})
            content = msg.get("content")
            c = tool_result_chars(content)
            if first_user_chars is None:
                if isinstance(content, str):
                    first_user_chars = len(content)
                elif isinstance(content, list):
                    first_user_chars = sum(len(x.get("text", "")) for x in content if isinstance(x, dict))
            if c:
                tr_chars += c
                tr_max = max(tr_max, c)
                if tstamp:
                    events.append((ts(tstamp), "tool_result"))
            elif not d.get("isMeta") and not d.get("isSidechain") and isinstance(content, str):
                human_msgs += 1
                if tstamp:
                    events.append((ts(tstamp), "human"))
        if t == "assistant":
            msg = d.get("message", {})
            key = msg.get("id") or d.get("requestId")
            u = msg.get("usage") or {}
            for c in msg.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    name = c.get("name", "?")
                    tool_uses[name] += 1
                    if name in ("Agent", "Task"):
                        inp = c.get("input") or {}
                        agent_spawns.append((inp.get("subagent_type", "general-purpose"), len(json.dumps(inp))))
            rec = reqs.get(key)
            row = dict(
                ts=ts(tstamp) if tstamp else None,
                model=msg.get("model"),
                effort=d.get("effort"),
                inp=u.get("input_tokens", 0) or 0,
                cr=u.get("cache_read_input_tokens", 0) or 0,
                cw=u.get("cache_creation_input_tokens", 0) or 0,
                cw1h=(u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0) or 0,
                out=u.get("output_tokens", 0) or 0,
            )
            if rec is None:
                reqs[key] = row
                order.append(key)
                if row["ts"]:
                    events.append((row["ts"], "req"))
            elif row["out"] > rec["out"]:
                row["ts"] = rec["ts"]
                reqs[key] = row
    rows = [reqs[k] for k in order if reqs[k]["model"] and reqs[k]["model"] != "<synthetic>"]
    return dict(rows=rows, tool_uses=tool_uses, agent_spawns=agent_spawns, tr_chars=tr_chars,
                tr_max=tr_max, human_msgs=human_msgs, compactions=compactions,
                first_user_chars=first_user_chars, first_ts=first_ts, last_ts=last_ts, events=sorted(events))


def main():
    files = [f for f in glob.glob(os.path.join(PROJ, "*hero-siege-offline-toolkit*", "**", "*.jsonl"), recursive=True)]
    per_file = []
    per_req = []
    for f in files:
        session, kind, run = classify(f)
        meta = read_meta(f) if kind != "main" else {}
        s = scan(f)
        rows = s["rows"]
        if not rows:
            continue
        agent = meta.get("agentType") or ("main" if kind == "main" else "unknown")
        tot = lambda k: sum(r[k] for r in rows)
        # gaps between consecutive requests in this context
        gaps = []
        cold_after_gap = 0
        for a, b in zip(rows, rows[1:]):
            if a["ts"] and b["ts"]:
                g = b["ts"] - a["ts"]
                gaps.append(g)
        ctx = [r["inp"] + r["cr"] + r["cw"] for r in rows]
        project = os.path.basename(os.path.dirname(f) if kind == "main" else f.split(os.sep + session + os.sep)[0])
        rec = dict(
            file=os.path.relpath(f, PROJ), project=project, session=session, kind=kind, run=run or "",
            agent=agent, phase=meta.get("workflowPhase", ""), desc=meta.get("description", "")[:80],
            depth=meta.get("spawnDepth", 0 if kind == "main" else ""),
            models="|".join(sorted({r["model"] for r in rows})),
            efforts="|".join(sorted({str(r["effort"]) for r in rows})),
            n_req=len(rows), inp=tot("inp"), cr=tot("cr"), cw=tot("cw"), cw1h=tot("cw1h"), out=tot("out"),
            first_ctx=ctx[0], max_ctx=max(ctx), last_ctx=ctx[-1],
            start=rows[0]["ts"], end=rows[-1]["ts"], dur=(rows[-1]["ts"] - rows[0]["ts"]) if rows[0]["ts"] else 0,
            span=(s["last_ts"] - s["first_ts"]) if s["first_ts"] else 0,
            gaps_over_5m=sum(1 for g in gaps if g > TTL_5M), gap_time_over_5m=sum(g for g in gaps if g > TTL_5M),
            tool_calls=sum(s["tool_uses"].values()), agent_calls=len(s["agent_spawns"]),
            tr_chars=s["tr_chars"], tr_max=s["tr_max"], human_msgs=s["human_msgs"],
            compactions=len(s["compactions"]), first_user_chars=s["first_user_chars"] or 0,
            top_tools=";".join(f"{k}:{v}" for k, v in s["tool_uses"].most_common(8)),
        )
        per_file.append(rec)
        for i, r in enumerate(rows):
            per_req.append(dict(file=rec["file"], session=session, kind=kind, agent=agent, i=i, **r))
    with open(os.path.join(OUT, "per_context.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_file[0].keys()))
        w.writeheader()
        w.writerows(per_file)
    with open(os.path.join(OUT, "per_request.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_req[0].keys()))
        w.writeheader()
        w.writerows(per_req)
    print("files", len(files), "contexts with usage", len(per_file), "requests", len(per_req))


if __name__ == "__main__":
    main()

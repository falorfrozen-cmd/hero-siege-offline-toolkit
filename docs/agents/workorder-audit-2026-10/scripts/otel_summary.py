"""Summarise a week of Claude Code OpenTelemetry events written by the local collector.

Reads the collector's file-exporter output (OTLP JSON lines, rotated backups included) and
prints aggregates only: hook latency by hook event/name, API request time and tokens by
query_source and model, tool durations, compactions, subagent completions. No model calls.

Usage: py -3 otel_summary.py [--dir %USERPROFILE%/otel]
"""
import argparse
import collections
import glob
import json
import os
import statistics as st


def attrs(rec):
    out = {}
    for a in rec.get("attributes", []):
        v = a.get("value", {})
        out[a["key"]] = next(iter(v.values()), None) if v else None
    return out


def events(directory):
    files = sorted(glob.glob(os.path.join(directory, "claude-events*.jsonl")))
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                for rl in d.get("resourceLogs", []):
                    for sl in rl.get("scopeLogs", []):
                        for rec in sl.get("logRecords", []):
                            a = attrs(rec)
                            body = rec.get("body", {}).get("stringValue")
                            yield a.get("event.name") or body or "?", a


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def table(title, groups, unit="ms"):
    print(f"\n## {title}\n")
    print(f"| key | n | median {unit} | p90 {unit} | total s |")
    print("|---|---:|---:|---:|---:|")
    for k, v in sorted(groups.items(), key=lambda kv: -sum(kv[1]))[:25]:
        v.sort()
        print(f"| {k} | {len(v)} | {st.median(v):.0f} | {v[9 * len(v) // 10]:.0f} | {sum(v) / 1000:.0f} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(os.path.expanduser("~"), "otel"))
    args = ap.parse_args()
    counts = collections.Counter()
    hook = collections.defaultdict(list)
    api = collections.defaultdict(list)
    tok = collections.defaultdict(collections.Counter)
    tool = collections.defaultdict(list)
    sub = collections.defaultdict(list)
    comp = []
    sessions = set()
    for name, a in events(args.dir):
        name = name.replace("claude_code.", "")
        counts[name] += 1
        sessions.add(a.get("session.id"))
        d = num(a.get("duration_ms") if a.get("duration_ms") is not None else a.get("total_duration_ms"))
        if name == "hook_execution_complete" and d is not None:
            hook[f"{a.get('hook_event', '?')} {a.get('hook_name', '')}".strip()].append(d)
        elif name == "api_request" and d is not None:
            key = f"{a.get('query_source', '?')} / {a.get('model', '?')}"
            api[key].append(d)
            for t in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"):
                tok[key][t] += int(num(a.get(t)) or 0)
        elif name == "tool_result" and d is not None:
            tool[a.get("tool_name", "?")].append(d)
        elif name == "subagent_completed" and d is not None:
            sub[a.get("agent_type") or a.get("subagent_type") or "?"].append(d)
        elif name == "compaction":
            comp.append((num(a.get("pre_tokens")), num(a.get("post_tokens"))))
    print(f"# Claude Code telemetry summary ({args.dir})\n")
    print(f"sessions: {len(sessions - {None})}; events: " + ", ".join(f"{k}:{v}" for k, v in counts.most_common(15)))
    table("Hook execution time", hook)
    table("API request time by query_source / model", api)
    print("\n## Tokens by query_source / model\n")
    print("| key | input | output | cache read | cache write |")
    print("|---|---:|---:|---:|---:|")
    for k, c in sorted(tok.items(), key=lambda kv: -kv[1]["cache_read_tokens"]):
        print(f"| {k} | {c['input_tokens']} | {c['output_tokens']} | {c['cache_read_tokens']} | {c['cache_creation_tokens']} |")
    table("Tool time", tool)
    table("Subagent run time by type", sub)
    if comp:
        print(f"\ncompactions: {len(comp)}")


if __name__ == "__main__":
    main()

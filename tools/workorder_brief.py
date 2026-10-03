#!/usr/bin/env python3
"""Print one implementer's slice of a `/workorder` plan, in one call.

    py -3 tools/workorder_brief.py <plan> (--round N | --lane NAME | --join | --item ID
                                           | --paths P[,P...] | --criteria K[,K...])
        [--criteria K[,K...]] [--context FILE] [--base REF | --base DIR=REF ...]
        [--since-round K] [--amended]

Why this exists: measured 2026-10-03 (docs/agents/workorder-calibration.md,
"Plan slices, the amendment tier and symbol lookup"), an implementer spent
5-20 `Read`/`sed` calls on its plan and context file before its first edit,
and most of them read a whole file for one lane's steps. The workflow that
spawns implementers cannot read files itself, so it cannot paste a slice into
the prompt; it names this command instead, and the implementer runs it first.
The plan and context paths stay in the prompt as the fallback, and the footer
here names them again.

Every brief prints, in order:

1. a header naming the plan, the selector, and the brief's KB against the
   plan's and context's together;
2. `## Goal`, `## Out of scope` and `## State`;
3. the preconditions: the `## Steps` text above the first `### Lane:`,
   `### Item:` or `### Join` heading (with `--round`, all of `## Steps` is
   the selection, so they are printed once, inside it);
4. the selection:
   * `--round N`: all of `## Steps` and every acceptance criterion, plus the
     Log's `### Round N-1` and `### Round N` entries when N > 0;
   * `--lane NAME`: that `### Lane:` section;
   * `--join`: the `### Join` section, each lane's `files:` and every
     criterion;
   * `--item ID`: that `### Item:` section, its `files:` and `checks:`
     included;
   * `--paths`: every lane and item whose file set covers one of the paths
     (plan_lint's glob rule), or a line saying none does and the `## Steps`
     headings;
   * `--criteria` alone: those criteria; beside another selector, it adds
     them. Criteria are numbered 1-based in plan order, as `run_criteria.py`
     numbers them;
   * `--amended` adds the Log's newest `### Amendment <k>`;
5. each context subsection a printed step or criterion cites as
   `ctx: "<heading>"`, once and whole, matched with section.py's tiers
   (exact, backticks ignored, prefix). One that does not resolve prints
   `ctx not found: "<cite>"`;
6. the Log's `### Decisions`, when it has content. Nothing else from `## Log`
   is printed unless the selection above asked for it;
7. `git diff` pointers, when `--base` or `--since-round` gives bases. They
   are printed, never run;
8. a footer listing each context `###` subsection not printed, with its KB,
   and the full plan and context paths.

The context file is `--context`, else the sibling `<slug>-context.md`, else
the plan itself (a legacy single-file plan, whose context is its own
`## Context the implementer needs`).

Exit codes: 0 printed; 2 usage, or the plan or context cannot be read; 3 the
lane, item, join or criterion the selector names does not exist; 5 a code
fence is never closed, so sections cannot be told apart.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
SKILL = TOOLS.parent / ".claude" / "skills" / "workorder"
sys.path.insert(0, str(TOOLS))
sys.path.insert(1, str(SKILL))
import plan_lint  # noqa: E402
import round_delta  # noqa: E402
import run_criteria  # noqa: E402
import section  # noqa: E402

CONTEXT_HEADING = "Context the implementer needs"
CTX_RE = re.compile(r"\bctx:?\s*[\"“]([^\"”]+)[\"”]")
AMENDMENT_RE = re.compile(r"^Amendment\s+(\d+)\b")
SECTION_PY = ".claude/skills/workorder/section.py"


class Usage(Exception):
    pass


class Missing(Exception):
    pass


class Doc:
    """A markdown file split the way section.py splits it, fences honoured."""

    def __init__(self, path: Path, raw: bytes):
        self.path = path
        # Forward slashes: the brief's paths are pasted into Bash commands.
        self.shown = path.as_posix()
        self.size = len(raw)
        self.lines = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.text = "\n".join(self.lines)
        self.found, self.open_fence = section.headings(self.lines)

    def span(self, k: int) -> tuple:
        start, level, _ = self.found[k]
        end = next((i for i, other, _ in self.found if i > start and other <= level), len(self.lines))
        return start, end

    def body(self, k: int) -> str:
        start, end = self.span(k)
        return "\n".join(self.lines[start:end]).rstrip()

    def kb(self, k: int) -> float:
        start, end = self.span(k)
        return sum(len(line.encode("utf-8")) + 1 for line in self.lines[start:end]) / 1024.0

    def h2(self, name: str):
        return next((k for k, (_, level, text) in enumerate(self.found) if level == 2 and text == name), None)

    def under(self, k: int) -> list:
        """Indexes of the headings inside heading k's section."""
        start, end = self.span(k)
        return [j for j, (i, _, _) in enumerate(self.found) if start < i < end]

    def log_entries(self) -> list:
        return [k for k in range(len(self.found))
                if self.found[k][1] == 3 and section.in_log(self.found, k)]


def _read(path: Path, what: str) -> Doc:
    try:
        return Doc(path, path.read_bytes())
    except (OSError, UnicodeDecodeError) as exc:
        raise Usage(f"cannot read the {what} {path}: {exc}")


def _numbers(raw: str, flag: str) -> list:
    try:
        return [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise Usage(f"{flag} takes comma-separated numbers, not {raw!r}")


def _paths(raw: str) -> list:
    return [p.strip().replace("\\", "/").removeprefix("./") for p in raw.split(",") if p.strip()]


class Brief:
    def __init__(self, args):
        self.args = args
        self.plan = _read(Path(args.plan), "plan")
        if args.context:
            self.ctx = _read(Path(args.context), "context file")
        else:
            sibling = plan_lint.sibling_context(self.plan.path)
            self.ctx = _read(sibling, "context file") if sibling is not None and sibling.is_file() else None
        for doc in (self.plan, self.ctx):
            if doc is not None and doc.open_fence is not None:
                raise Fence(f"{doc.shown}: code fence opened at line {doc.open_fence} is never closed; "
                            "sections cannot be told apart")
        self.log = next((d for d in (self.ctx, self.plan) if d is not None and d.h2(section.LOG_HEADING) is not None),
                        None)
        self.printed_ctx: set = set()

    # -- the plan's parts --------------------------------------------------

    def frame(self) -> list:
        out = []
        for name in ("Goal", "Out of scope", "State"):
            k = self.plan.h2(name)
            if k is not None:
                out.append(self.plan.body(k))
        return out

    def steps_sub(self) -> list:
        k = self.plan.h2("Steps")
        return [] if k is None else [j for j in self.plan.under(k) if self.plan.found[j][1] == 3]

    def preconditions(self) -> str:
        k = self.plan.h2("Steps")
        if k is None:
            return ""
        start, end = self.plan.span(k)
        for j in self.steps_sub():
            line = self.plan.lines[self.plan.found[j][0]]
            if (plan_lint.LANE_HEADING_RE.match(line) or plan_lint.ITEM_HEADING_RE.match(line)
                    or plan_lint.JOIN_HEADING_RE.match(line)):
                end = self.plan.found[j][0]
                break
        return "\n".join(self.plan.lines[start:end]).rstrip()

    def _sub(self, heading_re, name: str):
        for j in self.steps_sub():
            m = heading_re.match(self.plan.lines[self.plan.found[j][0]])
            if m and m.group(1).strip("`* ") == name:
                return j
        return None

    def criteria(self, wanted) -> str:
        """`## Acceptance criteria` numbered as run_criteria numbers them;
        `wanted` None means all of them."""
        items = run_criteria.criteria(self.plan.text) or []
        if wanted is not None:
            bad = [k for k in wanted if not 1 <= k <= len(items)]
            if bad:
                raise Missing(f"no criterion {', '.join(map(str, bad))}: the plan has {len(items)}")
        picked = range(1, len(items) + 1) if wanted is None else wanted
        if not items:
            return ""
        return "## Acceptance criteria\n\n" + "\n".join(f"{k}. {items[k - 1]}" for k in picked)

    # -- selection ---------------------------------------------------------

    def select(self) -> tuple:
        """(blocks, files or None): the selection's text and its file set."""
        a = self.args
        lanes, has_join = plan_lint.lanes(self.plan.text)
        items = plan_lint.items(self.plan.text)
        blocks, files = [], None
        if a.round is not None:
            k = self.plan.h2("Steps")
            if k is not None:
                blocks.append(self.plan.body(k))
            blocks.append(self.criteria(None))
            sets = [x["files"] for x in lanes + items if x["files"]]
            files = [p for s in sets for p in s] or None
        else:
            blocks.append(self.preconditions())
            if a.lane is not None:
                j = self._sub(plan_lint.LANE_HEADING_RE, a.lane)
                if j is None:
                    raise Missing(f"no `### Lane: {a.lane}`; lanes: {', '.join(x['name'] for x in lanes) or 'none'}")
                blocks.append(self.plan.body(j))
                files = next(x["files"] for x in lanes if x["name"] == a.lane)
            elif a.join:
                j = next((j for j in self.steps_sub()
                          if plan_lint.JOIN_HEADING_RE.match(self.plan.lines[self.plan.found[j][0]])), None)
                if j is None or not has_join:
                    raise Missing("the plan has no `### Join` under `## Steps`")
                blocks.append(self.plan.body(j))
                listing = [f"- lane {x['name']}: files: " + (", ".join(f"`{p}`" for p in x["files"])
                                                               if x["files"] else "(no files: line)")
                           for x in lanes]
                if listing:
                    blocks.append("Lanes and their file sets:\n\n" + "\n".join(listing))
                blocks.append(self.criteria(None))
                files = [p for x in lanes for p in (x["files"] or [])] or None
            elif a.item is not None:
                j = self._sub(plan_lint.ITEM_HEADING_RE, a.item)
                if j is None:
                    raise Missing(f"no `### Item: {a.item}`; items: {', '.join(x['id'] for x in items) or 'none'}")
                blocks.append(self.plan.body(j))
                files = next(x["files"] for x in items if x["id"] == a.item)
            elif a.paths is not None:
                wanted = _paths(a.paths)
                covering = []
                for x, regex, key in [(x, plan_lint.LANE_HEADING_RE, "name") for x in lanes] + \
                                     [(x, plan_lint.ITEM_HEADING_RE, "id") for x in items]:
                    if any(plan_lint.reads_path(g, p) for g in x["files"] or [] for p in wanted):
                        covering.append((x, self._sub(regex, x[key])))
                if covering:
                    blocks.extend(self.plan.body(j) for _, j in covering if j is not None)
                    files = [p for x, _ in covering for p in x["files"]]
                else:
                    heads = [self.plan.lines[self.plan.found[j][0]] for j in self.steps_sub()]
                    blocks.append(f"no lane or item covers {', '.join(wanted)}; the steps are:\n\n"
                                  + "\n".join(heads))
                    files = wanted
        if a.criteria is not None:
            blocks.append(self.criteria(_numbers(a.criteria, "--criteria")))
        return [b for b in blocks if b], files

    def log_selection(self) -> list:
        a = self.args
        if self.log is None:
            return []
        entries = self.log.log_entries()
        out = []
        if a.round is not None and a.round > 0:
            for n in (a.round - 1, a.round):
                hit = [k for k in entries if re.match(rf"^Round\s+{n}(?!\d)", self.log.found[k][2])]
                out.extend(self.log.body(k) for k in hit)
                if not hit and n == a.round - 1:
                    out.append(f"(no `### Round {n}` entry in the Log)")
        if a.amended:
            numbered = [(int(m.group(1)), k) for k in entries
                        for m in [AMENDMENT_RE.match(self.log.found[k][2])] if m]
            out.append(self.log.body(max(numbered)[1]) if numbered else "(no `### Amendment` entry in the Log)")
        return out

    # -- context -----------------------------------------------------------

    def ctx_doc(self) -> Doc:
        return self.ctx if self.ctx is not None else self.plan

    def ctx_candidates(self) -> list:
        doc = self.ctx_doc()
        if self.ctx is not None:
            pool = [k for k in range(len(doc.found)) if not section.in_log(doc.found, k)]
        else:
            k = doc.h2(CONTEXT_HEADING)
            pool = [] if k is None else doc.under(k)
        return pool

    def cited(self, text: str) -> list:
        doc, pool = self.ctx_doc(), self.ctx_candidates()
        flat = re.sub(r"\s+", " ", text)
        out, seen = [], set()
        for cite in CTX_RE.findall(flat):
            level, wanted = section.parse_request(cite)
            sub = [k for k in pool if (doc.found[k][1] >= 3 if level is None else doc.found[k][1] == level)]
            hits = section.match([doc.found[k] for k in sub], level, wanted)
            if len(hits) == 1:
                k = sub[hits[0]]
                if k not in seen:
                    seen.add(k)
                    self.printed_ctx.add(k)
                    out.append(doc.body(k))
            elif cite not in seen:
                seen.add(cite)
                why = f" ({len(hits)} headings match)" if hits else ""
                out.append(f'ctx not found: "{cite}"{why}')
        return out

    def decisions(self) -> str:
        if self.log is None:
            return ""
        for k in self.log.log_entries():
            if self.log.found[k][2] == "Decisions":
                body = self.log.body(k)
                if body.partition("\n")[2].strip():
                    return body
        return ""

    # -- diff pointers -----------------------------------------------------

    def bases(self) -> tuple:
        """({repo key: ref}, note or None); "" is the hub."""
        a, bases, note = self.args, {}, None
        if a.since_round is not None:
            name = self.plan.path.name
            slug = name[: -len("-plan.md")] if name.endswith("-plan.md") else self.plan.path.stem
            snap = self.plan.path.parent / ".rounds" / slug / f"round-{a.since_round}.json"
            snapshot, error = round_delta._load_snapshot(snap)
            if error:
                return {}, f"(no diff pointers: {error})"
            bases.update({key.replace("\\", "/").strip("/"): sha for key, sha in snapshot["heads"].items() if sha})
        for raw in a.base or []:
            key, ref = raw.split("=", 1) if "=" in raw else ("", raw)
            key = "" if key in (".", "") else key.replace("\\", "/").strip("/")
            bases[key] = ref
        return bases, note

    def diff_lines(self, files) -> list:
        bases, note = self.bases()
        if note:
            return [note]
        groups: dict = {}
        for p in files or []:
            owner = max((k for k in bases if k and (p == k or p.startswith(k + "/"))), key=len, default="")
            groups.setdefault(owner, []).append(p[len(owner) + 1:] if owner else p)
        out = []
        for key in sorted(bases, key=lambda k: (k != "", k)):
            git = "git" if key == "" else f"git -C {key}"
            if files is None:
                out.append(f"{git} diff {bases[key]} --stat")
            elif groups.get(key):
                out.append(f"{git} diff {bases[key]} -- " + " ".join(f'"{p}"' for p in dict.fromkeys(groups[key])))
        return out

    # -- the whole brief ---------------------------------------------------

    def render(self, selector: str) -> str:
        frame = self.frame()
        selection, files = self.select()
        log_sel = self.log_selection()
        cites = self.cited("\n".join(selection))
        parts = frame + selection
        if log_sel:
            parts.append(f"## Log entries for this brief (from {self.log.shown})")
            parts.extend(log_sel)
        if cites:
            parts.append(f"## Context cited by these steps (from {self.ctx_doc().shown})")
            parts.extend(cites)
        decisions = self.decisions()
        if decisions:
            parts.append(f"## Log › Decisions (from {self.log.shown})")
            parts.append(decisions)
        diffs = self.diff_lines(files)
        if diffs:
            parts.append("## What changed since the base (run these; this tool never runs git)\n\n" + "\n".join(diffs))
        parts.append(self.footer())
        body = "\n\n".join(parts) + "\n"
        total = self.plan.size + (self.ctx.size if self.ctx is not None else 0)
        header = (f"# Brief: {self.plan.shown} {selector} -- {len(body.encode('utf-8')) / 1024.0:.1f} KB "
                  f"of {total / 1024.0:.1f} KB (plan + context)\n\n")
        return header + body

    def footer(self) -> str:
        doc = self.ctx_doc()
        spans = [doc.span(k) for k in self.printed_ctx]
        left = [k for k in self.ctx_candidates() if doc.found[k][1] == 3 and k not in self.printed_ctx
                and not any(s < doc.found[k][0] < e for s, e in spans)]
        lines = ["## Not in this brief", ""]
        if left:
            lines.append("Context subsections not printed:")
            lines.extend(f"- ### {doc.found[k][2]} ({doc.kb(k):.1f} KB)" for k in left)
            lines.append("")
        where = (self.ctx.shown if self.ctx is not None
                 else f"{self.plan.shown} (its `## {CONTEXT_HEADING}`)")
        lines += [f"Full plan: {self.plan.shown}",
                  f"Full context: {where}",
                  f"Read one section with `py -3 {SECTION_PY} <file> '<heading>'`; never read either file whole."]
        return "\n".join(lines)


class Fence(Exception):
    pass


def _selector(a) -> str:
    out = []
    if a.round is not None:
        out.append(f"--round {a.round}")
    if a.lane is not None:
        out.append(f"--lane {a.lane}")
    if a.join:
        out.append("--join")
    if a.item is not None:
        out.append(f"--item {a.item}")
    if a.paths is not None:
        out.append(f"--paths {a.paths}")
    if a.criteria is not None:
        out.append(f"--criteria {a.criteria}")
    if a.amended:
        out.append("--amended")
    return " ".join(out)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workorder_brief.py",
                                description="Print one implementer's slice of a /workorder plan.")
    p.add_argument("plan")
    one = p.add_mutually_exclusive_group()
    one.add_argument("--round", type=int)
    one.add_argument("--lane")
    one.add_argument("--join", action="store_true")
    one.add_argument("--item")
    one.add_argument("--paths")
    p.add_argument("--criteria")
    p.add_argument("--context")
    p.add_argument("--base", action="append")
    p.add_argument("--since-round", type=int, dest="since_round")
    p.add_argument("--amended", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if (args.round is None and args.lane is None and not args.join and args.item is None
                and args.paths is None and args.criteria is None):
            raise Usage("name a selector: --round, --lane, --join, --item, --paths or --criteria")
        if args.round is not None and args.round < 0:
            raise Usage("--round takes a round number, 0 or more")
        if args.criteria is not None:
            _numbers(args.criteria, "--criteria")
        text = Brief(args).render(_selector(args))
    except Usage as exc:
        print(f"workorder_brief: {exc}", file=sys.stderr)
        return 2
    except Missing as exc:
        print(f"workorder_brief: {exc}", file=sys.stderr)
        return 3
    except Fence as exc:
        print(f"workorder_brief: {exc}", file=sys.stderr)
        return 5
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

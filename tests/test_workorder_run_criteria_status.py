"""run_criteria.py's status file, report file and `--status [--wait]` poll.

A whole-tree criteria run goes to the background so the Bash tool's
10-minute ceiling cannot kill it; the verifier then polls `--status` in calls
that each return inside the 240-second blocking-call limit and reads
`report.txt`. These pin what that procedure relies on: the status file says
what ran and how it exited, the report is exactly what stdout was, and the
poll's exit code tells finished (0), running (3), stale (4) and nothing to
read (2) apart -- each with a control. `--digest` (2026-10-03) is the
shortened report the verifier reads instead of `report.txt` whole.
"""

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import run_criteria  # noqa: E402


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        rc = run_criteria.main(argv)
    return rc, out.getvalue()


PLAN = """# x

## State
round: 0
gates: none

## Acceptance criteria

- [ ] `bash -c "echo ok"` prints `ok`
- [ ] `bash -c "exit 3"` exits 3, and `bash -c "echo ok"` still prints `ok`
- [ ] `docs/x.md` records the decision in its own words
- [ ] (gate `live1: complete`) `bash -c "echo live"` exits 0
- [ ] (reads `docs/**`) `bash -c "echo docs"` exits 0
"""


def stamp(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class StatusTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="run_criteria_status_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.tmp = Path(self._tmp)
        self.plan = self.tmp / "x-plan.md"
        self.plan.write_text(PLAN, encoding="utf-8")

    def need_bash(self):
        if not run_criteria.find_bash(None):
            self.skipTest("no bash on this machine")

    def status_of(self, out):
        return json.loads((out / "status.json").read_text(encoding="utf-8"))

    def hand_written(self, name, finished, seconds_ago):
        out = self.tmp / name
        out.mkdir()
        doc = {"plan": "x-plan.md", "item": None, "started_utc": stamp(seconds_ago + 60),
               "updated_utc": stamp(seconds_ago), "finished": finished, "error": None,
               "criteria": [{"k": 1, "state": "done" if finished else "running", "note": None,
                             "commands": [{"n": 1, "cmd": "true", "class": "pure",
                                           "state": "done" if finished else "running", "exit": 0 if finished else None,
                                           "seconds": 1.0 if finished else None, "started_utc": stamp(seconds_ago)}]}]}
        (out / "status.json").write_text(json.dumps(doc), encoding="utf-8")
        return out


class StatusFileTests(StatusTestBase):
    def check_finished_run(self, *extra):
        self.need_bash()
        out = self.tmp / ("logs" + "".join(extra))
        rc, stdout = run([str(self.plan), "--out", str(out), *extra])
        self.assertEqual(rc, 0, stdout)
        doc = self.status_of(out)
        self.assertTrue(doc["finished"])
        self.assertIsNone(doc["error"])
        states = {c["k"]: c["state"] for c in doc["criteria"]}
        self.assertEqual(states, {1: "done", 2: "done", 3: "skipped", 4: "skipped", 5: "done"})
        by_k = {c["k"]: c for c in doc["criteria"]}
        self.assertEqual([(c["n"], c["exit"]) for c in by_k[1]["commands"]], [(1, 0)])
        self.assertEqual([(c["n"], c["exit"]) for c in by_k[2]["commands"]], [(2, 3), (1, 0)],
                         "the shared command is reported under both criteria, as cmd-1")
        self.assertTrue(all(isinstance(c["seconds"], float) for c in by_k[2]["commands"]))
        self.assertIn("no command", by_k[3]["note"])
        self.assertIn("live1: complete", by_k[4]["note"])
        self.assertEqual(by_k[4]["commands"], [], "control: the gated command never ran")
        self.assertEqual(list(out.glob("*.tmp")), [], "a temporary status file was left behind")
        return out, stdout

    def test_a_serial_run_leaves_finished_every_state_and_exit_code(self):
        self.check_finished_run()

    def test_a_jobs_run_leaves_finished_every_state_and_exit_code(self):
        self.check_finished_run("--jobs", "3")

    def test_the_report_equals_stdout(self):
        for extra in ((), ("--jobs", "2")):
            out, stdout = self.check_finished_run(*extra)
            report = (out / "report.txt").read_text(encoding="utf-8")
            self.assertEqual(report, stdout, extra)
            self.assertIn("-> exit 3", report, "control: the report holds the run's output")

    def test_an_unselected_criterion_is_not_selected(self):
        self.need_bash()
        changed = self.tmp / "changed.txt"
        changed.write_text("tools/elsewhere.py\n", encoding="utf-8")
        out = self.tmp / "reach"
        rc, stdout = run([str(self.plan), "--out", str(out), "--changed-from", str(changed)])
        self.assertEqual(rc, 0, stdout)
        states = {c["k"]: c["state"] for c in self.status_of(out)["criteria"]}
        self.assertEqual(states[5], "not-selected")
        self.assertEqual(states[1], "done", "control: a criterion with no (reads ...) still runs")

    def test_criteria_before_start_are_skipped_and_named(self):
        self.need_bash()
        out = self.tmp / "start"
        run([str(self.plan), "--out", str(out), "--start", "2"])
        by_k = {c["k"]: c for c in self.status_of(out)["criteria"]}
        self.assertEqual(by_k[1]["state"], "skipped")
        self.assertIn("--start 2", by_k[1]["note"])
        self.assertEqual(by_k[2]["state"], "done")

    def test_list_writes_nothing(self):
        for extra in ((), ("--jobs", "2")):
            out = self.tmp / ("list" + "".join(extra))
            rc, stdout = run([str(self.plan), "--out", str(out), "--list", *extra])
            self.assertEqual(rc, 0)
            self.assertIn("would run:", stdout, "control: --list listed the commands")
            self.assertFalse(out.exists(), f"--list wrote {sorted(p.name for p in out.iterdir())}"
                             if out.exists() else "")

    def test_a_runner_that_raises_is_finished_with_its_error(self):
        self.need_bash()
        out = self.tmp / "boom"

        def boom(bash, cmd, root, timeout):
            raise OSError("simulated spawn failure")
        with mock.patch.object(run_criteria, "_run_one", boom), self.assertRaises(OSError):
            run([str(self.plan), "--out", str(out)])
        doc = self.status_of(out)
        self.assertTrue(doc["finished"], "a dead runner would otherwise look alive until it went stale")
        self.assertIn("simulated spawn failure", doc["error"])
        rc, text = run(["--status", str(out)])
        self.assertEqual(rc, 0)
        self.assertIn("stopped on an error", text)


class ReusedOutDirTests(StatusTestBase):
    """A verifier reuses one `--out` across its first run, `--start` resumes
    and fix-round reach runs. A new run into it must never let a poll read
    the earlier run's result as its own."""

    def old_finished_run(self, name):
        out = self.hand_written(name, True, 30)
        (out / "report.txt").write_text("the earlier run's report\n", encoding="utf-8")
        # Control: before the new run, the poll reports the old run finished.
        self.assertEqual(run(["--status", str(out)])[0], 0)
        return out

    def test_a_new_run_that_refuses_early_is_not_the_old_finished_run(self):
        refusals = (
            lambda out: [str(self.tmp / "no-such-plan.md"), "--out", str(out)],
            lambda out: [str(self.plan), "--out", str(out), "--jobs", "many"],
            lambda out: [str(self.plan), "--out", str(out), "--start", "soon"],  # argparse's own refusal
            lambda out: [str(self.plan), "--out", str(out), "--item", "nope"],
        )
        for i, argv in enumerate(refusals):
            out = self.old_finished_run(f"reused-{i}")
            self.assertEqual(run(argv(out))[0], 2, "control: the new run did refuse")
            self.assertFalse((out / "report.txt").exists(), "the earlier run's report is still there")
            doc = self.status_of(out)
            self.assertTrue(doc["refused"])
            self.assertEqual(doc["criteria"], [], "the earlier run's criteria are still reported")
            started = time.monotonic()
            rc, text = run(["--status", str(out), "--wait", "30"])
            self.assertEqual(rc, 2, f"the poll read the old run as this one: {text}")
            self.assertLess(time.monotonic() - started, 10, "the poll waited on a run that had already refused")
            self.assertIn("status: refused", text)
            self.assertNotIn("status: finished", text)
            self.assertNotIn("criterion 1", text)
        self.assertIn("no-such-plan.md", self.status_of(self.tmp / "reused-0")["error"],
                      "the refusal names what the run printed to stderr")

    def test_a_poll_during_startup_sees_a_run_not_the_old_one(self):
        out = self.old_finished_run("startup")
        seen = {}

        def slow_build_jobs(*args, **kwargs):
            seen["rc"], seen["text"] = run(["--status", str(out)])
            return real(*args, **kwargs)
        real = run_criteria.build_jobs
        with mock.patch.object(run_criteria, "build_jobs", slow_build_jobs):
            run([str(self.plan), "--out", str(out), "--shell", sys.executable, "--start", "99"])
        self.assertEqual(seen["rc"], 3, seen.get("text"))
        self.assertIn("status: running", seen["text"])

    def test_a_normal_rerun_into_the_same_dir_ends_finished(self):
        self.need_bash()
        out = self.old_finished_run("rerun")
        rc, stdout = run([str(self.plan), "--out", str(out)])
        self.assertEqual(rc, 0, stdout)
        doc = self.status_of(out)
        self.assertTrue(doc["finished"])
        self.assertIsNone(doc["error"])
        self.assertNotIn("refused", doc)
        self.assertEqual(len(doc["criteria"]), 5)
        self.assertEqual((out / "report.txt").read_text(encoding="utf-8"), stdout)
        rc, text = run(["--status", str(out)])
        self.assertEqual(rc, 0, text)
        self.assertIn("status: finished", text)

    def test_a_run_without_out_or_with_list_touches_no_earlier_dir(self):
        out = self.old_finished_run("listed")
        self.assertEqual(run([str(self.plan), "--out", str(out), "--list"])[0], 0)
        self.assertEqual(run(["--status", str(out)])[0], 0, "--list writes nothing, so the old run stands")
        self.assertTrue((out / "report.txt").exists())


class StatusPollTests(StatusTestBase):
    def test_a_finished_run_exits_0(self):
        rc, text = run(["--status", str(self.hand_written("done", True, 5000))])
        self.assertEqual(rc, 0, "a finished run is never stale, however old")
        self.assertIn("criterion 1: done -- cmd-1 exit 0", text)
        self.assertIn("status: finished", text)

    def test_a_recent_unfinished_run_exits_3(self):
        rc, text = run(["--status", str(self.hand_written("live", False, 10))])
        self.assertEqual(rc, 3)
        self.assertIn("status: running", text)
        self.assertIn("criterion 1: running -- cmd-1 running since", text)

    def test_an_unfinished_run_stale_past_1900s_exits_4(self):
        rc, text = run(["--status", str(self.hand_written("stale", False, 2000))])
        self.assertEqual(rc, 4)
        self.assertIn("status: stale", text)
        # Control: 1,800 s is the longest a command can run between two writes.
        self.assertEqual(run(["--status", str(self.hand_written("slow", False, 1800))])[0], 3)

    def test_a_directory_without_the_file_exits_2(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        rc, text = run(["--status", str(empty)])
        self.assertEqual(rc, 2)
        self.assertIn("no status.json", text)
        started = time.monotonic()
        self.assertEqual(run(["--status", str(empty), "--wait", "1"])[0], 2, "--wait waited for it, then gave up")
        self.assertGreaterEqual(time.monotonic() - started, 0.9)

    def test_wait_over_220_and_other_misuse_exit_2(self):
        done = str(self.hand_written("done", True, 5))
        self.assertEqual(run(["--status", done, "--wait", "221"])[0], 2)
        self.assertEqual(run(["--status", done, "--wait", "-1"])[0], 2)
        self.assertEqual(run(["--status", done, "--wait", "soon"])[0], 2)
        self.assertEqual(run(["--wait", "5"])[0], 2, "--wait without --status")
        self.assertEqual(run([str(self.plan), "--status", done])[0], 2, "--status takes no plan")
        self.assertEqual(run([])[0], 2, "neither a plan nor --status")
        self.assertEqual(run(["--status", done, "--wait", "220"])[0], 0, "control: 220 is allowed")

    def test_wait_returns_0_once_a_background_run_finishes(self):
        if not run_criteria.find_bash(None):
            self.skipTest("no bash on this machine")
        plan = self.tmp / "bg-plan.md"
        plan.write_text("## Acceptance criteria\n\n- [ ] `bash -c \"sleep 4; echo slow\"` exits 0\n", encoding="utf-8")
        out = self.tmp / "bg"
        proc = subprocess.Popen([sys.executable, str(TOOLS / "run_criteria.py"), str(plan), "--out", str(out)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.addCleanup(proc.wait, 60)
        self.addCleanup(proc.stdout.close)
        deadline = time.monotonic() + 30
        while not (out / "status.json").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        # Control: the same poll without --wait sees the run still going.
        self.assertEqual(run(["--status", str(out)])[0], 3)
        rc, text = run(["--status", str(out), "--wait", "60"])
        self.assertEqual(rc, 0, text)
        self.assertIn("criterion 1: done -- cmd-1 exit 0", text)
        stdout = proc.communicate(timeout=60)[0].decode("utf-8").replace("\r\n", "\n")
        self.assertEqual((out / "report.txt").read_text(encoding="utf-8"), stdout)


DIGEST_PLAN = """# x

## State
round: 0
gates: none

## Acceptance criteria

- [ ] `bash -c "echo one"` exits 0
- [ ] `bash -c "echo two; exit 3"` exits 0
- [ ] `bash -c "echo ok"` prints `ok`
- [ ] `docs/x.md` records the decision in its own words
- [ ] (gate `live1: complete`) `bash -c "echo live"` exits 0
- [ ] `bash -c "echo two; exit 3"` exits 3 and `bash -c "echo six"` exits 0
- [ ] (reads `docs/**`) (final) `bash -c "echo seven"` exits 0
- [ ] `bash -c "echo eight"` and `bash -c "echo nine"` exits 0
"""


class DigestTests(StatusTestBase):
    """`--digest DIR`: what a verifier reads instead of `report.txt` whole.
    Only a criterion whose prose says nothing but `exits <n>`, and whose
    every command exited so, shrinks to one line; everything else prints
    exactly as the report has it, so the verifier still judges it."""

    def setUp(self):
        super().setUp()
        self.plan.write_text(DIGEST_PLAN, encoding="utf-8")

    def finished(self, *extra):
        self.need_bash()
        out = self.tmp / ("digest" + "".join(extra).replace("-", "").replace("/", ""))
        rc, stdout = run([str(self.plan), "--out", str(out), *extra])
        self.assertEqual(rc, 0, stdout)
        return out, (out / "report.txt").read_text(encoding="utf-8")

    @staticmethod
    def block(report, k):
        """Criterion k's block in the report: its header line through the
        line before the blank line that opens the next one."""
        lines = report.split("\n")
        start = lines.index(next(l for l in lines if l.startswith(f"criterion {k}: ")))
        end = start + 1
        while end < len(lines) and lines[end] != "":
            end += 1
        return "\n".join(lines[start:end])

    def digest_lines(self, text, k):
        return [l for l in text.splitlines() if l.startswith(f"criterion {k}: ")]

    def test_an_exit_only_criterion_as_expected_is_one_line(self):
        for extra in ((), ("--jobs", "3")):
            out, report = self.finished(*extra)
            rc, text = run(["--digest", str(out)])
            self.assertEqual(rc, 0, text)
            self.assertEqual(self.digest_lines(text, 1),
                             [self.digest_lines(text, 1)[0]], "criterion 1 is one line")
            self.assertRegex(text, r"(?m)^criterion 1: exit-only, expects exit 0: cmd-1 exit 0 \(\d+s\)$")
            self.assertNotIn("    one", text, "the as-expected criterion's output is not shown")
            self.assertIn("    one", report, "control: the report does show it")
            # Per-command expectations, joined by `and`; the shared command is
            # judged against this criterion's own expectation.
            self.assertRegex(text, r"(?m)^criterion 6: exit-only, expects exit 3, 0: cmd-2 exit 3 \(\d+s\); "
                                   r"cmd-\d+ exit 0 \(\d+s\)$")
            # Declarations are not prose.
            self.assertRegex(text, r"(?m)^criterion 7: exit-only, expects exit 0: cmd-\d+ exit 0 \(\d+s\)$")
            # One `exits <n>` applies to every command.
            self.assertRegex(text, r"(?m)^criterion 8: exit-only, expects exit 0: cmd-\d+ exit 0 \(\d+s\); "
                                   r"cmd-\d+ exit 0 \(\d+s\)$")

    def test_a_wrong_exit_prints_the_block_exactly_as_the_report_has_it(self):
        out, report = self.finished()
        rc, text = run(["--digest", str(out)])
        self.assertEqual(rc, 0, text)
        block = self.block(report, 2)
        self.assertIn("-> exit 3", block, "control: the block is the failed command's")
        self.assertIn(block, text)
        self.assertNotIn("criterion 2: exit-only", text)

    def test_a_criterion_that_expects_output_prints_whole(self):
        out, report = self.finished()
        text = run(["--digest", str(out)])[1]
        self.assertIn(self.block(report, 3), text)
        self.assertIn("    ok", text, "the verifier needs the output to judge `prints ok`")

    def test_a_criterion_with_no_command_prints_whole(self):
        out, report = self.finished()
        text = run(["--digest", str(out)])[1]
        self.assertIn(self.block(report, 4), text)
        self.assertIn("no command -- check by reading", text)

    def test_a_skipped_criterion_is_its_single_report_line(self):
        out, report = self.finished()
        text = run(["--digest", str(out)])[1]
        lines = self.digest_lines(text, 5)
        self.assertEqual(len(lines), 1, text)
        self.assertIn("SKIPPED (gate live1: complete not set)", lines[0])
        self.assertNotIn("echo live", text, "the skipped criterion's prose is not repeated")
        self.assertIn("echo live", report, "control: the report does name it")

    def test_the_header_counts_and_the_scope_block(self):
        self.need_bash()
        changed = self.tmp / "changed.txt"
        changed.write_text("tools/elsewhere.py\n", encoding="utf-8")
        out = self.tmp / "scoped"
        self.assertEqual(run([str(self.plan), "--out", str(out), "--changed-from", str(changed)])[0], 0)
        report = (out / "report.txt").read_text(encoding="utf-8")
        rc, text = run(["--digest", str(out)])
        self.assertEqual(rc, 0, text)
        first = text.splitlines()[0]
        self.assertRegex(first, r"^digest: 8 criteria, 3 shown in full; report\.txt \d+(\.\d+)? KB")
        scope = [l for l in report.split("\n\ncriterion ")[0].splitlines() if l.startswith(("scope:", "  "))]
        self.assertTrue(scope and scope[0].startswith("scope:"), report)
        self.assertIn("\n".join(scope), text)
        self.assertIn("NOT SELECTED (nothing it reads changed", self.digest_lines(text, 7)[0])
        self.assertEqual(len(self.digest_lines(text, 7)), 1)
        # Control: an unscoped run has no scope block to print.
        plain, _ = self.finished()
        self.assertNotIn("scope:", run(["--digest", str(plain)])[1])

    def test_a_run_that_recorded_no_criterion_text_prints_every_block(self):
        out, report = self.finished()
        doc = self.status_of(out)
        for c in doc["criteria"]:
            c.pop("text", None)
        (out / "status.json").write_text(json.dumps(doc), encoding="utf-8")
        text = run(["--digest", str(out)])[1]
        self.assertNotIn("exit-only", text, "without the text nothing is provably exit-only")
        self.assertIn(self.block(report, 1), text)

    def test_an_unfinished_run_exits_3_and_prints_the_status_lines(self):
        rc, text = run(["--digest", str(self.hand_written("live", False, 10))])
        self.assertEqual(rc, 3)
        self.assertIn("status: running", text)
        self.assertIn("criterion 1: running -- cmd-1 running since", text)
        self.assertEqual(run(["--digest", str(self.hand_written("stale", False, 2000))])[0], 4)

    def test_a_missing_dir_a_refused_run_and_misuse_exit_2(self):
        rc, text = run(["--digest", str(self.tmp / "no-such-run-dir")])
        self.assertEqual(rc, 2)
        self.assertIn("no status.json", text)
        refused = self.tmp / "refused"
        self.assertEqual(run([str(self.tmp / "no-such-plan.md"), "--out", str(refused)])[0], 2)
        self.assertEqual(run(["--digest", str(refused)])[0], 2)
        done = str(self.hand_written("done", True, 5))
        self.assertEqual(run([str(self.plan), "--digest", done])[0], 2, "--digest takes no plan")
        self.assertEqual(run(["--status", done, "--digest", done])[0], 2)
        # Control: --digest given with --out must not wipe the run it reads.
        self.assertEqual(run(["--digest", done, "--out", done])[0], 2)
        self.assertTrue(self.status_of(Path(done))["finished"])


if __name__ == "__main__":
    unittest.main()

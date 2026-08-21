# Readiness Mute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator mark a readiness finding as "true, but it does not apply on this host" — permanently, with a reason, without turning the check off.

**Architecture:** A fifth `Severity`, `MUTED`. `server-readiness.py` owns reading (the mute file *and* the derived case from the cron file) and stays read-only; a new `ownerp_mute.py` owns the write path, following `ownerp_cron.py` step for step. Muting happens in exactly one place — `run_checks()` — so it reaches all four consumers at once.

**Tech Stack:** Python 3 standard library only. `unittest`, run as `python3 -m unittest tests.test_x -v` from the repository root. No new dependencies — deliberately not PyYAML (see spec).

**Spec:** `docs/superpowers/specs/2026-08-21-readiness-mute-design.md`

## Global Constraints

- All code, comments and documentation in **English**. Commit messages in English with an `[ADD]`/`[CHG]`/`[FIX]` prefix.
- **UTF-8** for every file operation; pass `encoding="utf-8"` explicitly.
- Version headers use `X.Y.Z` and `DD.MM.YYYY`. Every file touched here is dated **21.08.2026**.
- `server-readiness.py` **never writes**. No `open(..., "w")`, no `os.replace`, no `chmod`, no `unlink` may appear in it. Its header states this and a test enforces it.
- Mute file: `<ctx.home>/.config/myodoo-docker/readiness-mutes.conf`, mode **0600**, set **before** the rename.
- Never print or log the contents of `.env` or any key ending in `password`.
- Paths inside `server-readiness.py` resolve through `HealthContext` (`ctx.home`, `ctx.p()`), never as absolute constants — otherwise the tests cannot run off a real server.

## Where the parser lives (decided here, not in the spec)

The **reader** lives in `server-readiness.py`, the **writer** in `ownerp_mute.py`.

The tempting arrangement is the opposite — the module that owns the file owns both. It is wrong here: `server-readiness.py` runs on every `ups`, every `chk`, every Monday cron, and on servers where `ownerp_mute.py` has not been delivered yet. If reading went through `ownerp_mute.py`, a missing writer would silently stop every mute from applying, and the operator would get back exactly the messages they switched off — the precise failure the spec's stale-entry `WARN` exists to prevent, reintroduced one level up.

So `ownerp_mute.py` imports `server-readiness.py` (the `_load_module()` pattern) and calls `read_mutes()` for reading. One parser, in the module that cannot be absent.

---

### Task 1: The `MUTED` severity and how it renders

Adds the state and its report behaviour. No source of mutes yet — tests construct a muted finding directly, which is also how later tasks will test their own logic.

**Files:**
- Modify: `scripts/server-readiness.py` (Severity `:126`, `Finding` `:135`, `_palette` `:843`, `print_report` `:870-918`, `main` `:945`)
- Test: `tests/test_readiness_mute.py` (create)

**Interfaces:**
- Produces: `Severity.MUTED`; `Finding.note: Optional[str]`; `mute_finding(finding: Finding, note: str) -> Finding`

- [ ] **Step 1: Write the failing test**

Create `tests/test_readiness_mute.py`:

```python
"""
Tests for muting readiness findings.

A muted check still runs and still says what it found; only its weight
changes. The tests below pin the three things that make that honest: the
line stays visible in the full report, it never reaches --brief or the exit
code, and the count of muted findings can never be suppressed. A mute that
could hide its own existence would be a way to make a server look healthy.

Run from the repository root:

    python3 -m unittest tests.test_readiness_mute -v
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import importlib.util  # noqa: E402

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "scripts", "server-readiness.py")
_spec = importlib.util.spec_from_file_location("server_readiness", _PATH)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)


def render(findings, mode="full"):
    stream = io.StringIO()
    sr.print_report(findings, mode, stream)
    return stream.getvalue()


class MutedSeverityTest(unittest.TestCase):
    def setUp(self):
        self.fail_finding = sr.Finding(
            "backup_recency", sr.Severity.FAIL, "Backup recency",
            "last backup activity 34.9 d ago", "dobk")
        self.ok_finding = sr._ok("logrotate_present", "Logrotate", "installed")

    def test_muting_keeps_the_original_text(self):
        muted = sr.mute_finding(self.fail_finding, "test server, no backups")
        self.assertIs(muted.severity, sr.Severity.MUTED)
        self.assertEqual(muted.detail, "last backup activity 34.9 d ago")
        self.assertEqual(muted.note, "test server, no backups")

    def test_muting_drops_the_fix(self):
        """The fix is advice to act. On a muted finding nobody should act."""
        muted = sr.mute_finding(self.fail_finding, "test server")
        self.assertIsNone(muted.fix)

    def test_the_full_report_shows_the_line_and_the_reason(self):
        muted = sr.mute_finding(self.fail_finding, "test server, no backups")
        text = render([muted, self.ok_finding], "full")
        self.assertIn("[MUTED]", text)
        self.assertIn("Backup recency", text)
        self.assertIn("test server, no backups", text)
        self.assertNotIn("Fix:", text)

    def test_brief_hides_the_line(self):
        muted = sr.mute_finding(self.fail_finding, "test server")
        text = render([muted, self.ok_finding], "brief")
        self.assertNotIn("Backup recency", text)

    def test_brief_never_hides_the_count(self):
        """A report that omits part of itself without saying so is a lie."""
        muted = sr.mute_finding(self.fail_finding, "test server")
        for mode in ("full", "brief"):
            self.assertIn("1 muted", render([muted, self.ok_finding], mode))

    def test_quiet_stays_silent_when_the_only_problem_is_muted(self):
        muted = sr.mute_finding(self.fail_finding, "test server")
        self.assertEqual(render([muted, self.ok_finding], "quiet"), "")

    def test_a_muted_fail_does_not_set_the_exit_code(self):
        muted = sr.mute_finding(self.fail_finding, "test server")
        self.assertFalse(any(f.severity is sr.Severity.FAIL
                             for f in [muted, self.ok_finding]))

    def test_the_label_column_still_lines_up(self):
        """[MUTED] is three characters wider than [OK]; the detail column of
        every row must still start in the same place."""
        muted = sr.mute_finding(self.fail_finding, "test server")
        lines = [l for l in render([muted, self.ok_finding], "full").splitlines()
                 if "Backup recency" in l or "Logrotate" in l]
        self.assertEqual(len(lines), 2)
        columns = [line.index("Backup recency") if "Backup recency" in line
                   else line.index("Logrotate") for line in lines]
        self.assertEqual(columns[0], columns[1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: FAIL — `AttributeError: module 'server_readiness' has no attribute 'mute_finding'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/server-readiness.py`, extend the enum (`:126`):

```python
class Severity(Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"
    # A finding that is true and does not apply on this host. It still runs and
    # still shows its line; it just carries no weight. See
    # docs/superpowers/specs/2026-08-21-readiness-mute-design.md.
    MUTED = "MUTED"
```

Add `note` to `Finding` (`:135`):

```python
@dataclass
class Finding:
    check_id: str
    severity: Severity
    title: str
    detail: str
    fix: Optional[str] = None
    # Rendered under `detail` like `fix`, but without the "Fix:" label: it
    # explains why a finding does not count here, which is not something to act on.
    note: Optional[str] = None
```

Add the helper next to `_ok`/`_skip` (`:273`):

```python
def mute_finding(finding: Finding, note: str) -> Finding:
    """Same finding, no weight. The text is kept verbatim so the report still
    says what was actually measured; only the severity and the advice change.

    `fix` is dropped rather than kept: it is an instruction to act, and on a
    muted finding acting is precisely what nobody should do.
    """
    return Finding(finding.check_id, Severity.MUTED, finding.title,
                   finding.detail, None, note)
```

In `_palette()` (`:843`), give it the dim attribute — it is deliberately the quietest thing on the page:

```python
        Severity.SKIP: "",
        Severity.MUTED: "\033[2m",
```

In `print_report()`, four edits. Widen the label (`:892`) — `[MUTED]` is seven characters:

```python
        label = f"[{finding.severity.value}]".ljust(7)
```

Bump the continuation indent that is derived from it (`:896`), and render `note` right after the detail line:

```python
        indent = " " * (12 + width)
        if finding.note:
            emit(f"{indent}{colors['dim']}{finding.note}{colors['reset']}")
        if finding.fix:
            fix_lines = finding.fix.split("\n")
```

Treat `MUTED` like `OK` when deciding what to show, and never let it trigger `quiet`. Replace the two comprehensions near the top of `print_report()`:

```python
    quiet_levels = (Severity.OK, Severity.MUTED)
    noteworthy = [f for f in findings if f.severity not in quiet_levels]
    actionable = [f for f in findings if f.severity in (Severity.WARN, Severity.FAIL)]
```

Add the count to the summary, in every mode:

```python
    summary = (f"  {counts[Severity.OK]} OK · {counts[Severity.WARN]} WARN · "
               f"{counts[Severity.FAIL]} FAIL · {counts[Severity.SKIP]} skipped")
    if counts[Severity.MUTED]:
        # Never suppressed, not even in --brief: a report that quietly omits
        # part of itself is lying about its own coverage.
        summary += f" · {counts[Severity.MUTED]} muted"
    emit(summary)
```

`main()` needs no change — it already returns 1 only for `Severity.FAIL`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: PASS (8 tests)

Then confirm nothing else broke:

Run: `python3 -m unittest tests.test_ownerp_state tests.test_ownerp_console -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/server-readiness.py tests/test_readiness_mute.py
git commit -m "[ADD] a readiness finding can carry no weight

Severity.MUTED plus Finding.note. A muted finding keeps its measured text
and shows it in the full report; it drops out of --brief, --quiet and the
exit code. The muted count is appended to the summary in every mode -- a
report that omits part of itself without saying so is lying about its own
coverage.

Nothing produces a MUTED finding yet."
```

---

### Task 2: Read the mute file

The parser only. Deliberately tolerant of hand-editing, because the file is documented as hand-editable.

**Files:**
- Modify: `scripts/server-readiness.py` (constants near `:70`, helpers near `:273`)
- Test: `tests/test_readiness_mute.py`

**Interfaces:**
- Consumes: `HealthContext` (`ctx.home`)
- Produces: `MUTES_RELATIVE: str`; `mutes_path(ctx) -> str`; `MuteEntry(check_id: str, since: str, reason: str)`; `read_mutes(ctx) -> List[MuteEntry]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_readiness_mute.py`:

```python
import tempfile  # noqa: E402  — add to the imports at the top of the file


class MuteFixture(unittest.TestCase):
    """A throwaway home, so nothing here depends on a real server."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.ctx = sr.HealthContext(root=self.home, home=self.home,
                                    repo=os.path.join(self.home, "myodoo-docker"))

    def write_mutes(self, text):
        path = sr.mutes_path(self.ctx)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class ReadMutesTest(MuteFixture):
    def test_no_file_is_not_an_error(self):
        self.assertEqual(sr.read_mutes(self.ctx), [])

    def test_a_plain_entry_is_read(self):
        self.write_mutes("certbot_timer_window | 2026-08-21 | own certificates\n")
        entries = sr.read_mutes(self.ctx)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].check_id, "certbot_timer_window")
        self.assertEqual(entries[0].since, "2026-08-21")
        self.assertEqual(entries[0].reason, "own certificates")

    def test_comments_and_blank_lines_are_ignored(self):
        self.write_mutes("# a comment\n\n  \nbackup_recency | 2026-08-21 | test server\n")
        self.assertEqual([e.check_id for e in sr.read_mutes(self.ctx)],
                         ["backup_recency"])

    def test_surrounding_whitespace_is_stripped(self):
        """The file is column-aligned by the writer and by hand."""
        self.write_mutes("backup_recency       | 2026-08-21 | test server  \n")
        entry = sr.read_mutes(self.ctx)[0]
        self.assertEqual(entry.check_id, "backup_recency")
        self.assertEqual(entry.reason, "test server")

    def test_a_reason_may_contain_a_pipe(self):
        """Split on the first two separators only — the reason is free text."""
        self.write_mutes("backup_recency | 2026-08-21 | test | staging box\n")
        self.assertEqual(sr.read_mutes(self.ctx)[0].reason, "test | staging box")

    def test_a_malformed_line_is_skipped_not_fatal(self):
        """One bad hand-edit must not cost the operator every other mute."""
        self.write_mutes("nonsense\nbackup_recency | 2026-08-21 | test server\n")
        self.assertEqual([e.check_id for e in sr.read_mutes(self.ctx)],
                         ["backup_recency"])

    def test_an_unreadable_file_yields_nothing_rather_than_raising(self):
        path = self.write_mutes("backup_recency | 2026-08-21 | test\n")
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o600)
        if os.geteuid() == 0:
            self.skipTest("root reads regardless of mode")
        self.assertEqual(sr.read_mutes(self.ctx), [])

    def test_the_path_is_built_from_the_context_not_from_root(self):
        self.assertTrue(sr.mutes_path(self.ctx).startswith(self.home))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: FAIL — `AttributeError: module 'server_readiness' has no attribute 'mutes_path'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/server-readiness.py`, add next to the other path constants (near `:70`):

```python
# Checks muted on this host. Written by ownerp_mute.py, read here. Relative to
# ctx.home rather than absolute so the checks stay testable off a real server.
MUTES_RELATIVE = ".config/myodoo-docker/readiness-mutes.conf"
MUTE_SEPARATOR = "|"

# Findings that may never be muted. mute_registry reports a mute file that has
# gone stale; muting it would switch off the guard against silent mutes.
UNMUTABLE = ("mute_registry",)
```

Add the dataclass beside `Finding`:

```python
@dataclass
class MuteEntry:
    check_id: str
    since: str
    reason: str
```

Add the reader beside `_ok`/`_skip`:

```python
def mutes_path(ctx: HealthContext) -> str:
    return os.path.join(ctx.home, MUTES_RELATIVE)


def read_mutes(ctx: HealthContext) -> List[MuteEntry]:
    """Parse the mute file. Missing, unreadable or partly malformed all yield
    what could be read rather than an exception.

    A single bad hand-edit must not cost the operator every other mute — and it
    must not cost them the report either, which is what raising from here would
    do. Lines that do not parse are simply not mutes; the entries that do parse
    still apply.
    """
    text = _read(mutes_path(ctx))
    if text is None:
        return []
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # maxsplit=2: the reason is free text and may itself contain a pipe.
        parts = line.split(MUTE_SEPARATOR, 2)
        if len(parts) != 3:
            continue
        check_id, since, reason = (part.strip() for part in parts)
        if not check_id or not reason:
            continue
        entries.append(MuteEntry(check_id, since, reason))
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/server-readiness.py tests/test_readiness_mute.py
git commit -m "[ADD] read the list of checks muted on this host

A three-field line format rather than YAML, because server-readiness.py
runs today without PyYAML: a YAML mute file would silently stop applying
on such a host and hand the operator back exactly the messages they had
switched off.

Missing, unreadable or partly malformed all yield what could be read. One
bad hand-edit must cost neither the other mutes nor the report.

Nothing applies these entries yet."
```

---

### Task 3: Apply the mutes, and notice a stale one

**Files:**
- Modify: `scripts/server-readiness.py` (`run_checks` `:823`)
- Test: `tests/test_readiness_mute.py`

**Interfaces:**
- Consumes: `read_mutes()`, `mute_finding()`, `UNMUTABLE`
- Produces: `run_checks(ctx)` now returns findings with mutes applied, plus a `mute_registry` finding when the file names a check that does not exist

- [ ] **Step 1: Write the failing test**

Append to `tests/test_readiness_mute.py`:

```python
class ApplyMutesTest(MuteFixture):
    """run_checks() against a throwaway tree: almost everything FAILs or SKIPs
    there, which is fine — these tests only ask what muting did to the result."""

    def find(self, findings, check_id):
        for finding in findings:
            if finding.check_id == check_id:
                return finding
        self.fail(f"no finding with check_id {check_id!r}")

    def test_a_muted_check_comes_back_muted(self):
        self.write_mutes("maintenance_cron_present | 2026-08-21 | not scheduled here\n")
        finding = self.find(sr.run_checks(self.ctx), "maintenance_cron_present")
        self.assertIs(finding.severity, sr.Severity.MUTED)
        self.assertIn("not scheduled here", finding.note)
        self.assertIn("2026-08-21", finding.note)

    def test_an_unmuted_check_is_untouched(self):
        self.write_mutes("maintenance_cron_present | 2026-08-21 | not scheduled here\n")
        finding = self.find(sr.run_checks(self.ctx), "logrotate_present")
        self.assertIsNot(finding.severity, sr.Severity.MUTED)

    def test_without_a_mute_file_nothing_is_muted(self):
        findings = sr.run_checks(self.ctx)
        self.assertFalse(any(f.severity is sr.Severity.MUTED for f in findings))

    def test_no_registry_finding_when_every_entry_resolves(self):
        self.write_mutes("logrotate_present | 2026-08-21 | not used here\n")
        ids = [f.check_id for f in sr.run_checks(self.ctx)]
        self.assertNotIn("mute_registry", ids)

    def test_a_stale_entry_is_reported(self):
        """The silent failure this prevents: the message comes back one day and
        the file still looks like it should be stopping it."""
        self.write_mutes("backup_freshness | 2026-08-21 | renamed long ago\n")
        finding = self.find(sr.run_checks(self.ctx), "mute_registry")
        self.assertIs(finding.severity, sr.Severity.WARN)
        self.assertIn("backup_freshness", finding.detail)
        self.assertIn("ownerp_mute.py --unmute", finding.fix)

    def test_the_registry_guard_cannot_mute_itself(self):
        self.write_mutes("backup_freshness | 2026-08-21 | renamed\n"
                         "mute_registry | 2026-08-21 | stop nagging\n")
        finding = self.find(sr.run_checks(self.ctx), "mute_registry")
        self.assertIs(finding.severity, sr.Severity.WARN)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_readiness_mute.ApplyMutesTest -v`
Expected: FAIL — the finding comes back `FAIL`, not `MUTED`

- [ ] **Step 3: Write minimal implementation**

Replace `run_checks()` (`scripts/server-readiness.py:823`):

```python
def run_checks(ctx: HealthContext) -> List[Finding]:
    """Run every check, then apply this host's mutes.

    A check that raises becomes a SKIP finding carrying the error — one broken
    check must never cost the administrator the whole report.

    Muting happens here and nowhere else. Every consumer — chk, dostat, konsole,
    the block after `ups`, the Monday cron — comes through this function, so one
    filter reaches all of them and none of them can disagree about what is muted.
    """
    findings = []
    for check in CHECKS:
        try:
            findings.append(check(ctx))
        except Exception as exc:
            findings.append(Finding(
                check.__name__, Severity.SKIP, check.__name__,
                f"check failed to run: {type(exc).__name__}: {exc}",
            ))

    mutes = {entry.check_id: entry for entry in read_mutes(ctx)
             if entry.check_id not in UNMUTABLE}
    produced = {finding.check_id for finding in findings}

    applied = []
    for finding in findings:
        entry = mutes.get(finding.check_id)
        if entry is None or finding.severity is Severity.OK:
            applied.append(finding)
            continue
        applied.append(mute_finding(finding, f"off since {entry.since} — {entry.reason}"))

    stale = sorted(check_id for check_id in mutes if check_id not in produced)
    if stale:
        applied.append(Finding(
            "mute_registry", Severity.WARN, "Mute registry",
            f"{len(stale)} entr{'y' if len(stale) == 1 else 'ies'} name a check "
            f"that does not exist: {', '.join(stale)}",
            f"ownerp_mute.py --unmute {stale[0]}",
        ))
    return applied
```

Note the `Severity.OK` guard: muting an already-passing check would turn a green line into a `MUTED` one and inflate the muted count for no reason. The mute stays in the file and takes effect again the day the check starts failing.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: PASS (22 tests)

Run: `python3 -m unittest tests.test_ownerp_state -v`
Expected: PASS — `worst()` collects `finding.severity.value` and asks only for `"FAIL"`/`"WARN"` (`ownerp_state.py:748`), so `"MUTED"` is already ignored; this run confirms it rather than assuming it.

- [ ] **Step 5: Commit**

```bash
git add scripts/server-readiness.py tests/test_readiness_mute.py
git commit -m "[CHG] run_checks applies this host's mutes

One filter, in the one function every consumer comes through -- chk,
dostat, konsole, the block after ups and the Monday cron cannot disagree
about what is muted.

An entry naming a check that no longer exists gets its own WARN. Without
it the failure is silent in the worst way: the message returns one day and
the file still looks like it should be preventing it. That guard is on
UNMUTABLE, so it cannot be switched off with the thing it guards."
```

---

### Task 4: Derive the backup mute from a disabled cron job

**Files:**
- Modify: `scripts/server-readiness.py` (constants near `:100`, `check_backup_recency` `:467`)
- Test: `tests/test_readiness_mute.py`

**Interfaces:**
- Consumes: `_disabled_cron_lines()` (`:234`), `_normalise_cron_line()` (`:244`), `CRON_DEST` (`:71`)
- Produces: `DERIVED_MUTES: dict` mapping a cron job name to the `check_id` its absence explains

- [ ] **Step 1: Write the failing test**

Append to `tests/test_readiness_mute.py`:

```python
class DerivedMuteTest(MuteFixture):
    """A backup check on a host where the backup job is switched off on purpose.

    ownerp_cron.py parks a disabled job behind a marker instead of deleting it,
    so the cron file already records the decision. Reading it beats asking the
    operator to state the same fact a second time in a second file.
    """

    def install_cron(self, body):
        path = self.ctx.p(sr.CRON_DEST)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)

    def backup_finding(self):
        for finding in sr.run_checks(self.ctx):
            if finding.check_id == "backup_recency":
                return finding
        self.fail("no backup_recency finding")

    def test_a_disabled_backup_job_mutes_the_backup_check(self):
        self.install_cron(
            "#OWNERP-DISABLED# 0 2 * * * root /root/container2backup.py\n"
            "0 0 * * * root /root/ssl-renew.sh\n")
        finding = self.backup_finding()
        self.assertIs(finding.severity, sr.Severity.MUTED)
        self.assertIn("cron job disabled", finding.note)

    def test_an_active_backup_job_does_not_mute_it(self):
        self.install_cron("0 2 * * * root /root/container2backup.py\n")
        self.assertIsNot(self.backup_finding().severity, sr.Severity.MUTED)

    def test_another_disabled_job_does_not_mute_the_backup_check(self):
        """No blanket muting: only the pair whose absence explains the finding."""
        self.install_cron(
            "#OWNERP-DISABLED# 0 0 * * * root /root/ssl-renew.sh\n"
            "0 2 * * * root /root/container2backup.py\n")
        self.assertIsNot(self.backup_finding().severity, sr.Severity.MUTED)

    def test_no_cron_file_at_all_does_not_mute_it(self):
        self.assertIsNot(self.backup_finding().severity, sr.Severity.MUTED)

    def test_an_explicit_mute_wins_over_the_derived_one(self):
        """Both true at once: the operator's own words are the better message."""
        self.install_cron(
            "#OWNERP-DISABLED# 0 2 * * * root /root/container2backup.py\n")
        self.write_mutes("backup_recency | 2026-08-21 | staging, never backed up\n")
        finding = self.backup_finding()
        self.assertIs(finding.severity, sr.Severity.MUTED)
        self.assertIn("staging, never backed up", finding.note)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_readiness_mute.DerivedMuteTest -v`
Expected: FAIL — the finding is `WARN`/`FAIL`, not `MUTED`

- [ ] **Step 3: Write minimal implementation**

Add beside `MANAGED_JOBS` in `scripts/server-readiness.py`:

```python
# A check whose finding is fully explained by an ownERP job being switched off
# on purpose. The cron file already records that decision (ownerp_cron.py parks
# a disabled job behind a marker rather than deleting it), so it is read rather
# than asking the operator to state the same fact again in the mute file.
#
# Data, not an `if`: a second pair is a line here.
DERIVED_MUTES = {
    "container2backup": "backup_recency",
}
```

Add the helper beside `read_mutes()`:

```python
def _disabled_jobs(ctx: HealthContext) -> List[str]:
    """Basenames of the maintenance jobs switched off through ownerp_cron.py."""
    text = _read(ctx.p(CRON_DEST))
    if text is None:
        return []
    names = []
    for line in _disabled_cron_lines(text):
        normalised = _normalise_cron_line(line)
        for job in DERIVED_MUTES:
            if job in normalised:
                names.append(job)
    return names


def derived_mutes(ctx: HealthContext) -> dict:
    """check_id -> reason, for checks explained by a deliberately disabled job."""
    return {DERIVED_MUTES[job]: "cron job disabled on this host"
            for job in _disabled_jobs(ctx)}
```

In `run_checks()`, apply the derived mutes underneath the explicit ones — the operator's own sentence is the better message when both apply. Replace the mute-application block from Task 3:

```python
    mutes = {entry.check_id: f"off since {entry.since} — {entry.reason}"
             for entry in read_mutes(ctx) if entry.check_id not in UNMUTABLE}
    produced = {finding.check_id for finding in findings}
    stale = sorted(check_id for check_id in mutes if check_id not in produced)

    # Explicit last: an operator's own words beat a derived sentence.
    reasons = derived_mutes(ctx)
    reasons.update(mutes)

    applied = []
    for finding in findings:
        reason = reasons.get(finding.check_id)
        if reason is None or finding.severity is Severity.OK:
            applied.append(finding)
            continue
        applied.append(mute_finding(finding, reason))
```

The `stale` block below it is unchanged: it is computed from `mutes` (the file) only, so a derived mute never produces a registry warning.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: PASS (27 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/server-readiness.py tests/test_readiness_mute.py
git commit -m "[ADD] a backup job switched off on purpose mutes its own check

ownerp_cron.py parks a disabled job behind a marker instead of deleting
it, so the cron file already records the decision. Reading it beats asking
the operator to write the same fact into a second file, and re-enabling
the job brings the check back with nothing left to clean up.

Only for the one pair whose absence explains the finding, expressed as
data so a second pair is a line. An explicit mute still wins: the
operator's own words are the better message."
```

---

### Task 5: `ownerp_mute.py` — the write path

**Files:**
- Create: `scripts/ownerp_mute.py`
- Test: `tests/test_ownerp_mute.py` (create)

**Interfaces:**
- Consumes: `server-readiness.py` `read_mutes()`, `mutes_path()`, `MuteEntry`, `UNMUTABLE`
- Produces: `MuteError`; `load(home) -> List[MuteEntry]`; `render(entries) -> str`; `write(home, entries) -> str` (returns the backup path, or `""` when there was no file to back up); `mute(home, check_id, reason, valid_ids=None) -> str`; `unmute(home, check_id) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ownerp_mute.py`:

```python
"""
Tests for ownerp_mute.py — the write path for muted readiness checks.

The value of this module is entirely in that write path. Everything it can
get wrong is silent: a half-written file, a mode that leaves credentials-
adjacent config world-readable, an entry without a reason that nobody can
justify a year later. These tests pin the promises that make writing safe.

Run from the repository root:

    python3 -m unittest tests.test_ownerp_mute -v
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import ownerp_mute as om  # noqa: E402


class MuteWriteFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def path(self):
        return om.mutes_path(self.home)

    def text(self):
        with open(self.path(), "r", encoding="utf-8") as handle:
            return handle.read()


class WriteTest(MuteWriteFixture):
    def test_the_first_mute_creates_the_file_and_its_directory(self):
        om.mute(self.home, "certbot_timer_window", "own certificates")
        self.assertTrue(os.path.isfile(self.path()))
        self.assertIn("certbot_timer_window", self.text())
        self.assertIn("own certificates", self.text())

    def test_the_file_is_not_world_readable(self):
        om.mute(self.home, "certbot_timer_window", "own certificates")
        self.assertEqual(os.stat(self.path()).st_mode & 0o777, 0o600)

    def test_the_written_file_reads_back_as_what_went_in(self):
        om.mute(self.home, "backup_recency", "test server | staging")
        entries = om.load(self.home)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].check_id, "backup_recency")
        self.assertEqual(entries[0].reason, "test server | staging")

    def test_a_second_mute_keeps_the_first(self):
        om.mute(self.home, "backup_recency", "test server")
        om.mute(self.home, "certbot_timer_window", "own certificates")
        self.assertEqual(sorted(e.check_id for e in om.load(self.home)),
                         ["backup_recency", "certbot_timer_window"])

    def test_muting_the_same_check_twice_replaces_rather_than_duplicates(self):
        om.mute(self.home, "backup_recency", "first reason")
        om.mute(self.home, "backup_recency", "better reason")
        entries = om.load(self.home)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].reason, "better reason")

    def test_a_backup_is_taken_before_overwriting(self):
        om.mute(self.home, "backup_recency", "first reason")
        om.mute(self.home, "certbot_timer_window", "own certificates")
        backups = [n for n in os.listdir(os.path.dirname(self.path()))
                   if ".bak_" in n]
        self.assertEqual(len(backups), 1)

    def test_no_temp_file_is_left_behind(self):
        om.mute(self.home, "backup_recency", "test server")
        leftovers = [n for n in os.listdir(os.path.dirname(self.path()))
                     if ".tmp_" in n]
        self.assertEqual(leftovers, [])

    def test_unmute_removes_only_the_named_entry(self):
        om.mute(self.home, "backup_recency", "test server")
        om.mute(self.home, "certbot_timer_window", "own certificates")
        om.unmute(self.home, "backup_recency")
        self.assertEqual([e.check_id for e in om.load(self.home)],
                         ["certbot_timer_window"])

    def test_unmuting_something_that_is_not_muted_is_an_error(self):
        with self.assertRaises(om.MuteError):
            om.unmute(self.home, "backup_recency")


class RefusalTest(MuteWriteFixture):
    def test_a_mute_without_a_reason_is_refused(self):
        """An entry nobody can justify a year later gets deleted rather than
        understood, which brings the message back on a host that decided
        against it."""
        for reason in ("", "   "):
            with self.assertRaises(om.MuteError):
                om.mute(self.home, "backup_recency", reason)
        self.assertFalse(os.path.exists(self.path()))

    def test_an_unknown_check_id_is_refused_when_the_ids_are_known(self):
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "backup_freshness", "typo",
                    valid_ids=["backup_recency", "certbot_timer_window"])
        self.assertFalse(os.path.exists(self.path()))

    def test_the_error_names_the_valid_ids(self):
        with self.assertRaises(om.MuteError) as caught:
            om.mute(self.home, "backup_freshness", "typo",
                    valid_ids=["backup_recency"])
        self.assertIn("backup_recency", str(caught.exception))

    def test_an_unmutable_id_is_refused(self):
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "mute_registry", "stop nagging",
                    valid_ids=["mute_registry"])

    def test_a_separator_in_the_check_id_is_refused(self):
        """It would produce a line that parses back as something else."""
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "backup | recency", "test")

    def test_a_newline_in_the_reason_is_refused(self):
        with self.assertRaises(om.MuteError):
            om.mute(self.home, "backup_recency", "line one\nline two")


class AtomicityTest(MuteWriteFixture):
    def test_a_failed_validation_leaves_the_original_byte_identical(self):
        om.mute(self.home, "backup_recency", "test server")
        before = self.text()

        original_verify = om._verify

        def refuse(*args, **kwargs):
            raise om.MuteError("simulated validation failure")

        om._verify = refuse
        self.addCleanup(setattr, om, "_verify", original_verify)

        with self.assertRaises(om.MuteError):
            om.mute(self.home, "certbot_timer_window", "own certificates")

        self.assertEqual(self.text(), before)
        leftovers = [n for n in os.listdir(os.path.dirname(self.path()))
                     if ".tmp_" in n]
        self.assertEqual(leftovers, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_ownerp_mute -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ownerp_mute'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/ownerp_mute.py`:

```python
#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_mute.py
# Description:      Mark a readiness finding as true but not applicable on this
#                   host, permanently and with a reason.
# Version:          1.0.0
# Date:             21.08.2026
# Author:           Equitania Software GmbH
# ==============================================================================
# Why this exists:
#   Some readiness findings are correct and still describe nothing wrong. A host
#   whose certificates come from an internal CA gets a permanent certbot-timer
#   WARN; a test server with no backups by design gets a permanent Backup-recency
#   FAIL that mails every Monday.
#
#   The cost is not the noise. An operator who learns that two lines are always
#   there stops reading the block, and the third line - the one that matters -
#   goes with them.
#
# What it does:
#   Owns the write path for /root/.config/myodoo-docker/readiness-mutes.conf.
#   Reading lives in server-readiness.py, which runs on hosts where this script
#   has not been delivered yet; a reader that could be absent would silently
#   stop every mute from applying.
#
#   ownerp_mute.py --list
#   ownerp_mute.py <check_id> --reason "<text>"
#   ownerp_mute.py --unmute <check_id>
#
# Design: docs/superpowers/specs/2026-08-21-readiness-mute-design.md
# ==============================================================================
#    Copyright (C) 2014-now Equitania Software GmbH(<http://www.equitania.de>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
###############################################################################

import argparse
import importlib.util
import os
import shutil
import sys
import time
from typing import List, Optional

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "21.08.2026"

HERE = os.path.dirname(os.path.abspath(__file__))

HEADER = """\
# Readiness checks muted on this host.
#
# A muted check still runs and still shows its line in the full report; it
# carries no weight in `chk --brief`, in the Monday cron mail or in the exit
# code. Managed by ownerp_mute.py - hand edits are read back fine.
#
# Format:  <check_id> | <YYYY-MM-DD> | <reason>
"""


class MuteError(Exception):
    """Anything that must stop a write, with a sentence for the operator."""


def _readiness():
    """server-readiness.py, imported by path. It owns the reader.

    By path because the name carries a hyphen and it is not on the import path:
    on a server it sits beside this file in $HOME, in the repository in scripts/.
    """
    path = os.path.join(HERE, "server-readiness.py")
    try:
        spec = importlib.util.spec_from_file_location("server_readiness", path)
        if spec is None or spec.loader is None:
            raise MuteError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except MuteError:
        raise
    except Exception as exc:
        raise MuteError(f"server-readiness.py is not usable ({exc}) — run ups")


def _context(home: str):
    sr = _readiness()
    return sr, sr.HealthContext(home=home, repo=os.path.join(home, "myodoo-docker"))


def mutes_path(home: str) -> str:
    sr, ctx = _context(home)
    return sr.mutes_path(ctx)


def load(home: str) -> List:
    """The entries currently in the file. Reading goes through the reader."""
    sr, ctx = _context(home)
    return sr.read_mutes(ctx)


def check_ids(home: str) -> List[str]:
    """Every check_id the report can actually produce.

    A check_id does not exist until its check has run: CHECKS is a tuple of
    functions and the id lives in the Finding each returns. So the checks are
    run - read-only, a second or two - rather than kept in a second list that
    can drift away from the findings the report really emits. A mute pointing
    at an id nothing emits is exactly the silent failure this guards against.
    """
    sr, ctx = _context(home)
    return sorted({finding.check_id for finding in sr.run_checks(ctx)})


def render(entries: List) -> str:
    """The file, column-aligned so it stays readable when hand-edited."""
    width = max((len(entry.check_id) for entry in entries), default=0)
    lines = [HEADER]
    for entry in sorted(entries, key=lambda item: item.check_id):
        lines.append(f"{entry.check_id.ljust(width)} | {entry.since} | {entry.reason}")
    return "\n".join(lines) + "\n"


def _verify(sr, text: str, expected: List) -> None:
    """Re-parse what is about to be written and confirm it says the same thing.

    Separate function because the atomicity test replaces it: the failure that
    must be exercised is a write that gets as far as the temp file and is then
    rejected, and there is no malformed input that can produce it - render()
    refuses those inputs earlier.
    """
    parsed = sr.parse_mutes(text)
    if len(parsed) != len(expected):
        raise MuteError(f"refusing to write: {len(expected)} entries in, "
                        f"{len(parsed)} read back")
    for got, want in zip(sorted(parsed, key=lambda item: item.check_id),
                         sorted(expected, key=lambda item: item.check_id)):
        if (got.check_id, got.since, got.reason) != (want.check_id, want.since, want.reason):
            raise MuteError(f"refusing to write: {want.check_id} would not read back")


def write(home: str, entries: List) -> str:
    """Persist the file. Returns the backup path, or "" if there was none.

    Order matters and is the whole point: backup first, then a temp file in the
    same directory (so the rename is atomic and cannot cross a filesystem), then
    validate what was actually written by re-parsing it, and only then replace.
    A failure at any step removes the temp file and leaves the original as it was.
    """
    sr, _ctx = _context(home)
    path = mutes_path(home)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)

    backup = ""
    if os.path.exists(path):
        backup = f"{path}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(path, backup)

    text = render(entries)
    temp = f"{path}.tmp_{os.getpid()}"
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
        # Before the rename, never after: the file must not exist at its final
        # name with the wrong mode, however briefly.
        os.chmod(temp, 0o600)
        _verify(sr, text, entries)
        os.replace(temp, path)
    except Exception:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return backup


def mute(home: str, check_id: str, reason: str,
         valid_ids: Optional[List[str]] = None) -> str:
    """Add or replace one entry. Returns the backup path."""
    sr = _readiness()
    check_id = (check_id or "").strip()
    reason = (reason or "").strip()

    if not check_id:
        raise MuteError("no check to mute")
    if not reason:
        # The only field that makes the entry survivable. An entry nobody can
        # justify a year later gets removed rather than understood, which brings
        # the message back on a host that decided against it.
        raise MuteError(f"{check_id}: a reason is required — "
                        f'ownerp_mute.py {check_id} --reason "why it does not apply here"')
    if sr.MUTE_SEPARATOR in check_id or "\n" in check_id:
        raise MuteError(f"{check_id!r} is not a valid check id")
    if "\n" in reason:
        raise MuteError("the reason must be a single line")
    if check_id in sr.UNMUTABLE:
        raise MuteError(f"{check_id} cannot be muted: it reports mutes that no "
                        f"longer match a check, and muting it would switch off "
                        f"the guard against silent mutes")
    if valid_ids is not None and check_id not in valid_ids:
        raise MuteError(f"unknown check: {check_id}\nvalid ids: "
                        + ", ".join(sorted(valid_ids)))

    entries = [entry for entry in load(home) if entry.check_id != check_id]
    entries.append(sr.MuteEntry(check_id, time.strftime("%Y-%m-%d"), reason))
    return write(home, entries)


def unmute(home: str, check_id: str) -> str:
    """Remove one entry. Returns the backup path."""
    check_id = (check_id or "").strip()
    entries = load(home)
    remaining = [entry for entry in entries if entry.check_id != check_id]
    if len(remaining) == len(entries):
        raise MuteError(f"{check_id} is not muted on this host")
    return write(home, remaining)
```

`_verify()` calls `sr.parse_mutes(text)` — a text-only parser that `read_mutes()` must now be built on. Refactor in `scripts/server-readiness.py`, splitting the function added in Task 2:

```python
def parse_mutes(text: str) -> List[MuteEntry]:
    """Parse mute-file text. Lines that do not parse are simply not mutes."""
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # maxsplit=2: the reason is free text and may itself contain a pipe.
        parts = line.split(MUTE_SEPARATOR, 2)
        if len(parts) != 3:
            continue
        check_id, since, reason = (part.strip() for part in parts)
        if not check_id or not reason:
            continue
        entries.append(MuteEntry(check_id, since, reason))
    return entries


def read_mutes(ctx: HealthContext) -> List[MuteEntry]:
    """This host's mutes. Missing or unreadable yields nothing rather than
    raising: one bad hand-edit must cost neither the other mutes nor the report.
    """
    text = _read(mutes_path(ctx))
    return parse_mutes(text) if text is not None else []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_ownerp_mute -v`
Expected: PASS (18 tests)

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: PASS — the parser refactor is covered by Task 2's tests

- [ ] **Step 5: Commit**

```bash
chmod +x scripts/ownerp_mute.py
git add scripts/ownerp_mute.py scripts/server-readiness.py tests/test_ownerp_mute.py
git commit -m "[ADD] ownerp_mute.py owns the write path for muted checks

server-readiness.py promises in its header never to write, and that is
worth more than a --mute flag on it. Same split as ownerp_state/
ownerp_wizard: the reader stays in the module that is always present, the
writer is its own script.

Write path from ownerp_cron.py step for step -- backup, temp file in the
same directory, re-parse and compare, then os.replace. Mode 0600 before
the rename, never after.

A mute without a reason is refused. It is the only field that makes the
entry survivable a year later."
```

---

### Task 6: The command line

**Files:**
- Modify: `scripts/ownerp_mute.py`
- Test: `tests/test_ownerp_mute.py`

**Interfaces:**
- Consumes: `mute()`, `unmute()`, `load()`, `check_ids()`
- Produces: `build_parser()`, `main(argv=None) -> int`. Exit codes: `0` success, `1` refused with a message, `2` the reader is unusable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ownerp_mute.py`:

```python
import io  # noqa: E402  — add to the imports at the top of the file
import contextlib  # noqa: E402


class CliTest(MuteWriteFixture):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = om.main(["--home", self.home, *args])
        return code, out.getvalue() + err.getvalue()

    def test_list_on_an_empty_host_says_so_and_succeeds(self):
        code, text = self.run_cli("--list")
        self.assertEqual(code, 0)
        self.assertIn("no checks are muted", text.lower())

    def test_mute_then_list_shows_the_entry(self):
        self.assertEqual(self.run_cli("backup_recency", "--reason",
                                      "test server", "--no-verify-id")[0], 0)
        code, text = self.run_cli("--list")
        self.assertEqual(code, 0)
        self.assertIn("backup_recency", text)
        self.assertIn("test server", text)

    def test_mute_without_a_reason_exits_1_and_writes_nothing(self):
        code, text = self.run_cli("backup_recency", "--no-verify-id")
        self.assertEqual(code, 1)
        self.assertIn("reason", text.lower())
        self.assertFalse(os.path.exists(self.path()))

    def test_unmute_reports_when_nothing_was_muted(self):
        code, text = self.run_cli("--unmute", "backup_recency")
        self.assertEqual(code, 1)
        self.assertIn("not muted", text.lower())

    def test_a_successful_write_names_the_backup_or_says_it_was_new(self):
        self.run_cli("backup_recency", "--reason", "test", "--no-verify-id")
        code, text = self.run_cli("certbot_timer_window", "--reason", "own certs",
                                  "--no-verify-id")
        self.assertEqual(code, 0)
        self.assertIn("backup", text.lower())
```

`--no-verify-id` exists so the CLI tests do not have to run the whole readiness
suite against a throwaway tree. Verification against real ids is the default and
is covered by `RefusalTest` at the API level.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_ownerp_mute.CliTest -v`
Expected: FAIL — `AttributeError: module 'ownerp_mute' has no attribute 'main'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/ownerp_mute.py`:

```python
# ==============================================================================
# Command line
# ==============================================================================

def format_list(entries: List) -> str:
    if not entries:
        return "No checks are muted on this host."
    width = max(len(entry.check_id) for entry in entries)
    lines = [f"{len(entries)} muted on this host:", ""]
    for entry in sorted(entries, key=lambda item: item.check_id):
        lines.append(f"  {entry.check_id.ljust(width)}  since {entry.since}  {entry.reason}")
    lines += ["", "  Unmute: ownerp_mute.py --unmute <check_id>"]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mark a readiness finding as not applicable on this host.",
        epilog="A muted check still runs and still shows its line in the full "
               "report; it just carries no weight.",
    )
    parser.add_argument("check_id", nargs="?", help="the check to mute")
    parser.add_argument("--reason", help="why it does not apply here (required)")
    parser.add_argument("--unmute", metavar="CHECK_ID", help="remove a mute")
    parser.add_argument("--list", action="store_true", dest="list_entries",
                        help="show what is muted on this host")
    parser.add_argument("--home", default=None,
                        help="where the configuration lives (default: ~)")
    parser.add_argument("--no-verify-id", action="store_true",
                        help="skip checking the id against the readiness report")
    parser.add_argument("--version", action="version",
                        version=f"ownerp_mute.py {SCRIPT_VERSION} ({SCRIPT_DATE})")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    home = args.home or os.path.expanduser("~")

    try:
        if args.list_entries:
            print(format_list(load(home)))
            return 0

        if args.unmute:
            backup = unmute(home, args.unmute)
            print(f"{args.unmute} is no longer muted. "
                  f"Backup: {os.path.basename(backup)}")
            return 0

        if not args.check_id:
            build_parser().print_help()
            return 0

        # Running the checks to learn the valid ids costs a second or two, so it
        # is skippable - but it is the default, because a typo that lands in the
        # file is silent until somebody wonders why the message came back.
        valid = None if args.no_verify_id else check_ids(home)
        backup = mute(home, args.check_id, args.reason or "", valid)
        where = f"Backup: {os.path.basename(backup)}" if backup else "New file."
        print(f"{args.check_id} is muted on this host. {where}")
        print("It still runs and still shows in `chk`; it no longer counts.")
        return 0

    except MuteError as exc:
        print(str(exc), file=sys.stderr)
        return 2 if "run ups" in str(exc) else 1
    except OSError as exc:
        print(f"cannot write the mute file: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_ownerp_mute -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/ownerp_mute.py tests/test_ownerp_mute.py
git commit -m "[ADD] ownerp_mute.py command line

--list, mute with a reason, --unmute. Verifying the id against the real
readiness report is the default rather than an option: running the checks
costs a second, and a typo that lands in the file is silent until somebody
wonders why the message came back."
```

---

### Task 7: `chk --muted`

**Files:**
- Modify: `scripts/server-readiness.py` (`build_parser` `:926`, `main` `:945`)
- Modify: `fish/functions/linux/chk.fish`
- Test: `tests/test_readiness_mute.py`

**Interfaces:**
- Consumes: `read_mutes()`, `derived_mutes()`
- Produces: `server-readiness.py --muted`, display only

- [ ] **Step 1: Write the failing test**

Append to `tests/test_readiness_mute.py`:

```python
import contextlib  # noqa: E402  — add to the imports at the top of the file


class MutedListingTest(MuteFixture):
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sr.main(["--home", self.home, "--root", self.home, *args])
        return code, out.getvalue()

    def test_muted_lists_the_explicit_entries(self):
        self.write_mutes("certbot_timer_window | 2026-08-21 | own certificates\n")
        code, text = self.run_cli("--muted")
        self.assertEqual(code, 0)
        self.assertIn("certbot_timer_window", text)
        self.assertIn("own certificates", text)
        self.assertIn("2026-08-21", text)

    def test_muted_says_so_when_nothing_is_muted(self):
        code, text = self.run_cli("--muted")
        self.assertEqual(code, 0)
        self.assertIn("no checks are muted", text.lower())

    def test_muted_names_a_derived_mute_as_derived(self):
        """Otherwise an operator looks for it in the file and does not find it."""
        path = self.ctx.p(sr.CRON_DEST)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#OWNERP-DISABLED# 0 2 * * * root /root/container2backup.py\n")
        code, text = self.run_cli("--muted")
        self.assertEqual(code, 0)
        self.assertIn("backup_recency", text)
        self.assertIn("cron job disabled", text)

    def test_muted_never_writes(self):
        before = sorted(os.listdir(self.home))
        self.run_cli("--muted")
        self.assertEqual(sorted(os.listdir(self.home)), before)

    def test_muted_exits_zero_even_with_a_failing_check(self):
        """It is a listing, not a verdict."""
        self.assertEqual(self.run_cli("--muted")[0], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_readiness_mute.MutedListingTest -v`
Expected: FAIL — `SystemExit: 2`, `unrecognized arguments: --muted`

- [ ] **Step 3: Write minimal implementation**

In `scripts/server-readiness.py`, add to the mutually exclusive group in `build_parser()`:

```python
    mode.add_argument("--muted", action="store_true",
                      help="list the checks muted on this host and exit")
```

Add the renderer next to `print_report()`:

```python
def print_muted(ctx: HealthContext, stream=None) -> None:
    """List what is muted here, and where each mute comes from.

    Derived mutes are labelled as such: an operator who sees one and then goes
    looking for it in readiness-mutes.conf will not find it, and would
    reasonably conclude the tool is lying to them.
    """
    stream = stream or sys.stdout
    explicit = read_mutes(ctx)
    derived = derived_mutes(ctx)
    rows = [(entry.check_id, entry.since, entry.reason) for entry in explicit]
    known = {entry.check_id for entry in explicit}
    rows += [(check_id, "derived", reason)
             for check_id, reason in sorted(derived.items())
             if check_id not in known]

    def emit(text: str = "") -> None:
        print(text, file=stream)

    emit()
    emit("=" * 60)
    emit("  Muted readiness checks")
    emit("=" * 60)
    if not rows:
        emit("  No checks are muted on this host.")
    else:
        width = max(len(row[0]) for row in rows)
        for check_id, since, reason in sorted(rows):
            emit(f"  {check_id.ljust(width)}  {since:<10}  {reason}")
        emit("-" * 60)
        emit(f"  {len(rows)} muted · file: {mutes_path(ctx)}")
        emit("  Add: ownerp_mute.py <check_id> --reason \"...\"")
        emit("  Remove: ownerp_mute.py --unmute <check_id>")
    emit("=" * 60)
    emit()
```

In `main()`, handle it before running the checks:

```python
    if args.muted:
        print_muted(ctx)
        return 0

    findings = run_checks(ctx)
```

Update `fish/functions/linux/chk.fish` to 1.1.0:

```fish
# Server Readiness Check Function
# Version 1.1.0 | 21.08.2026

function chk --description "Check whether this server is in the expected state"
    # Full report including the checks that passed. getScripts.py runs the same
    # script with --brief at the end of every `ups`; this is the on-demand view.
    # `chk --muted` lists what is deliberately not counted on this host.
    # Needs root: reads /etc/cron.d, /etc/logrotate.d and root's crontab.
    sudo $HOME/server-readiness.py $argv
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_readiness_mute -v`
Expected: PASS (32 tests)

Run: `python3 -m unittest tests.test_fish_help -v`
Expected: PASS — every advertised command still resolves

- [ ] **Step 5: Commit**

```bash
git add scripts/server-readiness.py fish/functions/linux/chk.fish tests/test_readiness_mute.py
git commit -m "[ADD] chk --muted lists what this host does not count

Display only -- server-readiness.py still never writes, and --muted is a
report mode like --brief.

A derived mute is labelled as derived. An operator who sees one and then
goes looking for it in readiness-mutes.conf would not find it, and would
reasonably conclude the tool is lying to them."
```

---

### Task 8: Muting from the console

**Files:**
- Modify: `scripts/ownerp_console.py` (`_sibling` calls `:207`, `_fill_system` `:640`, `ACTIONS` `:661`, `_act` `:701`, modals near `:424`)
- Test: `tests/test_ownerp_console.py`

**Interfaces:**
- Consumes: `ownerp_mute.mute()`, `ownerp_mute.unmute()`, `ownerp_mute.MuteError`
- Produces: `MuteReason(ModalScreen)`; `ConsoleApp.ACTIONS["system"]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ownerp_console.py` (follow the file's existing import style):

```python
class SystemTabActionsTest(unittest.TestCase):
    """The System tab gained actions. It deliberately had none: readiness
    findings are facts, not settings. With muting they are both — the finding
    stays a fact, its relevance on this host becomes a setting."""

    def test_the_system_tab_offers_mute_and_unmute(self):
        actions = console.ConsoleApp.ACTIONS["system"]
        names = [name for _key, _label, name in actions]
        self.assertIn("mute", names)
        self.assertIn("unmute", names)
        self.assertIn("cancel", names)

    def test_every_system_label_fits_the_menu_box(self):
        """The menu clips rather than wrapping, and a clipped label reads as a
        different setting than the one it toggles."""
        for _key, label, _name in console.ConsoleApp.ACTIONS["system"]:
            self.assertLessEqual(len(label), console.MENU_LABEL_WIDTH)

    def test_every_system_action_has_a_distinct_key(self):
        keys = [key for key, _label, _name in console.ConsoleApp.ACTIONS["system"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_console_still_writes_nothing_itself(self):
        """Every change goes through the module that owns the file."""
        with open(console.__file__, "r", encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("os.replace(", "os.chmod(", "shutil.copy2("):
            self.assertNotIn(forbidden, source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_ownerp_console -v`
Expected: FAIL — `KeyError: 'system'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/ownerp_console.py`, load the writer beside the others (`:207`):

```python
cron = _sibling("ownerp_cron.py", "ownerp_cron")
mute = _sibling("ownerp_mute.py", "ownerp_mute")
```

Add the modal next to `Reschedule` (`:424`):

```python
class MuteReason(ModalScreen):
    """Why a finding does not apply on this host. Required, not optional.

    An entry nobody can justify a year later gets removed rather than
    understood, which brings the message back on a host that decided against it.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, finding):
        super().__init__()
        self.finding = finding

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(f"Mute {self.finding.title}", classes="dialog-title")
            yield Label("It keeps running and keeps its line in the full "
                        "report — it stops counting.", classes="dialog-detail")
            yield Input(placeholder="why it does not apply here", id="value")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Mute", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def _submitted(self) -> None:
        self._save()

    @on(Button.Pressed, "#save")
    def _save_pressed(self) -> None:
        self._save()

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        text = self.query_one("#value", Input).value.strip()
        if not text:
            self.notify("A reason is required.", severity="error")
            return
        self.dismiss(text)
```

Populate the row index in `_fill_system()` (`:640`) — row selection is what the menu hangs off — and mark the new state:

```python
    def _fill_system(self) -> None:
        table = self.query_one("#system", DataTable)
        table.clear()
        self._rows["system"] = {}
        section = self.server.health
        if not section.known:
            table.add_row("?", section.error, "")
            return
        for index, finding in enumerate(section.findings):
            severity = getattr(finding.severity, "value", finding.severity)
            key = table.add_row(
                {"OK": "ok", "WARN": "!", "FAIL": "XX", "MUTED": "off"}.get(severity, "-"),
                finding.title,
                f"{finding.detail} ({finding.note})" if finding.note else finding.detail)
            self._rows["system"][key] = index
```

Add to `ACTIONS` (`:661`), inside `MENU_LABEL_WIDTH = 26`:

```python
        "system": (("m", "mute on this host", "mute"),
                   ("u", "unmute", "unmute"),
                   ("c", "cancel", "cancel")),
```

Add the row title for the new tab in `_row_title()`:

```python
        if table_id == "system":
            return self.server.health.findings[index].title
```

Dispatch in `_act()` (`:701`), before the wizard branch — muting does not go through the wizard:

```python
        if table_id == "system":
            self._act_on_finding(self.server.health.findings[index], action)
            return
```

And the handler beside `_act_on_job()`:

```python
    def _act_on_finding(self, finding, action) -> None:
        if mute is None:
            self.notify("ownerp_mute.py is not installed - run ups.",
                        severity="error")
            return
        if action == "mute":
            self.push_screen(
                MuteReason(finding),
                lambda reason: reason and self._write_mute(
                    lambda: mute.mute(self.home, finding.check_id, reason)))
        elif action == "unmute":
            self._write_mute(lambda: mute.unmute(self.home, finding.check_id))

    def _write_mute(self, change) -> None:
        """Through ownerp_mute, which owns the file. The console writes nothing."""
        try:
            change()
        except Exception as exc:                  # MuteError, OSError
            self.notify(str(exc), severity="error")
            return
        self.notify("Mute list updated.")
        self.action_reload()
```

Note `mute.mute(self.home, ...)` rather than a bare call: the console already
resolves configuration under `self.home` (`_path_for()`, `:848`) so it can be
run against a test tree.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_ownerp_console -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/ownerp_console.py tests/test_ownerp_console.py
git commit -m "[ADD] mute a readiness finding from the console

The System tab deliberately had no actions, because readiness findings are
facts and not settings. With muting they are both: the finding stays a
fact, its relevance on this host becomes a setting. CLAUDE.md is corrected
rather than quietly left standing.

_fill_system() now records its row index, which is what the action menu
hangs off. The console still owns no write path -- ownerp_mute.py does."
```

---

### Task 9: Delivery, documentation, versions

Without this task the feature works in the repository and never reaches a server.

**Files:**
- Modify: `getScripts.py:3898` (the `scripts` list in `copy_scripts()`), version header
- Modify: `scripts/server-readiness.py:88` (`DELIVERED_SCRIPTS`), version header
- Modify: `scripts/ownerp_console.py` version header
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-08-21-readiness-mute-design.md`
- Test: `tests/test_delivered_scripts.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_delivered_scripts.py`, extend the existing test at `:97`:

```python
    def test_the_new_tools_are_on_the_delivery_list(self):
        delivered = delivered_names()
        for name in ("ownerp_cron.py", "ownerp_migrate.py", "ownerp_mute.py",
                     "nginx-cert-guard.py", "server-readiness.py"):
            self.assertIn(name, delivered)
```

And add, in the same class:

```python
    def test_delivery_and_the_version_check_agree(self):
        """Two lists, one fact. On ownerp_mute.py they disagreed once: ups would
        install it and the version check would never notice a stale copy."""
        import importlib.util
        path = os.path.join(REPO, "scripts", "server-readiness.py")
        spec = importlib.util.spec_from_file_location("server_readiness", path)
        sr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sr)
        for name in sr.DELIVERED_SCRIPTS:
            self.assertIn(name, delivered_names(),
                          f"{name} is version-checked but never delivered")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_delivered_scripts -v`
Expected: FAIL — `'ownerp_mute.py' not found in ...`

- [ ] **Step 3: Write minimal implementation**

In `getScripts.py`, add to the `scripts` list in `copy_scripts()` (`:3898`), after `"server-readiness.py"`:

```python
        "server-readiness.py",
        "ownerp_mute.py",
```

In `scripts/server-readiness.py`, add to `DELIVERED_SCRIPTS` (`:88`), after `"ownerp_cron.py"`:

```python
    "ownerp_cron.py",
    "ownerp_mute.py",
```

Version headers, all dated `21.08.2026`:

| File | Set `SCRIPT_VERSION` / header to |
|---|---|
| `scripts/server-readiness.py` | `1.5.0` (both `SCRIPT_VERSION` and the header block) |
| `scripts/ownerp_console.py` | `1.2.0` |
| `getScripts.py` | `9.21.0` |

In `scripts/server-readiness.py`, extend the header's "What it does" block:

```
#   (no flag)   Full report, including the checks that passed.
#   --brief     Only non-OK lines plus the summary. Used by getScripts.py.
#   --quiet     Like --brief, but prints nothing at all when everything is OK.
#               For cron: cron only mails when there is output, so a weekly job
#               speaks up only on actual drift.
#   --muted     List the checks this host deliberately does not count, and exit.
#
# A muted check still runs and still shows its line in the full report; it
# carries no weight in --brief, --quiet or the exit code. Muting is written by
# ownerp_mute.py; this script only reads the list, like everything else here.
```

In `CLAUDE.md`, correct the `ownerp_console.py` bullet that currently reads
*"the System tab has none, because readiness findings are facts, not settings"*:

```markdown
- **Select a row → an action menu, ctop-style** (v1.1.0): a small box at the
  top left over the table it acts on, one letter per action. It is placed
  there rather than centred so the row it belongs to stays visible. `ACTIONS`
  says what each tab offers. The System tab had none until v1.2.0, on the
  grounds that readiness findings are facts and not settings — with muting
  they are both: the finding stays a fact, its **relevance on this host**
  becomes a setting
```

Add section 15 to `CLAUDE.md` after `docker_table.py`:

```markdown
#### 15. ownerp_mute.py (v1.0.0)
- **Purpose**: Mark a readiness finding as true but not applicable on this
  host — permanently, with a reason. `chk --muted` lists them, `konsole` →
  System → `[m]` sets them
- **Why**: a host whose certificates come from an internal CA collects a
  permanent `certbot timer` WARN; a test server with no backups by design
  collects a permanent `Backup recency` FAIL that mails every Monday. Both
  findings are correct. The cost is not the noise: an operator who learns that
  two lines are always there stops reading the block, and the third line — the
  one that matters — goes with them. Same reasoning as `BENIGN_CHILD_NOISE` in
  `update_docker_odoo.py` and `OPTIONAL_INSTRUCTIONS` in
  `odoo_build_cache.py`, extended from two hard-coded lists to a per-host
  decision
- **Muted is not off**: the check still runs, still measures, still prints its
  line in the full report — with the date and the reason it does not count. It
  drops out of `--brief`, `--quiet` and the exit code, and nothing else. A
  check that was *removed* leaves a report that looks complete while a class
  of faults goes unwatched; a muted one leaves a line saying so
- **The count is never suppressed**, not even in `--brief`. A report that
  quietly omits part of itself is lying about its own coverage, and that is
  the one way muting could turn into hiding
- **The reader lives in `server-readiness.py`, the writer here.** The obvious
  arrangement is the opposite, and it is wrong: `server-readiness.py` runs on
  hosts where this script has not been delivered yet, so a reader that could be
  absent would silently stop every mute from applying and hand the operator
  back exactly the messages they had switched off
- **Not YAML**, against the repository's own default. `server-readiness.py`
  runs today without PyYAML — it imports `yaml` inside one check and SKIPs when
  it fails. A YAML mute file would inherit that failure mode; a three-field
  line cannot. Robustness beats format consistency for a file whose whole job
  is to stay quiet
- **A mute without a reason is refused.** It is the only field that makes the
  entry survivable: an entry nobody can justify a year later gets deleted
  rather than understood, which brings the message back on a host that decided
  against it
- **A disabled backup cron job mutes its own check, with no entry at all**
  (`DERIVED_MUTES`). `ownerp_cron.py` parks a switched-off job behind
  `#OWNERP-DISABLED#` rather than deleting it, so the cron file already records
  the decision — reading it beats asking for the same fact twice, and
  re-enabling the job brings the check back with nothing left behind
- **`mute_registry` is on `UNMUTABLE`**: it is the WARN that reports mute
  entries naming a check that no longer exists. Muting it would switch off the
  guard against silent mutes, and the failure it guards is the nastiest one
  here — the message simply returns one day while the file still looks like it
  should be preventing it
- **No expiry date**, deliberately. Both driving cases are permanent, and the
  risk an expiry would guard against — a mute nobody remembers — is already
  covered by the visible `[MUTED]` line and the count in every summary
```

Finally, record the parser-location decision in the spec so it does not
disagree with the code — add to `docs/superpowers/specs/2026-08-21-readiness-mute-design.md`
directly under the `ownerp_mute.py — the write path` heading:

```markdown
> **One correction the plan forced.** The spec did not say where the *parser*
> lives, and the obvious answer — with the writer — is wrong.
> `server-readiness.py` runs on hosts where `ownerp_mute.py` has not been
> delivered yet; a reader that could be absent would silently stop every mute
> from applying, which is the failure the stale-entry WARN exists to prevent,
> reintroduced one level up. The reader is therefore in `server-readiness.py`
> (`parse_mutes()`, `read_mutes()`) and this module imports it.
```

- [ ] **Step 4: Run the whole suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS, all files

Then confirm the two entry points really start:

Run: `python3 scripts/ownerp_mute.py --version && python3 scripts/server-readiness.py --muted --home /tmp --root /tmp`
Expected: version line; then a "No checks are muted on this host." block, exit 0

- [ ] **Step 5: Commit**

```bash
git add getScripts.py scripts/server-readiness.py scripts/ownerp_console.py CLAUDE.md docs/superpowers/specs/2026-08-21-readiness-mute-design.md tests/test_delivered_scripts.py
git commit -m "[ADD] deliver ownerp_mute.py and document what muting means

Both lists or neither: copy_scripts() installs it, DELIVERED_SCRIPTS
version-checks it. A test now asserts nothing can be on the second list
without being on the first -- that pairing has drifted before.

CLAUDE.md gains section 15 and has its System-tab note corrected rather
than left standing, and the spec records the one thing the plan had to
decide for it: the reader lives in server-readiness.py, not with the
writer."
```

---

## Self-Review

**Spec coverage** — every section maps to a task:

| Spec section | Task |
|---|---|
| The `MUTED` severity, channel table, rendering | 1 |
| Explicit source, file format, `ctx.home` resolution | 2, 5 |
| Applying mutes in `run_checks()`, stale entry `WARN` | 3 |
| Derived source (disabled cron job) | 4 |
| `ownerp_mute.py` write path, refusals, terminal-free API | 5 |
| CLI, `check_id` validation via `run_checks()` | 6 |
| `chk --muted` | 7 |
| Console System tab, `_fill_system` row index, `CLAUDE.md` reversal | 8, 9 |
| Out of scope (no expiry, no wildcards, no second channel) | not implemented, recorded in 9 |
| Delivery on both lists, versions, tests | 9 |

**Naming consistency** — checked across tasks: `mute_finding`, `read_mutes`, `parse_mutes`, `mutes_path`, `derived_mutes`, `MuteEntry`, `MUTE_SEPARATOR`, `UNMUTABLE`, `DERIVED_MUTES`, `MuteError`, `_verify`. Task 2 defines `read_mutes()` as a single function; Task 5 splits it into `parse_mutes()` + `read_mutes()` and says so explicitly, because `_verify()` needs a text-only parser.

**Two things a reviewer should push back on if they disagree:**

1. **Task 5 makes the atomicity test monkeypatch `_verify`.** There is no malformed input that reaches the temp file — `mute()` refuses those earlier — so the only way to exercise "written, then rejected, original intact" is to force the rejection. The alternative is not testing the most important promise in the module.
2. **Task 6's `--no-verify-id`** exists mainly so CLI tests need not run the full readiness suite against a throwaway tree. It is a real escape hatch too (a host where a check crashes), but if that reads as test-shaped API, the flag can go and the CLI tests can accept the slower path.

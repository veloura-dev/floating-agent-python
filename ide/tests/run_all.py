#!/usr/bin/env python3
"""Run every suite and print one summary.

    python3 tests/run_all.py

Needs a display. On a headless machine:
    Xvfb :99 -screen 0 1600x1000x24 &
    DISPLAY=:99 python3 tests/run_all.py

The table shows a short hash of each test file so that a stale copy is
obvious when comparing results between machines. The hash ignores line
endings, so Windows (CRLF) and Unix (LF) checkouts of the same file agree.
"""
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [
    ("core, languages, runner", "core_test.py"),
    ("filesystem, sandbox, menu", "fs_test.py"),
    ("images and PDFs", "media_test.py"),
    ("bare-python fallbacks", "media_nodeps_test.py"),
    ("file-type icons", "icons_test.py"),
    ("empty state, create, rename", "empty_test.py"),
    ("dialogs (real keystrokes)", "dialog_test.py"),
    ("design system", "design_test.py"),
    ("explorer indent guides", "guides_test.py"),
]
SUMMARY = re.compile(r"=====\s*PASS\s+(\d+)\s+FAIL\s+(\d+)")
CHECK = re.compile(r"^\s{2}(OK|FAIL)\s")


def fingerprint(path):
    """Hash of the file's *content*, ignoring line endings.

    Windows checkouts use CRLF, so a raw byte hash would differ from a
    Unix one for identical files and defeat the whole point of showing it.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return "missing!"
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()[:8]


def main():
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":99")
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    total_p = total_f = 0
    rows = []
    for label, script in SUITES:
        path = os.path.join(HERE, script)
        fp = fingerprint(path)
        if not os.path.exists(path):
            rows.append((label, fp, "-", "-", "MISSING FILE"))
            total_f += 1
            continue
        try:
            r = subprocess.run([sys.executable, path], capture_output=True,
                               text=True, timeout=900, env=env)
            out = r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            rows.append((label, fp, "-", "-", "TIMEOUT"))
            total_f += 1
            continue
        if verbose:
            print(f"----- {script} -----")
            print(out.rstrip())
        m = SUMMARY.search(out)
        if not m:
            rows.append((label, fp, "-", "-", "no summary"))
            total_f += 1
            print(f"--- {script} produced no summary ---")
            print("\n".join(out.strip().splitlines()[-8:]) + "\n")
            continue
        p, f = int(m.group(1)), int(m.group(2))
        ran = sum(1 for line in out.splitlines() if CHECK.match(line))
        total_p += p
        total_f += f
        status = "ok" if not f else "FAILURES"
        rows.append((label, fp, p, f, status))
        if f and not verbose:
            for line in out.splitlines():
                if line.strip().startswith("XX"):
                    print("   " + line.strip())
        if ran != p + f:
            print(f"   note: {script} printed {ran} checks but counted "
                  f"{p + f}")

    print("\n" + "=" * 72)
    print(f"{'suite':30}{'file':>10}{'pass':>7}{'fail':>6}   status")
    print("-" * 72)
    for label, fp, p, f, status in rows:
        print(f"{label:30}{fp:>10}{str(p):>7}{str(f):>6}   {status}")
    print("-" * 72)
    print(f"{'TOTAL':30}{'':>10}{total_p:>7}{total_f:>6}")
    print("=" * 72)
    print("Run with -v to see every individual check.")
    return 1 if total_f else 0


if __name__ == "__main__":
    sys.exit(main())

"""Each panel module must import cleanly in a fresh Python process.

This guards against import cycles hidden by importing app_panels first.
"""
import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ("settings_panel", "notepad_panel", "conversation_panels", "app_panels")


def main():
    failures = []
    for module in MODULES:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            failures.append((module, result.stderr.strip()))
            print(f"FAIL - direct import of {module}")
            print(result.stderr.strip())
        else:
            print(f"PASS - direct import of {module}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

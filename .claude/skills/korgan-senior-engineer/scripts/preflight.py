#!/usr/bin/env python3
"""Read-only repository context for the korgan-senior-engineer Claude skill."""

from __future__ import annotations

import pathlib
import subprocess


def run(*args: str) -> str:
    try:
        completed = subprocess.run(
            list(args),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # diagnostic only; never blocks skill loading
        return f"<unavailable: {type(exc).__name__}>"
    text = completed.stdout.strip()
    if completed.returncode != 0:
        return f"<command failed {completed.returncode}: {text[:300]}>"
    return text or "<empty>"


def main() -> None:
    root = run("git", "rev-parse", "--show-toplevel")
    branch = run("git", "branch", "--show-current")
    head = run("git", "rev-parse", "--short=12", "HEAD")
    status = run("git", "status", "--short")
    diff_stat = run("git", "diff", "--stat")
    recent = run("git", "log", "-5", "--oneline", "--decorate=no")

    test_count = "<unknown>"
    try:
        if not root.startswith("<"):
            tests = pathlib.Path(root) / "tests"
            if tests.is_dir():
                test_count = str(sum(1 for p in tests.rglob("test_*.py") if p.is_file()))
    except Exception:
        pass

    print("KORGAN senior preflight (read-only)")
    print(f"repo: {root}")
    print(f"branch: {branch}")
    print(f"head: {head}")
    print(f"pytest test files: {test_count}")
    print("worktree status:")
    print(status)
    print("diff stat:")
    print(diff_stat)
    print("recent commits:")
    print(recent)


if __name__ == "__main__":
    main()

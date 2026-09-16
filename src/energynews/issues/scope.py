"""IssueScopeGuard (NFR-8). Task-authored commits are identified by the 'issue:' commit-message prefix."""
from __future__ import annotations
import subprocess
import sys


def check_issue_scope(changed_paths: list[str], commit_message: str) -> bool:
    if not commit_message.startswith("issue:"):
        return True
    return all(p.startswith("issues/") for p in changed_paths)


def main(argv=None):
    """Usage: python -m energynews.issues.scope <before_sha> <after_sha>. Prints offending commits; exit 1 if any."""
    before, after = (argv or sys.argv[1:])[:2]
    rng = f"{before}..{after}" if before and set(before) != {"0"} else after
    shas = subprocess.run(["git", "rev-list", "--reverse", rng], capture_output=True, text=True, check=True).stdout.split()
    bad = []
    for s in shas:
        msg = subprocess.run(["git", "log", "-1", "--format=%s", s], capture_output=True, text=True, check=True).stdout.strip()
        paths = subprocess.run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", s], capture_output=True, text=True, check=True).stdout.split()
        if not check_issue_scope(paths, msg):
            bad.append(s)
            print(f"ISSUE_SCOPE_VIOLATION {s} '{msg}' touched {[p for p in paths if not p.startswith('issues/')]}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

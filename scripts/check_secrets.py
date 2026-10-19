"""Refuse to ship anything that looks like a secret.

    python scripts/check_secrets.py            # every file git tracks (CI, `make secrets`)
    python scripts/check_secrets.py --staged   # what is about to be committed (pre-commit hook)

`make hooks` installs the second form as .git/hooks/pre-commit. Real keys belong in `.env`,
which is git-ignored; this script also fails if a `.env` file other than `.env.example` is
tracked or staged. It is a safety net for the obvious mistakes, not a replacement for GitHub's
push protection, which the README recommends switching on for your copy.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = {
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
    "Slack token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "JSON web token": r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "key or password with a value": (
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9/+_-]{16,}"
    ),
    "database URL with a real password": (
        r"(?i)\b(?:postgres(?:ql)?|mysql|redis|amqp|mongodb)(?:\+\w+)?://\w+:"
        r"(?!(?:n8n|leadintake|postgres|password|changeme|secret|example)@)[^@\s/]+@"
    ),
}
_COMPILED = {name: re.compile(p) for name, p in PATTERNS.items()}
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".onnx"}


def _git(*args: str) -> str:
    cmd = ["git", "-c", "core.quotePath=false", *args]
    return subprocess.check_output(cmd, cwd=ROOT, text=True, encoding="utf-8")


def _names(*args: str) -> list[str]:
    return [n for n in _git(*args, "-z").split(chr(0)) if n]


def _forbidden_name(path: str) -> bool:
    name = Path(path).name
    return name == ".env" or (name.startswith(".env.") and name != ".env.example")


def _files(staged: bool) -> list[tuple[str, str]]:
    """(path, content) pairs: the index for --staged, the working tree copy otherwise."""
    if staged:
        names = _names("diff", "--cached", "--name-only", "--diff-filter=ACMR")
        return [(n, _git("show", f":{n}")) for n in names if Path(n).suffix not in _SKIP_SUFFIXES]
    names = _names("ls-files")
    out = []
    for n in names:
        if Path(n).suffix in _SKIP_SUFFIXES:
            continue
        out.append((n, (ROOT / n).read_text(encoding="utf-8", errors="replace")))
    return out


def main(argv: list[str]) -> int:
    staged = "--staged" in argv
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    problems: list[str] = []
    files = _files(staged)
    for path, text in files:
        if _forbidden_name(path):
            problems.append(
                f"{path}: environment file must not be committed (it is for .env.example only)"
            )
        for name, pattern in _COMPILED.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                shown = match.group(0)[:12] + "..."
                problems.append(f"{path}:{line}: looks like a {name} ({shown})")
    where = "staged" if staged else "tracked"
    if problems:
        print(f"check_secrets: {len(problems)} problem(s) in {where} files:")
        for p in problems:
            print("  " + p)
        print("Move real values to .env (git-ignored) and commit a placeholder instead.")
        return 1
    print(f"check_secrets: nothing that looks like a secret in {len(files)} {where} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

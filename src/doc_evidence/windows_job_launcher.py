"""Gate worker startup until its launcher belongs to a Windows Job Object."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def run(
    *,
    gate: Path,
    pid_file: Path,
    command: tuple[str, ...],
    timeout_seconds: float = 30.0,
) -> int:
    if (
        not gate.is_absolute()
        or not pid_file.is_absolute()
        or gate.parent != pid_file.parent
        or not command
    ):
        raise ValueError("Windows worker-launch gate is invalid")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if gate.is_file():
            gate.unlink()
            process = subprocess.Popen(command)
            pid_file.write_text(str(process.pid), encoding="ascii")
            return process.wait()
        time.sleep(0.01)
    raise TimeoutError("Windows worker-launch gate timed out")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gate", type=Path)
    parser.add_argument("pid_file", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        return run(
            gate=args.gate,
            pid_file=args.pid_file,
            command=tuple(args.command),
        )
    except (OSError, TimeoutError, ValueError) as error:
        print(f"doc-evidence worker launcher: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    raise SystemExit(main())

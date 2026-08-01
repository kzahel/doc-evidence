from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    request_path = Path(sys.argv[1])
    response_path = Path(sys.argv[2])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    settings = request.get("settings", {})
    behavior = settings.get("behavior", "success")
    attempt_dir = Path(request["attempt_dir"])
    if behavior == "block":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        (attempt_dir / "child.pid").write_text(str(child.pid), encoding="ascii")
        sys.stdout.write("x" * 200_000)
        sys.stdout.flush()
        sys.stderr.write("y" * 200_000)
        sys.stderr.flush()
        time.sleep(120)
        return 1

    extractor_id = request["extractor_id"]
    run_key = str(settings.get("run_key", "fixture-run-key"))
    run_id = f"{extractor_id}:{run_key}"
    run_dir = attempt_dir / "runs" / extractor_id / run_key
    run_dir.mkdir(parents=True)
    text = str(settings.get("text", "fixture evidence"))
    (run_dir / "text.txt").write_text(text, encoding="utf-8")
    (run_dir / "raw.txt").write_text("raw fixture", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "extractor_id": extractor_id,
                "run_id": run_id,
                "run_key": run_key,
                "source_sha256": request["source_sha256"],
                "status": "ok",
                "started_at": str(time.time_ns()),
                "completed_at": str(time.time_ns()),
                "runtime_seconds": time.monotonic(),
                "descriptor": {"fixture": True},
                "warnings": [],
                "raw_artifacts": {"raw": "raw.txt"},
            }
        ),
        encoding="utf-8",
    )
    normalized = {
        "schema_version": 1,
        "extractor_id": extractor_id,
        "source_sha256": request["source_sha256"],
        "page_count": 1,
        "table_count": 0,
        "pages": [
            {
                "page_number": 1,
                "text": text,
                "character_count": len(text),
                "non_whitespace_character_count": sum(
                    not character.isspace() for character in text
                ),
            }
        ],
    }
    if behavior == "corrupt":
        normalized["source_sha256"] = "0" * 64
    (run_dir / "normalized.json").write_text(
        json.dumps(normalized),
        encoding="utf-8",
    )
    response_path.write_text(
        json.dumps(
            {
                "protocol_version": 1,
                "status": "ok",
                "extractor_id": extractor_id,
                "run_id": run_id,
                "run_key": run_key,
            }
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

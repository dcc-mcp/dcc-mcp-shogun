"""CI smoke for the versioned doctor/verify JSON and exit-code contract."""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    for verb, expected_code in (("doctor", 10), ("verify", 40)):
        result = subprocess.run(
            [sys.executable, "-m", "dcc_mcp_shogun.server", verb, "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != expected_code:
            raise SystemExit(
                f"{verb} returned {result.returncode}, expected {expected_code}: {result.stderr}"
            )
        payload = json.loads(result.stdout)
        required = {
            "schema_version",
            "status",
            "dcc_type",
            "adapter_version",
            "core_version",
            "steps",
            "next_steps",
            "verify",
            "directly_usable",
        }
        missing = required - payload.keys()
        if missing:
            raise SystemExit(f"{verb} JSON is missing fields: {sorted(missing)}")
        if payload["schema_version"] != "1.0" or payload["dcc_type"] != "shogun":
            raise SystemExit(f"{verb} returned an unexpected contract identity")
        if payload["directly_usable"] is not False:
            raise SystemExit(f"{verb} unexpectedly reported a hostless CI runner as usable")


if __name__ == "__main__":
    main()

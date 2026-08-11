from pathlib import Path

from dcc_mcp_core import validate_skill


def main() -> None:
    skill_root = Path(__file__).parents[1] / "src" / "dcc_mcp_shogun" / "skills"
    failed = False
    for skill_dir in sorted(path for path in skill_root.iterdir() if path.is_dir()):
        report = validate_skill(str(skill_dir))
        for issue in report.issues:
            print(f"[{issue.severity}] {skill_dir.name}: {issue.category}: {issue.message}")
        failed = failed or report.has_errors
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

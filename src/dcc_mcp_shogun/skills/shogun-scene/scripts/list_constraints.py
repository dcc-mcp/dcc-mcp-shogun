from _result import safe_result
from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import list_constraints


@skill_entry
def main(subject: str, skeleton: str, max_constraints: int = 1000, **_kwargs):
    return safe_result(
        "Shogun subject constraints listed.",
        lambda: list_constraints(subject, skeleton, max_constraints),
    )


if __name__ == "__main__":
    run_main(main)

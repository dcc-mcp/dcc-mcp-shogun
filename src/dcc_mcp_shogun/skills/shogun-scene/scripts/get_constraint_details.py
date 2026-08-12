from _result import safe_result
from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import constraint_details


@skill_entry
def main(subject: str, constraint: str, skeleton: str, **_kwargs):
    return safe_result(
        "Shogun constraint details read.",
        lambda: constraint_details(subject, constraint, skeleton),
    )


if __name__ == "__main__":
    run_main(main)

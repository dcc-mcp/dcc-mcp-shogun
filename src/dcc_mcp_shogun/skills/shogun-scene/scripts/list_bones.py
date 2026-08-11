from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_bones


@skill_entry
def main(subject: str, skeleton: str, max_bones: int = 1000, **_kwargs):
    return safe_result(
        "Shogun subject skeleton listed.",
        lambda: list_bones(subject, skeleton, max_bones),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

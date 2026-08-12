from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import quick_post


@skill_entry
def main(process_level: str, range_mode: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post QuickPost completed.",
        lambda: quick_post(process_level, range_mode),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

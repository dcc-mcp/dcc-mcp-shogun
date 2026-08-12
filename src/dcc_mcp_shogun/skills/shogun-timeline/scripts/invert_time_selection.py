from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import invert_time_selection


@skill_entry
def main(**_kwargs):
    return safe_result(
        "Vicon Shogun Post time selection inverted.",
        invert_time_selection,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import select_time_range


@skill_entry
def main(start_frame: int, end_frame: int, replace: bool = True, **_kwargs):
    return safe_result(
        "Vicon Shogun Post time range selected.",
        lambda: select_time_range(start_frame, end_frame, replace=replace),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

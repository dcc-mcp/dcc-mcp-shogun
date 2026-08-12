from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import inspect_timeline


@skill_entry
def main(max_selected_ranges: int = 100, **_kwargs):
    return safe_result(
        "Vicon Shogun Post timeline inspected.",
        lambda: inspect_timeline(max_selected_ranges),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

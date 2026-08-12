from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import set_animation_range


@skill_entry
def main(start_frame: int, end_frame: int, **_kwargs):
    return safe_result(
        "Vicon Shogun Post animation range updated.",
        lambda: set_animation_range(start_frame, end_frame),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

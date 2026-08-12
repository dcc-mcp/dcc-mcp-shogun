from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import set_current_frame


@skill_entry
def main(frame: int, **_kwargs):
    return safe_result(
        "Vicon Shogun Post current frame updated.",
        lambda: set_current_frame(frame),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_video_cameras


@skill_entry
def main(max_cameras: int = 500, **_kwargs):
    return safe_result(
        "Vicon Shogun Post video cameras listed.",
        lambda: list_video_cameras(max_cameras=max_cameras),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

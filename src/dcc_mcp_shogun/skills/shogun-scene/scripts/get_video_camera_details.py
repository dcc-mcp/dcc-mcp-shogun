from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import video_camera_details


@skill_entry
def main(object_path: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post video camera inspected.",
        lambda: video_camera_details(object_path=object_path),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

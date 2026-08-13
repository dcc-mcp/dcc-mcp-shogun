from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import rigid_body_details


@skill_entry
def main(object_path: str, frame: int, max_markers: int = 100, **_kwargs):
    return safe_result(
        "Vicon Shogun Post rigid body inspected.",
        lambda: rigid_body_details(
            object_path=object_path,
            frame=frame,
            max_markers=max_markers,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

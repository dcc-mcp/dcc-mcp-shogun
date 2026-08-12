from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import update_reconstruct_settings


@skill_entry
def main(
    min_cameras_to_start=None,
    min_cameras_to_continue=None,
    min_radius=None,
    max_radius=None,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post reconstruction settings updated.",
        lambda: update_reconstruct_settings(
            min_cameras_to_start=min_cameras_to_start,
            min_cameras_to_continue=min_cameras_to_continue,
            min_radius=min_radius,
            max_radius=max_radius,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_rigid_bodies


@skill_entry
def main(max_rigid_bodies: int = 500, **_kwargs):
    return safe_result(
        "Vicon Shogun Post rigid bodies listed.",
        lambda: list_rigid_bodies(max_rigid_bodies=max_rigid_bodies),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

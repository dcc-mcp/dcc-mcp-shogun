from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import set_trajectory_sample


@skill_entry
def main(
    subject: str,
    marker: str,
    frame: int,
    x: float,
    y: float,
    z: float,
    exists: bool = True,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post trajectory sample updated and verified.",
        lambda: set_trajectory_sample(subject, marker, frame, x=x, y=y, z=z, exists=exists),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

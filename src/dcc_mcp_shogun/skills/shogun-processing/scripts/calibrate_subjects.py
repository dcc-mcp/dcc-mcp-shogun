from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import calibrate_subjects


@skill_entry
def main(skeleton: str, subjects: str, range_mode: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post subject calibration completed.",
        lambda: calibrate_subjects(skeleton, subjects, range_mode),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

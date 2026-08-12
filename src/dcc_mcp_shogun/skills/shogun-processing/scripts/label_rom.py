from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import label_rom


@skill_entry
def main(subjects: str, range_mode: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post ROM labeling completed.",
        lambda: label_rom(subjects, range_mode),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

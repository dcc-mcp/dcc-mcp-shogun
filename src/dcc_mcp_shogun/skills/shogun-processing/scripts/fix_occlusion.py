from _result import safe_result
from _run import run
from dcc_mcp_core.skill import skill_entry


@skill_entry
def main(range_mode: str, subjects: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post occlusion fixing completed.",
        lambda: run("fix_occlusion", range_mode, subjects),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from _run import run
from dcc_mcp_core.skill import skill_entry


@skill_entry
def main(range_mode: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post solving completed.",
        lambda: run("solve", range_mode),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

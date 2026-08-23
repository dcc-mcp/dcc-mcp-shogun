from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import run_pipeline_command
from dcc_mcp_shogun.skill_result import safe_result


@skill_entry
def main(**kwargs):
    return safe_result(
        "Vicon Shogun Post pipeline command returned.",
        lambda: run_pipeline_command(**kwargs),
    )


if __name__ == "__main__":
    run_main(main)

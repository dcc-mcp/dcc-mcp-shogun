from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import inspect_processing_settings


@skill_entry
def main(section: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post processing settings inspected.",
        lambda: inspect_processing_settings(section),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

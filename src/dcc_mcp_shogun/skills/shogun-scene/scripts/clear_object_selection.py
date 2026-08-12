from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import clear_object_selection


@skill_entry
def main(**_kwargs):
    return safe_result(
        "Vicon Shogun Post object selection cleared.",
        clear_object_selection,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

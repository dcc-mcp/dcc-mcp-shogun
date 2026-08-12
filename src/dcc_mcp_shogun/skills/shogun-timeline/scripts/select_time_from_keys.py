from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import select_time_from_keys


@skill_entry
def main(**_kwargs):
    return safe_result(
        "Vicon Shogun Post time ranges selected from keys.",
        select_time_from_keys,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

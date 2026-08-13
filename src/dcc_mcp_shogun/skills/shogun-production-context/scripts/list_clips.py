from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_clips


@skill_entry
def main(max_clips: int = 500, **_kwargs):
    return safe_result(
        "Vicon Shogun Post clips inspected.",
        lambda: list_clips(max_clips=max_clips),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

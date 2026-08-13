from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import set_active_clip


@skill_entry
def main(clip_name: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post active clip updated.",
        lambda: set_active_clip(clip_name),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

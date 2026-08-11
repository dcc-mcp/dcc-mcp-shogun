from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import trajectory_at_frame


@skill_entry
def main(subject: str, marker: str, frame: int, **_kwargs):
    return safe_result(
        "Shogun marker trajectory read.", lambda: trajectory_at_frame(subject, marker, frame)
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import trajectory_window


@skill_entry
def main(subject: str, marker: str, start_frame: int, end_frame: int, **_kwargs):
    return safe_result(
        "Shogun marker trajectory window read.",
        lambda: trajectory_window(subject, marker, start_frame, end_frame),
    )


if __name__ == "__main__":
    run_main(main)

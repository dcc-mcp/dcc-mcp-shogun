from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_object_channels


@skill_entry
def main(object_path: str, max_channels: int = 200, **_kwargs):
    return safe_result(
        "Vicon Shogun Post object channels listed.",
        lambda: list_object_channels(object_path, max_channels=max_channels),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

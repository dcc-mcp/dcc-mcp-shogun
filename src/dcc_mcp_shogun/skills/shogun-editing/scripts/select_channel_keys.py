from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import select_channel_keys


@skill_entry
def main(object_path: str, channel_name: str, selection_mode: str, **_kwargs):
    return safe_result(
        "Vicon Shogun Post channel-key selection updated.",
        lambda: select_channel_keys(object_path, channel_name, selection_mode),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

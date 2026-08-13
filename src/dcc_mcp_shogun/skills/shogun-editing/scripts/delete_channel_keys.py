from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import delete_channel_keys


@skill_entry
def main(
    object_path: str,
    channel_name: str,
    delete_mode: str,
    frame: int = None,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post channel keys deleted within the explicit scope.",
        lambda: delete_channel_keys(
            object_path, channel_name, delete_mode=delete_mode, frame=frame
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

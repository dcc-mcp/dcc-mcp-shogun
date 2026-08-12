from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_channel_gaps


@skill_entry
def main(
    object_path: str,
    channel_name: str,
    any_subchannel: bool = False,
    max_gaps: int = 200,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post channel gaps listed.",
        lambda: list_channel_gaps(
            object_path,
            channel_name,
            any_subchannel=any_subchannel,
            max_gaps=max_gaps,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import apply_weighted_average_filter


@skill_entry
def main(
    object_path: str,
    channel_name: str,
    selected_keys_only: bool = True,
    width: int = 3,
    strength: int = 5,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post weighted-average filter applied.",
        lambda: apply_weighted_average_filter(
            object_path,
            channel_name,
            selected_keys_only=selected_keys_only,
            width=width,
            strength=strength,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

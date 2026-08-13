from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import apply_fir_filter


@skill_entry
def main(
    object_path: str,
    channel_name: str,
    selected_keys_only: bool = True,
    length: int = 49,
    transition_width: float = 0.0198,
    light_cutoff: float = 0.3,
    threshold: float = 15.0,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post FIR filter applied.",
        lambda: apply_fir_filter(
            object_path,
            channel_name,
            selected_keys_only=selected_keys_only,
            length=length,
            transition_width=transition_width,
            light_cutoff=light_cutoff,
            threshold=threshold,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

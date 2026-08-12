from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import update_occlusion_settings


@skill_entry
def main(
    enabled=None,
    apply_fixed_markers=None,
    marker_smoothing=None,
    data_fidelity=None,
    transition_time=None,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post occlusion settings updated.",
        lambda: update_occlusion_settings(
            enabled=enabled,
            apply_fixed_markers=apply_fixed_markers,
            marker_smoothing=marker_smoothing,
            data_fidelity=data_fidelity,
            transition_time=transition_time,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

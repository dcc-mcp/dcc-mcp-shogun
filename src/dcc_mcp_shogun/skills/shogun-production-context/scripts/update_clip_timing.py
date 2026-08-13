from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import update_clip_timing


@skill_entry
def main(
    object_path: str,
    locked=None,
    start_frame=None,
    clip_offset=None,
    duration=None,
    time_scale=None,
    smpte_align_clip=None,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post clip timing updated.",
        lambda: update_clip_timing(
            object_path,
            locked=locked,
            start_frame=start_frame,
            clip_offset=clip_offset,
            duration=duration,
            time_scale=time_scale,
            smpte_align_clip=smpte_align_clip,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

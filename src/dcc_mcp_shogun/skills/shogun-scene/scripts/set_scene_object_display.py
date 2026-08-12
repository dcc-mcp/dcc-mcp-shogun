from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import set_scene_object_display


@skill_entry
def main(
    object_path: str,
    showing=None,
    selectable=None,
    opacity=None,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post scene object display updated.",
        lambda: set_scene_object_display(
            object_path,
            showing=showing,
            selectable=selectable,
            opacity=opacity,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

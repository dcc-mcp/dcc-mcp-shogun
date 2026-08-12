from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import select_scene_object


@skill_entry
def main(object_path: str, replace: bool = True, **_kwargs):
    return safe_result(
        "Vicon Shogun Post scene object selected.",
        lambda: select_scene_object(object_path, replace=replace),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

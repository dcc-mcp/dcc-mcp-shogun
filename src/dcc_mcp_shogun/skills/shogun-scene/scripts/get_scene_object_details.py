from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import scene_object_details


@skill_entry
def main(object_path: str, frame: int, max_children: int = 100, **_kwargs):
    return safe_result(
        "Vicon Shogun Post scene object inspected.",
        lambda: scene_object_details(object_path, frame, max_children=max_children),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

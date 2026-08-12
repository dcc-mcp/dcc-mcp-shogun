from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_scene_objects


@skill_entry
def main(max_objects: int = 500, object_type: str = "", **_kwargs):
    return safe_result(
        "Vicon Shogun Post scene objects listed.",
        lambda: list_scene_objects(max_objects=max_objects, object_type=object_type),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import inspect_object_selection


@skill_entry
def main(max_objects: int = 500, **_kwargs):
    return safe_result(
        "Vicon Shogun Post object selection inspected.",
        lambda: inspect_object_selection(max_objects=max_objects),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

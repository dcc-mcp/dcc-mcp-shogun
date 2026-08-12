from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_object_attributes


@skill_entry
def main(object_path: str, max_attributes: int = 200, **_kwargs):
    return safe_result(
        "Vicon Shogun Post object attributes listed.",
        lambda: list_object_attributes(object_path, max_attributes=max_attributes),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_setup_parameters


@skill_entry
def main(
    object_path: str,
    parameter_kind: str = "all",
    max_parameters: int = 500,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post setup parameters listed.",
        lambda: list_setup_parameters(
            object_path=object_path,
            parameter_kind=parameter_kind,
            max_parameters=max_parameters,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

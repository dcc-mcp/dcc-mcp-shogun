from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_character_statuses


@skill_entry
def main(max_characters: int = 500, **_kwargs):
    return safe_result(
        "Vicon Shogun Post character status inspected.",
        lambda: list_character_statuses(max_characters=max_characters),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import update_character_qa_status


@skill_entry
def main(
    object_path: str,
    active=None,
    shot_labeled=None,
    shot_edited=None,
    shot_approved=None,
    shot_attached=None,
    special_flag=None,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post character QA status updated.",
        lambda: update_character_qa_status(
            object_path,
            active=active,
            shot_labeled=shot_labeled,
            shot_edited=shot_edited,
            shot_approved=shot_approved,
            shot_attached=shot_attached,
            special_flag=special_flag,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

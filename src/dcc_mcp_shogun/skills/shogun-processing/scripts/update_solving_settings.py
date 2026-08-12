from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import update_solving_settings


@skill_entry
def main(
    prior_importance=None,
    mean_pose_ratio=None,
    plausibility_importance=None,
    thread_count=None,
    **_kwargs,
):
    return safe_result(
        "Vicon Shogun Post solving settings updated.",
        lambda: update_solving_settings(
            prior_importance=prior_importance,
            mean_pose_ratio=mean_pose_ratio,
            plausibility_importance=plausibility_importance,
            thread_count=thread_count,
        ),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

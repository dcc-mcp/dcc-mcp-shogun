from _result import safe_result
from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import bone_details


@skill_entry
def main(
    subject: str,
    bone: str,
    skeleton: str,
    max_children: int = 1000,
    **_kwargs,
):
    return safe_result(
        "Shogun bone details read.",
        lambda: bone_details(subject, bone, skeleton, max_children),
    )


if __name__ == "__main__":
    run_main(main)

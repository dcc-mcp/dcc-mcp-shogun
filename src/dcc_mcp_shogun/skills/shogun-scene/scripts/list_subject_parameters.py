from _result import safe_result
from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import list_subject_parameters


@skill_entry
def main(subject: str, skeleton: str, max_parameters: int = 1000, **_kwargs):
    return safe_result(
        "Shogun subject parameters listed.",
        lambda: list_subject_parameters(subject, skeleton, max_parameters),
    )


if __name__ == "__main__":
    run_main(main)

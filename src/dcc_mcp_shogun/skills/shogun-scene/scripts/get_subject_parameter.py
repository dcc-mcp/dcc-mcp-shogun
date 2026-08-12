from _result import safe_result
from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import subject_parameter


@skill_entry
def main(subject: str, parameter: str, skeleton: str, **_kwargs):
    return safe_result(
        "Shogun subject parameter read.",
        lambda: subject_parameter(subject, parameter, skeleton),
    )


if __name__ == "__main__":
    run_main(main)

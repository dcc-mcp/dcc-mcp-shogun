from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import list_markers


@skill_entry
def main(subject: str, max_markers: int = 1000, **_kwargs):
    return safe_result("Shogun subject markers listed.", lambda: list_markers(subject, max_markers))


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

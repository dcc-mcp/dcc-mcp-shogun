from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import start_playback


@skill_entry
def main(**_kwargs):
    return safe_result("Vicon Shogun Post playback started.", start_playback)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

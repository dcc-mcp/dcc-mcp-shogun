from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import channel_sample


@skill_entry
def main(object_path: str, channel_name: str, frame: int, **_kwargs):
    return safe_result(
        "Vicon Shogun Post channel sampled.",
        lambda: channel_sample(object_path, channel_name, frame),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

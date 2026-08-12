from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import export_motion
from dcc_mcp_shogun.skill_result import safe_result


@skill_entry
def main(file_path: str, overwrite: bool = False, **_kwargs):
    return safe_result(
        "Shogun motion exported.",
        lambda: export_motion(file_path, overwrite=overwrite),
    )


if __name__ == "__main__":
    run_main(main)

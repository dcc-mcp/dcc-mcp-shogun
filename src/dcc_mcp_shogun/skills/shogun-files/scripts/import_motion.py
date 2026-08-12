from dcc_mcp_core.skill import run_main, skill_entry

from dcc_mcp_shogun.runtime import import_motion
from dcc_mcp_shogun.skill_result import safe_result


@skill_entry
def main(
    file_path: str,
    import_type: str = "selCreateNew",
    create_second_figure: bool = False,
    max_file_bytes: int = 512 * 1024 * 1024,
    **_kwargs,
):
    return safe_result(
        "Shogun motion file imported.",
        lambda: import_motion(
            file_path,
            import_type=import_type,
            create_second_figure=create_second_figure,
            max_file_bytes=max_file_bytes,
        ),
    )


if __name__ == "__main__":
    run_main(main)

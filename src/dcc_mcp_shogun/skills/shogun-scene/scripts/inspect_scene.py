from _result import safe_result
from dcc_mcp_core.skill import skill_entry

from dcc_mcp_shogun.runtime import inspect_scene
from dcc_mcp_shogun.state import publish_scene_snapshot


@skill_entry
def main(max_subjects: int = 100, **_kwargs):
    def operation():
        snapshot = inspect_scene(max_subjects)
        publish_scene_snapshot(snapshot)
        return snapshot

    return safe_result("Vicon Shogun Post scene inspected.", operation)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)

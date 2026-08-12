from dcc_mcp_shogun.runtime import run_processing_step


def run(operation: str, range_mode: str, subjects: str = "active"):
    return run_processing_step(operation, range_mode, subjects)

from dcc_mcp_shogun.state import bind_server, publish_scene_snapshot, unbind_server


class FakeServer:
    def __init__(self):
        self.snapshot = None

    def set_scene_resource(self, snapshot):
        self.snapshot = snapshot


def test_bound_server_receives_scene_resource():
    server = FakeServer()
    snapshot = {"scene_name": "Take01.vdf", "frame_count": 120}
    bind_server(server)
    try:
        assert publish_scene_snapshot(snapshot) is True
        assert server.snapshot == snapshot
    finally:
        unbind_server(server)


def test_unbound_publish_is_a_safe_noop():
    server = FakeServer()
    bind_server(server)
    unbind_server(server)
    assert publish_scene_snapshot({"scene_name": "Take01.vdf"}) is False

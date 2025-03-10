import pytest
import pytest_asyncio

from tests.setup_nodes import setup_daemon
from cryptodoge.daemon.client import connect_to_daemon
from cryptodoge import __version__


@pytest_asyncio.fixture(scope="function")
async def get_daemon(bt):
    async for _ in setup_daemon(btools=bt):
        yield _


class TestDaemonRpc:
    @pytest.mark.asyncio
    async def test_get_version_rpc(self, get_daemon, bt):
        ws_server = get_daemon
        config = bt.config
        client = await connect_to_daemon(config["self_hostname"], config["daemon_port"], bt.get_daemon_ssl_context())
        response = await client.get_version()

        assert response["data"]["success"]
        assert response["data"]["version"] == __version__
        ws_server.stop()

import asyncio

from typing import Optional

from cryptodoge.server.server import CryptodogeServer
from cryptodoge.types.peer_info import PeerInfo
from cryptodoge.util.network import get_host_addr


def start_reconnect_task(server: CryptodogeServer, peer_info_arg: PeerInfo, log, auth: bool, prefer_ipv6: Optional[bool]):
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """
    # If peer_info_arg is already an address, use it, otherwise resolve it here.
    if peer_info_arg.is_valid():
        peer_info = peer_info_arg
    else:
        peer_info = PeerInfo(get_host_addr(peer_info_arg, prefer_ipv6), peer_info_arg.port)

    async def connection_check():
        while True:
            peer_retry = True
            for _, connection in server.all_connections.items():
                if connection.get_peer_info() == peer_info or connection.get_peer_info() == peer_info_arg:
                    peer_retry = False
            if peer_retry:
                log.info(f"Reconnecting to peer {peer_info}")
                try:
                    await server.start_client(peer_info, None, auth=auth)
                except Exception as e:
                    log.info(f"Failed to connect to {peer_info} {e}")
            await asyncio.sleep(3)

    return asyncio.create_task(connection_check())

import asyncio
import logging
from typing import Tuple

import aiohttp
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization

from cryptodoge.protocols.shared_protocol import protocol_version
from cryptodoge.server.outbound_message import NodeType
from cryptodoge.server.server import CryptodogeServer, ssl_context_for_client
from cryptodoge.server.ws_connection import WSCryptodogeConnection
from cryptodoge.ssl.create_ssl import generate_ca_signed_cert
from cryptodoge.types.blockchain_format.sized_bytes import bytes32
from cryptodoge.types.peer_info import PeerInfo
from cryptodoge.util.ints import uint16
from tests.time_out_assert import time_out_assert

log = logging.getLogger(__name__)


async def disconnect_all_and_reconnect(server: CryptodogeServer, reconnect_to: CryptodogeServer, self_hostname: str) -> bool:
    cons = list(server.all_connections.values())[:]
    for con in cons:
        await con.close()
    return await server.start_client(PeerInfo(self_hostname, uint16(reconnect_to._port)), None)


async def add_dummy_connection(
    server: CryptodogeServer, self_hostname: str, dummy_port: int, type: NodeType = NodeType.FULL_NODE
) -> Tuple[asyncio.Queue, bytes32]:
    timeout = aiohttp.ClientTimeout(total=10)
    session = aiohttp.ClientSession(timeout=timeout)
    incoming_queue: asyncio.Queue = asyncio.Queue()
    dummy_crt_path = server._private_key_path.parent / "dummy.crt"
    dummy_key_path = server._private_key_path.parent / "dummy.key"
    generate_ca_signed_cert(
        server.cryptodoge_ca_crt_path.read_bytes(), server.cryptodoge_ca_key_path.read_bytes(), dummy_crt_path, dummy_key_path
    )
    ssl_context = ssl_context_for_client(
        server.cryptodoge_ca_crt_path, server.cryptodoge_ca_key_path, dummy_crt_path, dummy_key_path
    )
    pem_cert = x509.load_pem_x509_certificate(dummy_crt_path.read_bytes(), default_backend())
    der_cert = x509.load_der_x509_certificate(pem_cert.public_bytes(serialization.Encoding.DER), default_backend())
    peer_id = bytes32(der_cert.fingerprint(hashes.SHA256()))
    url = f"wss://{self_hostname}:{server._port}/ws"
    ws = await session.ws_connect(url, autoclose=True, autoping=True, ssl=ssl_context)
    wsc = WSCryptodogeConnection(
        type,
        ws,
        server._port,
        log,
        True,
        False,
        self_hostname,
        incoming_queue,
        lambda x, y: x,
        peer_id,
        100,
        30,
    )
    handshake = await wsc.perform_handshake(server._network_id, protocol_version, dummy_port, NodeType.FULL_NODE)
    assert handshake is True
    return incoming_queue, peer_id


async def connect_and_get_peer(server_1: CryptodogeServer, server_2: CryptodogeServer, self_hostname: str) -> WSCryptodogeConnection:
    """
    Connect server_2 to server_1, and get return the connection in server_1.
    """
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)))

    async def connected():
        for node_id_c, _ in server_1.all_connections.items():
            if node_id_c == server_2.node_id:
                return True
        return False

    await time_out_assert(10, connected, True)
    for node_id, wsc in server_1.all_connections.items():
        if node_id == server_2.node_id:
            return wsc
    assert False

import dataclasses
import logging
from time import time

from typing import Dict, List, Optional, Tuple, Callable

from clvm.casts import int_to_bytes
import pytest
import pytest_asyncio

import cryptodoge.server.ws_connection as ws

from cryptodoge.full_node.mempool import Mempool
from cryptodoge.full_node.full_node_api import FullNodeAPI
from cryptodoge.protocols import full_node_protocol, wallet_protocol
from cryptodoge.protocols.wallet_protocol import TransactionAck
from cryptodoge.server.outbound_message import Message
from cryptodoge.simulator.simulator_protocol import FarmNewBlockProtocol
from cryptodoge.types.announcement import Announcement
from cryptodoge.types.blockchain_format.coin import Coin
from cryptodoge.types.blockchain_format.sized_bytes import bytes32
from cryptodoge.types.coin_spend import CoinSpend
from cryptodoge.types.condition_opcodes import ConditionOpcode
from cryptodoge.types.condition_with_args import ConditionWithArgs
from cryptodoge.types.spend_bundle import SpendBundle
from cryptodoge.types.mempool_item import MempoolItem
from cryptodoge.util.condition_tools import conditions_for_solution, pkm_pairs
from cryptodoge.util.errors import Err
from cryptodoge.util.ints import uint64, uint32
from cryptodoge.util.hash import std_hash
from cryptodoge.types.mempool_inclusion_status import MempoolInclusionStatus
from cryptodoge.util.api_decorators import api_request, peer_required, bytes_required
from cryptodoge.full_node.mempool_check_conditions import get_name_puzzle_conditions
from cryptodoge.types.name_puzzle_condition import NPC
from cryptodoge.full_node.pending_tx_cache import PendingTxCache
from blspy import G2Element

from cryptodoge.util.recursive_replace import recursive_replace
from tests.blockchain.blockchain_test_utils import _validate_and_add_block
from tests.connection_utils import connect_and_get_peer
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from cryptodoge.types.blockchain_format.program import Program, INFINITE_COST
from cryptodoge.consensus.cost_calculator import NPCResult
from cryptodoge.consensus.condition_costs import ConditionCost
from cryptodoge.types.blockchain_format.program import SerializedProgram
from clvm_tools import binutils
from cryptodoge.types.generator_types import BlockGenerator
from clvm.casts import int_from_bytes
from blspy import G1Element

from tests.wallet_tools import WalletTool

BURN_PUZZLE_HASH = bytes32(b"0" * 32)
BURN_PUZZLE_HASH_2 = bytes32(b"1" * 32)


@pytest.fixture(scope="module")
def wallet_a(bt):
    return bt.get_pool_wallet_tool()


log = logging.getLogger(__name__)


def generate_test_spend_bundle(
    wallet_a: WalletTool,
    coin: Coin,
    condition_dic: Dict[ConditionOpcode, List[ConditionWithArgs]] = None,
    fee: uint64 = uint64(0),
    amount: uint64 = uint64(1000),
    new_puzzle_hash=BURN_PUZZLE_HASH,
) -> SpendBundle:
    if condition_dic is None:
        condition_dic = {}
    transaction = wallet_a.generate_signed_transaction(amount, new_puzzle_hash, coin, condition_dic, fee)
    assert transaction is not None
    return transaction


@pytest_asyncio.fixture(scope="module")
async def two_nodes(bt, wallet_a):
    async_gen = setup_simulators_and_wallets(2, 1, {})
    nodes, _ = await async_gen.__anext__()
    full_node_1 = nodes[0]
    full_node_2 = nodes[1]
    server_1 = full_node_1.full_node.server
    server_2 = full_node_2.full_node.server

    reward_ph = wallet_a.get_new_puzzlehash()
    blocks = bt.get_consecutive_blocks(
        3,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
    )

    for block in blocks:
        await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

    await time_out_assert(60, node_height_at_least, True, full_node_1, blocks[-1].height)

    yield full_node_1, full_node_2, server_1, server_2

    async for _ in async_gen:
        yield _


def make_item(idx: int, cost: uint64 = uint64(80)) -> MempoolItem:
    spend_bundle_name = bytes([idx] * 32)
    # TODO: address hint error and remove ignore
    #       error: Argument 5 to "MempoolItem" has incompatible type "bytes"; expected "bytes32"  [arg-type]
    return MempoolItem(
        SpendBundle([], G2Element()),
        uint64(0),
        NPCResult(None, [], cost),
        cost,
        spend_bundle_name,  # type: ignore[arg-type]
        [],
        [],
        SerializedProgram(),
    )


class TestPendingTxCache:
    def test_recall(self):
        c = PendingTxCache(100)
        item = make_item(1)
        c.add(item)
        tx = c.drain()
        assert tx == {item.spend_bundle_name: item}

    def test_fifo_limit(self):
        c = PendingTxCache(200)
        # each item has cost 80
        items = [make_item(i) for i in range(1, 4)]
        for i in items:
            c.add(i)
        # the max cost is 200, only two transactions will fit
        # we evict items FIFO, so the to most recently added will be left
        tx = c.drain()
        assert tx == {items[-2].spend_bundle_name: items[-2], items[-1].spend_bundle_name: items[-1]}

    def test_drain(self):
        c = PendingTxCache(100)
        item = make_item(1)
        c.add(item)
        tx = c.drain()
        assert tx == {item.spend_bundle_name: item}

        # drain will clear the cache, so a second call will be empty
        tx = c.drain()
        assert tx == {}

    def test_cost(self):
        c = PendingTxCache(200)
        assert c.cost() == 0
        item1 = make_item(1)
        c.add(item1)
        # each item has cost 80
        assert c.cost() == 80

        item2 = make_item(2)
        c.add(item2)
        assert c.cost() == 160

        # the first item is evicted, so the cost stays the same
        item3 = make_item(3)
        c.add(item3)
        assert c.cost() == 160

        tx = c.drain()
        assert tx == {item2.spend_bundle_name: item2, item3.spend_bundle_name: item3}

        assert c.cost() == 0
        item4 = make_item(4)
        c.add(item4)
        assert c.cost() == 80

        tx = c.drain()
        assert tx == {item4.spend_bundle_name: item4}


class TestMempool:
    @pytest.mark.asyncio
    async def test_basic_mempool(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        max_mempool_cost = 40000000 * 5
        mempool = Mempool(max_mempool_cost)
        assert mempool.get_min_fee_rate(104000) == 0

        with pytest.raises(ValueError):
            mempool.get_min_fee_rate(max_mempool_cost + 1)

        coin = await next_block(full_node_1, wallet_a, bt)
        spend_bundle = generate_test_spend_bundle(wallet_a, coin)
        assert spend_bundle is not None


@peer_required
@api_request
@bytes_required
async def respond_transaction(
    node: FullNodeAPI,
    tx: full_node_protocol.RespondTransaction,
    peer: ws.WSCryptodogeConnection,
    tx_bytes: bytes = b"",
    test: bool = False,
) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
    """
    Receives a full transaction from peer.
    If tx is added to mempool, send tx_id to others. (new_transaction)
    """
    assert tx_bytes != b""
    spend_name = std_hash(tx_bytes)
    if spend_name in node.full_node.full_node_store.pending_tx_request:
        node.full_node.full_node_store.pending_tx_request.pop(spend_name)
    if spend_name in node.full_node.full_node_store.peers_with_tx:
        node.full_node.full_node_store.peers_with_tx.pop(spend_name)
    return await node.full_node.respond_transaction(tx.transaction, spend_name, peer, test)


async def next_block(full_node_1, wallet_a, bt) -> Coin:
    blocks = await full_node_1.get_all_full_blocks()
    # we have to farm a new block here, to ensure every test has a unique coin to test spending.
    # all this could be simplified if the tests did not share a simulation
    start_height = blocks[-1].height
    reward_ph = wallet_a.get_new_puzzlehash()
    blocks = bt.get_consecutive_blocks(
        1,
        block_list_input=blocks,
        guarantee_transaction_block=True,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
    )

    for block in blocks:
        await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

    await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 1)
    return list(blocks[-1].get_included_reward_coins())[0]


class TestMempoolManager:
    @pytest.mark.asyncio
    async def test_basic_mempool_manager(self, bt, two_nodes, wallet_a, self_hostname):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        coin = await next_block(full_node_1, wallet_a, bt)
        spend_bundle = generate_test_spend_bundle(wallet_a, coin)
        assert spend_bundle is not None
        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        await full_node_1.respond_transaction(tx, peer)

        await time_out_assert(
            10,
            full_node_1.full_node.mempool_manager.get_spendbundle,
            spend_bundle,
            spend_bundle.name(),
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "opcode,lock_value,expected",
        [
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, -2, MempoolInclusionStatus.SUCCESS),
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, -1, MempoolInclusionStatus.SUCCESS),
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, 0, MempoolInclusionStatus.SUCCESS),
            (ConditionOpcode.ASSERT_SECONDS_RELATIVE, 1, MempoolInclusionStatus.FAILED),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, -2, MempoolInclusionStatus.SUCCESS),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, -1, MempoolInclusionStatus.SUCCESS),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, 0, MempoolInclusionStatus.PENDING),
            (ConditionOpcode.ASSERT_HEIGHT_RELATIVE, 1, MempoolInclusionStatus.PENDING),
            # the absolute height and seconds tests require fresh full nodes to
            # run the test on. Right now, we just launch two simulations and all
            # tests use the same ones. See comment at the two_nodes fixture
            # (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 2, MempoolInclusionStatus.SUCCESS),
            # (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 3, MempoolInclusionStatus.SUCCESS),
            # (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 4, MempoolInclusionStatus.PENDING),
            # (ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, 5, MempoolInclusionStatus.PENDING),
            # genesis timestamp is 10000 and each block is 10 seconds
            # (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10029, MempoolInclusionStatus.SUCCESS),
            # (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10030, MempoolInclusionStatus.SUCCESS),
            # (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10031, MempoolInclusionStatus.FAILED),
            # (ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, 10032, MempoolInclusionStatus.FAILED),
        ],
    )
    async def test_ephemeral_timelock(self, bt, two_nodes, wallet_a, opcode, lock_value, expected):
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:

            conditions = {opcode: [ConditionWithArgs(opcode, [int_to_bytes(lock_value)])]}
            tx1 = wallet_a.generate_signed_transaction(
                uint64(1000000), wallet_a.get_new_puzzlehash(), coin_2, conditions.copy(), uint64(0)
            )

            ephemeral_coin: Coin = tx1.additions()[0]
            tx2 = wallet_a.generate_signed_transaction(
                uint64(1000000), wallet_a.get_new_puzzlehash(), ephemeral_coin, conditions.copy(), uint64(0)
            )

            bundle = SpendBundle.aggregate([tx1, tx2])
            return bundle

        full_node_1, _, server_1, _ = two_nodes
        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        print(f"status: {status}")
        print(f"error: {err}")

        assert status == expected
        if expected == MempoolInclusionStatus.SUCCESS:
            assert mempool_bundle is bundle
            assert err is None
        else:
            assert mempool_bundle is None
            assert err is not None

    # this test makes sure that one spend successfully asserts the announce from
    # another spend, even though the assert condition is duplicated 100 times
    @pytest.mark.asyncio
    async def test_coin_announcement_duplicate_consumed(self, bt, two_nodes, wallet_a):
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = Announcement(coin_2.name(), b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp] * 100}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS

    # this test makes sure that one spend successfully asserts the announce from
    # another spend, even though the create announcement is duplicated 100 times
    @pytest.mark.asyncio
    async def test_coin_duplicate_announcement_consumed(self, bt, two_nodes, wallet_a):
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = Announcement(coin_2.name(), b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2] * 100}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_double_spend(self, bt, two_nodes, wallet_a, self_hostname):
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        spend_bundle1 = generate_test_spend_bundle(wallet_a, list(blocks[-1].get_included_reward_coins())[0])

        assert spend_bundle1 is not None
        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)
        status, err = await respond_transaction(full_node_1, tx1, peer)
        assert err is None
        assert status == MempoolInclusionStatus.SUCCESS

        spend_bundle2 = generate_test_spend_bundle(
            wallet_a,
            list(blocks[-1].get_included_reward_coins())[0],
            new_puzzle_hash=BURN_PUZZLE_HASH_2,
        )
        assert spend_bundle2 is not None
        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle2)
        status, err = await respond_transaction(full_node_1, tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        sb2 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle2.name())

        assert err == Err.MEMPOOL_CONFLICT
        assert sb1 == spend_bundle1
        assert sb2 is None
        assert status == MempoolInclusionStatus.PENDING

    async def send_sb(self, node: FullNodeAPI, sb: SpendBundle) -> Optional[Message]:
        tx = wallet_protocol.SendTransaction(sb)
        return await node.send_transaction(tx)

    async def gen_and_send_sb(self, node, peer, *args, **kwargs):
        sb = generate_test_spend_bundle(*args, **kwargs)
        assert sb is not None

        await self.send_sb(node, sb)
        return sb

    def assert_sb_in_pool(self, node, sb):
        assert sb == node.full_node.mempool_manager.get_spendbundle(sb.name())

    def assert_sb_not_in_pool(self, node, sb):
        assert node.full_node.mempool_manager.get_spendbundle(sb.name()) is None

    @pytest.mark.asyncio
    async def test_double_spend_with_higher_fee(self, bt, two_nodes, wallet_a, self_hostname):
        reward_ph = wallet_a.get_new_puzzlehash()

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height if len(blocks) > 0 else -1
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2, self_hostname)

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coins = iter(blocks[-1].get_included_reward_coins())
        coin1, coin2 = next(coins), next(coins)
        coins = iter(blocks[-2].get_included_reward_coins())
        coin3, coin4 = next(coins), next(coins)

        sb1_1 = await self.gen_and_send_sb(full_node_1, peer, wallet_a, coin1)
        sb1_2 = await self.gen_and_send_sb(full_node_1, peer, wallet_a, coin1, fee=uint64(1))

        # Fee increase is insufficient, the old spendbundle must stay
        self.assert_sb_in_pool(full_node_1, sb1_1)
        self.assert_sb_not_in_pool(full_node_1, sb1_2)

        min_fee_increase = full_node_1.full_node.mempool_manager.get_min_fee_increase()

        sb1_3 = await self.gen_and_send_sb(full_node_1, peer, wallet_a, coin1, fee=uint64(min_fee_increase))

        # Fee increase is sufficiently high, sb1_1 gets replaced with sb1_3
        self.assert_sb_not_in_pool(full_node_1, sb1_1)
        self.assert_sb_in_pool(full_node_1, sb1_3)

        sb2 = generate_test_spend_bundle(wallet_a, coin2, fee=uint64(min_fee_increase))
        sb12 = SpendBundle.aggregate((sb2, sb1_3))
        await self.send_sb(full_node_1, sb12)

        # Aggregated spendbundle sb12 replaces sb1_3 since it spends a superset
        # of coins spent in sb1_3
        self.assert_sb_in_pool(full_node_1, sb12)
        self.assert_sb_not_in_pool(full_node_1, sb1_3)

        sb3 = generate_test_spend_bundle(wallet_a, coin3, fee=uint64(min_fee_increase * 2))
        sb23 = SpendBundle.aggregate((sb2, sb3))
        await self.send_sb(full_node_1, sb23)

        # sb23 must not replace existing sb12 as the former does not spend all
        # coins that are spent in the latter (specifically, coin1)
        self.assert_sb_in_pool(full_node_1, sb12)
        self.assert_sb_not_in_pool(full_node_1, sb23)

        await self.send_sb(full_node_1, sb3)
        # Adding non-conflicting sb3 should succeed
        self.assert_sb_in_pool(full_node_1, sb3)

        sb4_1 = generate_test_spend_bundle(wallet_a, coin4, fee=uint64(min_fee_increase))
        sb1234_1 = SpendBundle.aggregate((sb12, sb3, sb4_1))
        await self.send_sb(full_node_1, sb1234_1)
        # sb1234_1 should not be in pool as it decreases total fees per cost
        self.assert_sb_not_in_pool(full_node_1, sb1234_1)

        sb4_2 = generate_test_spend_bundle(wallet_a, coin4, fee=uint64(min_fee_increase * 2))
        sb1234_2 = SpendBundle.aggregate((sb12, sb3, sb4_2))
        await self.send_sb(full_node_1, sb1234_2)
        # sb1234_2 has a higher fee per cost than its conflicts and should get
        # into mempool
        self.assert_sb_in_pool(full_node_1, sb1234_2)
        self.assert_sb_not_in_pool(full_node_1, sb12)
        self.assert_sb_not_in_pool(full_node_1, sb3)

    @pytest.mark.asyncio
    async def test_invalid_signature(self, bt, two_nodes, wallet_a):
        reward_ph = wallet_a.get_new_puzzlehash()

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height if len(blocks) > 0 else -1
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))
        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coins = iter(blocks[-1].get_included_reward_coins())
        coin1 = next(coins)
        coins = iter(blocks[-2].get_included_reward_coins())

        sb: SpendBundle = generate_test_spend_bundle(wallet_a, coin1)
        assert sb.aggregated_signature != G2Element.generator()
        sb = dataclasses.replace(sb, aggregated_signature=G2Element.generator())
        res: Optional[Message] = await self.send_sb(full_node_1, sb)
        assert res is not None
        ack: TransactionAck = TransactionAck.from_bytes(res.data)
        assert ack.status == MempoolInclusionStatus.FAILED.value
        assert ack.error == Err.BAD_AGGREGATE_SIGNATURE.name

    async def condition_tester(
        self,
        bt,
        two_nodes,
        wallet_a,
        dic: Dict[ConditionOpcode, List[ConditionWithArgs]],
        fee: int = 0,
        num_blocks: int = 3,
        coin: Optional[Coin] = None,
    ):
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            num_blocks,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2, bt.config["self_hostname"])

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + num_blocks)

        spend_bundle1 = generate_test_spend_bundle(
            wallet_a, coin or list(blocks[-num_blocks + 2].get_included_reward_coins())[0], dic, uint64(fee)
        )

        assert spend_bundle1 is not None

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx1, peer)
        return blocks, spend_bundle1, peer, status, err

    @pytest.mark.asyncio
    async def condition_tester2(self, bt, two_nodes, wallet_a, test_fun: Callable[[Coin, Coin], SpendBundle]):
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height if len(blocks) > 0 else -1
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2, bt.config["self_hostname"])

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin_1 = list(blocks[-2].get_included_reward_coins())[0]
        coin_2 = list(blocks[-1].get_included_reward_coins())[0]

        bundle = test_fun(coin_1, coin_2)

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(bundle)
        status, err = await respond_transaction(full_node_1, tx1, peer, test=True)

        return blocks, bundle, status, err

    @pytest.mark.asyncio
    async def test_invalid_block_index(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        cvp = ConditionWithArgs(
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            [int_to_bytes(start_height + 5)],
        )
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert err == Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
        assert status == MempoolInclusionStatus.PENDING

    @pytest.mark.asyncio
    async def test_block_index_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert sb1 is None
        # the transaction may become valid later
        assert err == Err.INVALID_CONDITION
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_correct_block_index(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(1)])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_block_index_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(1), b"garbage"])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_negative_block_index(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(-1)])
        dic = {ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_invalid_block_age(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(5)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_HEIGHT_RELATIVE_FAILED
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.PENDING

    @pytest.mark.asyncio
    async def test_block_age_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        # the transaction may become valid later
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_correct_block_age(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            bt, two_nodes, wallet_a, dic, num_blocks=4
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_block_age_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(1), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            bt, two_nodes, wallet_a, dic, num_blocks=4
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_negative_block_age(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_RELATIVE, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(
            bt, two_nodes, wallet_a, dic, num_blocks=4
        )

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_correct_my_id(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin.name()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_my_id_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin.name(), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_invalid_my_id(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        coin_2 = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [coin_2.name()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_MY_COIN_ID_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_my_id_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_COIN_ID, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_assert_time_exceeds(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # 5 seconds should be before the next block
        time_now = full_node_1.full_node.blockchain.get_peak().timestamp + 5

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_assert_time_fail(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_now = full_node_1.full_node.blockchain.get_peak().timestamp + 1000

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_SECONDS_ABSOLUTE_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_assert_height_pending(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        print(full_node_1.full_node.blockchain.get_peak())
        current_height = full_node_1.full_node.blockchain.get_peak().height

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE, [int_to_bytes(current_height + 4)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.PENDING

    @pytest.mark.asyncio
    async def test_assert_time_negative(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_now = -1

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_assert_time_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_assert_time_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_now = full_node_1.full_node.blockchain.get_peak().timestamp + 5

        # garbage at the end of the argument list is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_ABSOLUTE, [int_to_bytes(time_now), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)
        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_assert_time_relative_exceeds(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_relative = 3

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.ASSERT_SECONDS_RELATIVE_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

        for i in range(0, 4):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        tx2: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx2, peer)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_assert_time_relative_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_relative = 0

        # garbage at the end of the arguments is ignored
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_assert_time_relative_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_assert_time_relative_negative(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        time_relative = -3

        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_SECONDS_RELATIVE, [int_to_bytes(time_relative)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())
        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    # ensure one spend can assert a coin announcement from another spend
    @pytest.mark.asyncio
    async def test_correct_coin_announcement_consumed(self, bt, two_nodes, wallet_a):
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = Announcement(coin_2.name(), b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS

    # ensure one spend can assert a coin announcement from another spend, even
    # though the conditions have garbage (ignored) at the end
    @pytest.mark.asyncio
    async def test_coin_announcement_garbage(self, bt, two_nodes, wallet_a):
        def test_fun(coin_1: Coin, coin_2: Coin) -> SpendBundle:
            announce = Announcement(coin_2.name(), b"test")
            # garbage at the end is ignored
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name(), b"garbage"])
            dic = {cvp.opcode: [cvp]}

            # garbage at the end is ignored
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test", b"garbage"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)
            bundle = SpendBundle.aggregate([spend_bundle1, spend_bundle2])
            return bundle

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_coin_announcement_missing_arg(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            # missing arg here
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [])
            dic = {cvp.opcode: [cvp]}
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        assert err == Err.INVALID_CONDITION
        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_coin_announcement_missing_arg2(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.name(), b"test")
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp]}
            # missing arg here
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        assert err == Err.INVALID_CONDITION
        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_coin_announcement_too_big(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.name(), bytes([1] * 10000))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name()) is None
        assert status == MempoolInclusionStatus.FAILED

        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=bundle
        )
        try:
            await _validate_and_add_block(full_node_1.full_node.blockchain, blocks[-1])
            assert False
        except AssertionError as e:
            assert e.args[0] == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED

    # ensure an assert coin announcement is rejected if it doesn't match the
    # create announcement
    @pytest.mark.asyncio
    async def test_invalid_coin_announcement_rejected(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.name(), b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}
            # mismatching message
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
                [b"wrong test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_coin_announcement_rejected_two(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_1.name(), b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [b"test"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            # coin 2 is making the announcement, right message wrong coin
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_correct_puzzle_announcement(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, bytes(0x80))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [bytes(0x80)])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_puzzle_announcement_garbage(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, bytes(0x80))

            # garbage at the end is ignored
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name(), b"garbage"])
            dic = {cvp.opcode: [cvp]}
            # garbage at the end is ignored
            cvp2 = ConditionWithArgs(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [bytes(0x80), b"garbage"])
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err is None
        assert mempool_bundle is bundle
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_puzzle_announcement_missing_arg(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            # missing arg here
            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [])
            dic = {cvp.opcode: [cvp]}
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [b"test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.INVALID_CONDITION
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_puzzle_announcement_missing_arg2(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])
            dic = {cvp.opcode: [cvp]}
            # missing arg here
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.INVALID_CONDITION
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement_rejected(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, bytes("test", "utf-8"))

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}

            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
                [b"wrong test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_puzzle_announcement_rejected_two(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        def test_fun(coin_1: Coin, coin_2: Coin):
            announce = Announcement(coin_2.puzzle_hash, b"test")

            cvp = ConditionWithArgs(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [announce.name()])

            dic = {cvp.opcode: [cvp]}
            # Wrong type of Create_announcement
            cvp2 = ConditionWithArgs(
                ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
                [b"test"],
            )
            dic2 = {cvp.opcode: [cvp2]}
            spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic)
            spend_bundle2 = generate_test_spend_bundle(wallet_a, coin_2, dic2)

            return SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        blocks, bundle, status, err = await self.condition_tester2(bt, two_nodes, wallet_a, test_fun)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(bundle.name())

        assert err == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_assert_fee_condition(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, fee=10)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert mempool_bundle is not None
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_assert_fee_condition_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        # garbage at the end of the arguments is ignored
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, fee=10)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert mempool_bundle is not None
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_assert_fee_condition_missing_arg(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, fee=10)
        assert err == Err.INVALID_CONDITION
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_assert_fee_condition_negative_fee(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, fee=10)
        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert status == MempoolInclusionStatus.FAILED
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle1
        )
        assert full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name()) is None
        await _validate_and_add_block(
            full_node_1.full_node.blockchain, blocks[-1], expected_error=Err.RESERVE_FEE_CONDITION_FAILED
        )

    @pytest.mark.asyncio
    async def test_assert_fee_condition_fee_too_large(self, bt, two_nodes, wallet_a):
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(2 ** 64)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, fee=10)
        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert status == MempoolInclusionStatus.FAILED
        blocks = bt.get_consecutive_blocks(
            1, block_list_input=blocks, guarantee_transaction_block=True, transaction_data=spend_bundle1
        )
        assert full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name()) is None
        await _validate_and_add_block(
            full_node_1.full_node.blockchain, blocks[-1], expected_error=Err.RESERVE_FEE_CONDITION_FAILED
        )

    @pytest.mark.asyncio
    async def test_assert_fee_condition_wrong_fee(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, fee=9)
        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_stealing_fee(self, bt, two_nodes, wallet_a):
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            5,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        peer = await connect_and_get_peer(server_1, server_2, bt.config["self_hostname"])

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 5)

        receiver_puzzlehash = BURN_PUZZLE_HASH

        cvp = ConditionWithArgs(ConditionOpcode.RESERVE_FEE, [int_to_bytes(10)])
        dic = {cvp.opcode: [cvp]}

        fee = 9

        coin_1 = list(blocks[-2].get_included_reward_coins())[0]
        coin_2 = None
        for coin in list(blocks[-1].get_included_reward_coins()):
            if coin.amount == coin_1.amount:
                coin_2 = coin
        spend_bundle1 = generate_test_spend_bundle(wallet_a, coin_1, dic, uint64(fee))

        steal_fee_spendbundle = wallet_a.generate_signed_transaction(
            uint64(coin_1.amount + fee - 4), receiver_puzzlehash, coin_2
        )

        assert spend_bundle1 is not None
        assert steal_fee_spendbundle is not None

        combined = SpendBundle.aggregate([spend_bundle1, steal_fee_spendbundle])

        assert combined.fees() == 4

        tx1: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle1)

        status, err = await respond_transaction(full_node_1, tx1, peer)

        mempool_bundle = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.RESERVE_FEE_CONDITION_FAILED
        assert mempool_bundle is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_double_spend_same_bundle(self, bt, two_nodes, wallet_a):
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        peer = await connect_and_get_peer(server_1, server_2, bt.config["self_hostname"])

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)
        # coin = list(blocks[-1].get_included_reward_coins())[0]
        # spend_bundle1 = generate_test_spend_bundle(wallet_a, coin)
        coin = await next_block(full_node_1, wallet_a, bt)
        spend_bundle1 = generate_test_spend_bundle(wallet_a, coin)

        assert spend_bundle1 is not None

        spend_bundle2 = generate_test_spend_bundle(
            wallet_a,
            coin,
            new_puzzle_hash=BURN_PUZZLE_HASH_2,
        )

        assert spend_bundle2 is not None

        spend_bundle_combined = SpendBundle.aggregate([spend_bundle1, spend_bundle2])

        tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle_combined)

        peer = await connect_and_get_peer(server_1, server_2, bt.config["self_hostname"])
        status, err = await respond_transaction(full_node_1, tx, peer)

        sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle_combined.name())
        assert err == Err.DOUBLE_SPEND
        assert sb is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_agg_sig_condition(self, bt, two_nodes, wallet_a):
        reward_ph = wallet_a.get_new_puzzlehash()
        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        start_height = blocks[-1].height
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, start_height + 3)

        coin = await next_block(full_node_1, wallet_a, bt)
        # coin = list(blocks[-1].get_included_reward_coins())[0]
        spend_bundle_0 = generate_test_spend_bundle(wallet_a, coin)
        unsigned: List[CoinSpend] = spend_bundle_0.coin_spends

        assert len(unsigned) == 1
        coin_spend: CoinSpend = unsigned[0]

        err, con, cost = conditions_for_solution(coin_spend.puzzle_reveal, coin_spend.solution, INFINITE_COST)
        assert con is not None

        # TODO(straya): fix this test
        # puzzle, solution = list(coin_spend.solution.as_iter())
        # conditions_dict = conditions_by_opcode(con)

        # pkm_pairs = pkm_pairs_for_conditions_dict(conditions_dict, coin_spend.coin.name())
        # assert len(pkm_pairs) == 1
        #
        # assert pkm_pairs[0][1] == solution.rest().first().get_tree_hash() + coin_spend.coin.name()
        #
        # spend_bundle = wallet_a.sign_transaction(unsigned)
        # assert spend_bundle is not None
        #
        # tx: full_node_protocol.RespondTransaction = full_node_protocol.RespondTransaction(spend_bundle)
        # await full_node_1.respond_transaction(tx, peer)
        #
        # sb = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle.name())
        # assert sb is spend_bundle

    @pytest.mark.asyncio
    async def test_correct_my_parent(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin.parent_coin_info])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_my_parent_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the arguments list is allowed but stripped
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin.parent_coin_info, b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_my_parent_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_my_parent(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        coin_2 = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PARENT_ID, [coin_2.parent_coin_info])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_PARENT_ID_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_correct_my_puzhash(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [coin.puzzle_hash])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_my_puzhash_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the arguments list is allowed but stripped
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [coin.puzzle_hash, b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_my_puzhash_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_my_puzhash(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_PUZZLEHASH, [Program.to([]).get_tree_hash()])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_PUZZLEHASH_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_correct_my_amount(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(coin.amount)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_my_amount_garbage(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        coin = await next_block(full_node_1, wallet_a, bt)
        # garbage at the end of the arguments list is allowed but stripped
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(coin.amount), b"garbage"])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic, coin=coin)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err is None
        assert sb1 is spend_bundle1
        assert status == MempoolInclusionStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_my_amount_missing_arg(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.INVALID_CONDITION
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_invalid_my_amount(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(1000)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_AMOUNT_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_negative_my_amount(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(-1)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_AMOUNT_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED

    @pytest.mark.asyncio
    async def test_my_amount_too_large(self, bt, two_nodes, wallet_a):

        full_node_1, full_node_2, server_1, server_2 = two_nodes
        blocks = await full_node_1.get_all_full_blocks()
        cvp = ConditionWithArgs(ConditionOpcode.ASSERT_MY_AMOUNT, [int_to_bytes(2 ** 64)])
        dic = {cvp.opcode: [cvp]}
        blocks, spend_bundle1, peer, status, err = await self.condition_tester(bt, two_nodes, wallet_a, dic)

        sb1 = full_node_1.full_node.mempool_manager.get_spendbundle(spend_bundle1.name())

        assert err == Err.ASSERT_MY_AMOUNT_FAILED
        assert sb1 is None
        assert status == MempoolInclusionStatus.FAILED


# the following tests generate generator programs and run them through get_name_puzzle_conditions()

COST_PER_BYTE = 12000
MAX_BLOCK_COST_CLVM = 11000000000


def generator_condition_tester(
    conditions: str,
    *,
    mempool_mode: bool = False,
    quote: bool = True,
    max_cost: int = MAX_BLOCK_COST_CLVM,
    height: uint32,
) -> NPCResult:
    prg = f"(q ((0x0101010101010101010101010101010101010101010101010101010101010101 {'(q ' if quote else ''} {conditions} {')' if quote else ''} 123 (() (q . ())))))"  # noqa
    print(f"program: {prg}")
    program = SerializedProgram.from_bytes(binutils.assemble(prg).as_bin())
    generator = BlockGenerator(program, [], [])
    print(f"len: {len(bytes(program))}")
    npc_result: NPCResult = get_name_puzzle_conditions(
        generator, max_cost, cost_per_byte=COST_PER_BYTE, mempool_mode=mempool_mode, height=height
    )
    return npc_result


class TestGeneratorConditions:
    def test_invalid_condition_args_terminator(self, softfork_height):

        # note how the condition argument list isn't correctly terminated with a
        # NIL atom. This is allowed, and all arguments beyond the ones we look
        # at are ignored, including the termination of the list
        npc_result = generator_condition_tester("(80 50 . 1)", height=softfork_height)
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        opcode = ConditionOpcode(bytes([80]))
        assert len(npc_result.npc_list[0].conditions) == 1
        assert npc_result.npc_list[0].conditions[0][0] == opcode
        assert len(npc_result.npc_list[0].conditions[0][1]) == 1
        c = npc_result.npc_list[0].conditions[0][1][0]
        assert c == ConditionWithArgs(opcode=ConditionOpcode.ASSERT_SECONDS_RELATIVE, vars=[bytes([50])])

    @pytest.mark.parametrize(
        "mempool,height,operand,expected",
        [
            (True, 0, -1, Err.GENERATOR_RUNTIME_ERROR.value),
            (False, 1000000, -1, None),
            (False, 2300000, -1, Err.GENERATOR_RUNTIME_ERROR.value),
            (True, 0, 1, None),
            (False, 1000000, 1, None),
            (False, 2300000, 1, None),
        ],
    )
    def test_div(self, mempool, height: uint32, operand, expected):

        # op_div is disallowed on negative numbers in the mempool, and after the
        # softfork
        npc_result = generator_condition_tester(
            f"(c (c (q . 80) (c (/ (q . 50) (q . {operand})) ())) ())", quote=False, mempool_mode=mempool, height=height
        )
        assert npc_result.error == expected

    def test_invalid_condition_list_terminator(self, softfork_height):

        # note how the list of conditions isn't correctly terminated with a
        # NIL atom. This is a failure
        npc_result = generator_condition_tester("(80 50) . 3", height=softfork_height)
        assert npc_result.error in [Err.INVALID_CONDITION.value, Err.GENERATOR_RUNTIME_ERROR.value]

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_height_time_conditions(self, opcode, softfork_height):
        # even though the generator outputs multiple conditions, we only
        # need to return the highest one (i.e. most strict)
        npc_result = generator_condition_tester(
            " ".join([f"({opcode.value[0]} {i})" for i in range(50, 101)]), height=softfork_height
        )
        print(npc_result)
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        max_arg = 0
        assert npc_result.npc_list[0].conditions[0][0] == opcode
        for c in npc_result.npc_list[0].conditions[0][1]:
            assert c.opcode == opcode
            max_arg = max(max_arg, int_from_bytes(c.vars[0]))
        assert max_arg == 100

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.CREATE_COIN_ANNOUNCEMENT,
            ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT,
        ],
    )
    def test_just_announcement(self, opcode, softfork_height):
        message = "a" * 1024
        # announcements are validated on the Rust side and never returned
        # back. They are either satisified or cause an immediate failure
        npc_result = generator_condition_tester(f'({opcode.value[0]} "{message}") ' * 50, height=softfork_height)
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        # create-announcements and assert-announcements are dropped once
        # validated
        assert npc_result.npc_list[0].conditions == []

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
            ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
        ],
    )
    def test_assert_announcement_fail(self, opcode, softfork_height):
        message = "a" * 1024
        # announcements are validated on the Rust side and never returned
        # back. They ar either satisified or cause an immediate failure
        # in this test we just assert announcements, we never make them, so
        # these should fail
        npc_result = generator_condition_tester(f'({opcode.value[0]} "{message}") ', height=softfork_height)
        print(npc_result)
        assert npc_result.error == Err.ASSERT_ANNOUNCE_CONSUMED_FAILED.value
        assert npc_result.npc_list == []

    def test_multiple_reserve_fee(self, softfork_height):
        # RESERVE_FEE
        cond = 52
        # even though the generator outputs 3 conditions, we only need to return one copy
        # with all the fees accumulated
        npc_result = generator_condition_tester(f"({cond} 100) " * 3, height=softfork_height)
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        opcode = ConditionOpcode(bytes([cond]))
        reserve_fee = 0
        assert len(npc_result.npc_list[0].conditions) == 1
        assert npc_result.npc_list[0].conditions[0][0] == opcode
        for c in npc_result.npc_list[0].conditions[0][1]:
            assert c.opcode == opcode
            reserve_fee += int_from_bytes(c.vars[0])

        assert reserve_fee == 300
        assert len(npc_result.npc_list[0].conditions[0][1]) == 1

    def test_duplicate_outputs(self, softfork_height):
        # CREATE_COIN
        # creating multiple coins with the same properties (same parent, same
        # target puzzle hash and same amount) is not allowed. That's a consensus
        # failure.
        puzzle_hash = "abababababababababababababababab"
        npc_result = generator_condition_tester(f'(51 "{puzzle_hash}" 10) ' * 2, height=softfork_height)
        assert npc_result.error == Err.DUPLICATE_OUTPUT.value
        assert npc_result.npc_list == []

    def test_create_coin_cost(self, softfork_height):
        # CREATE_COIN
        puzzle_hash = "abababababababababababababababab"

        # this max cost is exactly enough for the create coin condition
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash}" 10) ',
            max_cost=20470 + 95 * COST_PER_BYTE + ConditionCost.CREATE_COIN.value,
            height=softfork_height,
        )
        assert npc_result.error is None
        assert npc_result.cost == 20470 + 95 * COST_PER_BYTE + ConditionCost.CREATE_COIN.value
        assert len(npc_result.npc_list) == 1

        # if we subtract one from max cost, this should fail
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash}" 10) ',
            max_cost=20470 + 95 * COST_PER_BYTE + ConditionCost.CREATE_COIN.value - 1,
            height=softfork_height,
        )
        assert npc_result.error in [Err.BLOCK_COST_EXCEEDS_MAX.value, Err.INVALID_BLOCK_COST.value]

    def test_agg_sig_cost(self, softfork_height):
        # AGG_SIG_ME
        pubkey = "abababababababababababababababababababababababab"

        # this max cost is exactly enough for the AGG_SIG condition
        npc_result = generator_condition_tester(
            f'(49 "{pubkey}" "foobar") ',
            max_cost=20512 + 117 * COST_PER_BYTE + ConditionCost.AGG_SIG.value,
            height=softfork_height,
        )
        assert npc_result.error is None
        assert npc_result.cost == 20512 + 117 * COST_PER_BYTE + ConditionCost.AGG_SIG.value
        assert len(npc_result.npc_list) == 1

        # if we subtract one from max cost, this should fail
        npc_result = generator_condition_tester(
            f'(49 "{pubkey}" "foobar") ',
            max_cost=20512 + 117 * COST_PER_BYTE + ConditionCost.AGG_SIG.value - 1,
            height=softfork_height,
        )
        assert npc_result.error in [Err.BLOCK_COST_EXCEEDS_MAX.value, Err.INVALID_BLOCK_COST.value]

    def test_create_coin_different_parent(self, softfork_height):

        # if the coins we create have different parents, they are never
        # considered duplicate, even when they have the same puzzle hash and
        # amount
        puzzle_hash = "abababababababababababababababab"
        program = SerializedProgram.from_bytes(
            binutils.assemble(
                f'(q ((0x0101010101010101010101010101010101010101010101010101010101010101 (q (51 "{puzzle_hash}" 10)) 123 (() (q . ())))(0x0101010101010101010101010101010101010101010101010101010101010102 (q (51 "{puzzle_hash}" 10)) 123 (() (q . ()))) ))'  # noqa
            ).as_bin()
        )
        generator = BlockGenerator(program, [], [])
        npc_result: NPCResult = get_name_puzzle_conditions(
            generator, MAX_BLOCK_COST_CLVM, cost_per_byte=COST_PER_BYTE, mempool_mode=False, height=softfork_height
        )
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 2
        opcode = ConditionOpcode.CREATE_COIN
        for c in npc_result.npc_list:
            assert c.conditions == [
                (
                    opcode.value,
                    [ConditionWithArgs(opcode, [puzzle_hash.encode("ascii"), bytes([10])])],
                )
            ]

    def test_create_coin_different_puzzhash(self, softfork_height):
        # CREATE_COIN
        # coins with different puzzle hashes are not considered duplicate
        puzzle_hash_1 = "abababababababababababababababab"
        puzzle_hash_2 = "cbcbcbcbcbcbcbcbcbcbcbcbcbcbcbcb"
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash_1}" 5) (51 "{puzzle_hash_2}" 5)', height=softfork_height
        )
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        opcode = ConditionOpcode.CREATE_COIN
        assert (
            ConditionWithArgs(opcode, [puzzle_hash_1.encode("ascii"), bytes([5])])
            in npc_result.npc_list[0].conditions[0][1]
        )
        assert (
            ConditionWithArgs(opcode, [puzzle_hash_2.encode("ascii"), bytes([5])])
            in npc_result.npc_list[0].conditions[0][1]
        )

    def test_create_coin_different_amounts(self, softfork_height):
        # CREATE_COIN
        # coins with different amounts are not considered duplicate
        puzzle_hash = "abababababababababababababababab"
        npc_result = generator_condition_tester(
            f'(51 "{puzzle_hash}" 5) (51 "{puzzle_hash}" 4)', height=softfork_height
        )
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        opcode = ConditionOpcode.CREATE_COIN
        assert (
            ConditionWithArgs(opcode, [puzzle_hash.encode("ascii"), bytes([5])])
            in npc_result.npc_list[0].conditions[0][1]
        )
        assert (
            ConditionWithArgs(opcode, [puzzle_hash.encode("ascii"), bytes([4])])
            in npc_result.npc_list[0].conditions[0][1]
        )

    def test_create_coin_with_hint(self, softfork_height):
        # CREATE_COIN
        puzzle_hash_1 = "abababababababababababababababab"
        hint = "12341234123412341234213421341234"
        npc_result = generator_condition_tester(f'(51 "{puzzle_hash_1}" 5 ("{hint}"))', height=softfork_height)
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        opcode = ConditionOpcode.CREATE_COIN
        assert npc_result.npc_list[0].conditions[0][1][0] == ConditionWithArgs(
            opcode, [puzzle_hash_1.encode("ascii"), bytes([5]), hint.encode("ascii")]
        )

    @pytest.mark.parametrize(
        "mempool,height",
        [
            (True, None),
            (False, 1000000),
            (False, 2300000),
        ],
    )
    def test_unknown_condition(self, mempool: bool, height: uint32):
        for c in ['(1 100 "foo" "bar")', "(100)", "(1 1) (2 2) (3 3)", '("foobar")']:
            npc_result = generator_condition_tester(c, mempool_mode=mempool, height=height)
            print(npc_result)
            if mempool:
                assert npc_result.error == Err.INVALID_CONDITION.value
                assert npc_result.npc_list == []
            else:
                assert npc_result.error is None
                assert npc_result.npc_list[0].conditions == []


# the tests below are malicious generator programs

# this program:
# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c V (iter V (- N 1))) ())
#  )
#  (iter (c (q . 83) (c (concat (large_string 0x00 A) (q . 100)) ())) B)
# )
# with A=28 and B specified as {num}

SINGLE_ARG_INT_COND = "(a (q 2 4 (c 2 (c (c (q . {opcode}) (c (concat (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (q . {val})) ())) (c 11 ())))) (c (q (a (i 11 (q 4 5 (a 4 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 28 {num})))"  # noqa

# this program:
# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c (c (q . 83) (c V ())) (iter (substr V 1) (- N 1))) ())
#  )
#  (iter (concat (large_string 0x00 A) (q . 100)) B)
# )
# truncates the first byte of the large string being passed down for each
# iteration, in an attempt to defeat any caching of integers by node ID.
# substr is cheap, and no memory is copied, so we can perform a lot of these
SINGLE_ARG_INT_SUBSTR_COND = "(a (q 2 4 (c 2 (c (concat (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (q . {val})) (c 11 ())))) (c (q (a (i 11 (q 4 (c (q . {opcode}) (c 5 ())) (a 4 (c 2 (c (substr 5 (q . 1)) (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 28 {num})))"  # noqa

# this program:
# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c (c (q . 83) (c V ())) (iter (substr V 0 (- (strlen V) 1)) (- N 1))) ())
#  )
#  (iter (concat (large_string 0x00 A) (q . 0xffffffff)) B)
# )
SINGLE_ARG_INT_SUBSTR_TAIL_COND = "(a (q 2 4 (c 2 (c (concat (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (q . {val})) (c 11 ())))) (c (q (a (i 11 (q 4 (c (q . {opcode}) (c 5 ())) (a 4 (c 2 (c (substr 5 () (- (strlen 5) (q . 1))) (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 25 {num})))"  # noqa

# (mod (A B)
#  (defun large_string (V N)
#    (if N (large_string (concat V V) (- N 1)) V)
#  )
#  (defun iter (V N)
#    (if N (c (c (q . 83) (c (concat V N) ())) (iter V (- N 1))) ())
#  )
#  (iter (large_string 0x00 A) B)
# )
SINGLE_ARG_INT_LADDER_COND = "(a (q 2 4 (c 2 (c (a 6 (c 2 (c (q . {filler}) (c 5 ())))) (c 11 ())))) (c (q (a (i 11 (q 4 (c (q . {opcode}) (c (concat 5 11) ())) (a 4 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) 2 (i 11 (q 2 6 (c 2 (c (concat 5 5) (c (- 11 (q . 1)) ())))) (q . 5)) 1) (q 24 {num})))"  # noqa

# this program:
# (mod (A B)
#  (defun large_message (N)
#    (lsh (q . "a") N)
#  )
#  (defun iter (V N)
#    (if N (c V (iter V (- N 1))) ())
#  )
#  (iter (c (q . 60) (c (large_message A) ())) B)
# )
# with B set to {num}

CREATE_ANNOUNCE_COND = "(a (q 2 4 (c 2 (c (c (q . {opcode}) (c (a 6 (c 2 (c 5 ()))) ())) (c 11 ())))) (c (q (a (i 11 (q 4 5 (a 4 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) 23 (q . 97) 5) (q 8184 {num})))"  # noqa

# this program:
# (mod (A)
#  (defun iter (V N)
#    (if N (c V (iter V (- N 1))) ())
#  )
#  (iter (q 51 "abababababababababababababababab" 1) A)
# )
CREATE_COIN = '(a (q 2 2 (c 2 (c (q 51 "abababababababababababababababab" 1) (c 5 ())))) (c (q 2 (i 11 (q 4 5 (a 2 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) (q {num})))'  # noqa

# this program:
# (mod (A)
#   (defun append (L B)
#     (if L
#       (c (f L) (append (r L) B))
#       (c B ())
#     )
#   )
#   (defun iter (V N)
#     (if N (c (append V N) (iter V (- N 1))) ())
#   )
#   (iter (q 51 "abababababababababababababababab") A)
# )
# creates {num} CREATE_COIN conditions, each with a different amount
CREATE_UNIQUE_COINS = '(a (q 2 6 (c 2 (c (q 51 "abababababababababababababababab") (c 5 ())))) (c (q (a (i 5 (q 4 9 (a 4 (c 2 (c 13 (c 11 ()))))) (q 4 11 ())) 1) 2 (i 11 (q 4 (a 4 (c 2 (c 5 (c 11 ())))) (a 6 (c 2 (c 5 (c (- 11 (q . 1)) ()))))) ()) 1) (q {num})))'  # noqa


# some of the malicious tests will fail post soft-fork, this function helps test
# the specific error to expect
def error_for_condition(cond: ConditionOpcode) -> int:
    if cond == ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED.value
    if cond == ConditionOpcode.ASSERT_HEIGHT_RELATIVE:
        return Err.ASSERT_HEIGHT_RELATIVE_FAILED.value
    if cond == ConditionOpcode.ASSERT_SECONDS_ABSOLUTE:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED.value
    if cond == ConditionOpcode.ASSERT_SECONDS_RELATIVE:
        return Err.ASSERT_SECONDS_RELATIVE_FAILED.value
    if cond == ConditionOpcode.RESERVE_FEE:
        return Err.RESERVE_FEE_CONDITION_FAILED.value
    assert False


class TestMaliciousGenerators:

    # TODO: create a lot of announcements. The messages can be made different by
    # using substr on a large buffer

    # for all the height/time locks, we should only return the most strict
    # condition, not all of them
    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_ladder(self, opcode, softfork_height):
        condition = SINGLE_ARG_INT_LADDER_COND.format(opcode=opcode.value[0], num=28, filler="0x00")
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        if softfork_height >= 2300000:
            assert npc_result.error == error_for_condition(opcode)
        else:
            assert npc_result.error is None
            assert len(npc_result.npc_list) == 1
            assert npc_result.npc_list[0].conditions == [
                (
                    opcode,
                    [ConditionWithArgs(opcode, [int_to_bytes(28)])],
                )
            ]
        assert run_time < 1.5
        print(f"run time:{run_time}")

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer(self, opcode, softfork_height):
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0x00")
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        if softfork_height >= 2300000:
            assert npc_result.error == error_for_condition(opcode)
        else:
            assert npc_result.error is None
            assert len(npc_result.npc_list) == 1
            assert npc_result.npc_list[0].conditions == [
                (
                    opcode,
                    [ConditionWithArgs(opcode, [bytes([100])])],
                )
            ]
        assert run_time < 2.5
        print(f"run time:{run_time}")

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_substr(self, opcode, softfork_height):
        condition = SINGLE_ARG_INT_SUBSTR_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0x00")
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        if softfork_height >= 2300000:
            assert npc_result.error == error_for_condition(opcode)
        else:
            assert npc_result.error is None
            assert len(npc_result.npc_list) == 1
            assert npc_result.npc_list[0].conditions == [
                (
                    opcode,
                    [ConditionWithArgs(opcode, [bytes([100])])],
                )
            ]
        assert run_time < 3
        print(f"run time:{run_time}")

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_substr_tail(self, opcode, softfork_height):
        condition = SINGLE_ARG_INT_SUBSTR_TAIL_COND.format(
            opcode=opcode.value[0], num=280, val="0xffffffff", filler="0x00"
        )
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        if softfork_height >= 2300000:
            assert npc_result.error == error_for_condition(opcode)
        else:
            assert npc_result.error is None
            assert len(npc_result.npc_list) == 1

            print(npc_result.npc_list[0].conditions[0][1])
            assert ConditionWithArgs(opcode, [int_to_bytes(0xFFFFFFFF)]) in npc_result.npc_list[0].conditions[0][1]
        assert run_time < 1
        print(f"run time:{run_time}")

    @pytest.mark.parametrize(
        "opcode",
        [
            ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE,
            ConditionOpcode.ASSERT_HEIGHT_RELATIVE,
            ConditionOpcode.ASSERT_SECONDS_ABSOLUTE,
            ConditionOpcode.ASSERT_SECONDS_RELATIVE,
        ],
    )
    def test_duplicate_large_integer_negative(self, opcode, softfork_height):
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0xff")
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        assert npc_result.npc_list[0].conditions == []
        assert run_time < 2
        print(f"run time:{run_time}")

    def test_duplicate_reserve_fee(self, softfork_height):
        opcode = ConditionOpcode.RESERVE_FEE
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=280000, val=100, filler="0x00")
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        if softfork_height >= 2300000:
            assert npc_result.error == error_for_condition(opcode)
        else:
            assert npc_result.error is None
            assert len(npc_result.npc_list) == 1
            assert npc_result.npc_list[0].conditions == [
                (
                    opcode.value,
                    [ConditionWithArgs(opcode, [int_to_bytes(100 * 280000)])],
                )
            ]
        assert run_time < 2
        print(f"run time:{run_time}")

    def test_duplicate_reserve_fee_negative(self, softfork_height):
        opcode = ConditionOpcode.RESERVE_FEE
        condition = SINGLE_ARG_INT_COND.format(opcode=opcode.value[0], num=200000, val=100, filler="0xff")
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        # RESERVE_FEE conditions fail unconditionally if they have a negative
        # amount
        assert npc_result.error == Err.RESERVE_FEE_CONDITION_FAILED.value
        assert len(npc_result.npc_list) == 0
        assert run_time < 1.5
        print(f"run time:{run_time}")

    @pytest.mark.parametrize(
        "opcode", [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]
    )
    def test_duplicate_coin_announces(self, opcode, softfork_height):
        condition = CREATE_ANNOUNCE_COND.format(opcode=opcode.value[0], num=5950000)
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        # coin announcements are not propagated to python, but validated in rust
        assert len(npc_result.npc_list[0].conditions) == 0
        # TODO: optimize clvm to make this run in < 1 second
        assert run_time < 21
        print(f"run time:{run_time}")

    def test_create_coin_duplicates(self, softfork_height):
        # CREATE_COIN
        # this program will emit 6000 identical CREATE_COIN conditions. However,
        # we'll just end up looking at two of them, and fail at the first
        # duplicate
        condition = CREATE_COIN.format(num=600000)
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        assert npc_result.error == Err.DUPLICATE_OUTPUT.value
        assert len(npc_result.npc_list) == 0
        assert run_time < 2
        print(f"run time:{run_time}")

    def test_many_create_coin(self, softfork_height):
        # CREATE_COIN
        # this program will emit many CREATE_COIN conditions, all with different
        # amounts.
        # the number 6095 was chosen carefully to not exceed the maximum cost
        condition = CREATE_UNIQUE_COINS.format(num=6094)
        start_time = time()
        npc_result = generator_condition_tester(condition, quote=False, height=softfork_height)
        run_time = time() - start_time
        assert npc_result.error is None
        assert len(npc_result.npc_list) == 1
        assert len(npc_result.npc_list[0].conditions) == 1
        assert npc_result.npc_list[0].conditions[0][0] == ConditionOpcode.CREATE_COIN.value
        assert len(npc_result.npc_list[0].conditions[0][1]) == 6094
        assert run_time < 1
        print(f"run time:{run_time}")

    @pytest.mark.asyncio
    async def test_invalid_coin_spend_coin(self, bt, two_nodes, wallet_a):
        reward_ph = wallet_a.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            5,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
        )
        full_node_1, full_node_2, server_1, server_2 = two_nodes

        for block in blocks:
            await full_node_1.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(60, node_height_at_least, True, full_node_1, blocks[-1].height)

        spend_bundle = generate_test_spend_bundle(wallet_a, list(blocks[-1].get_included_reward_coins())[0])
        coin_spend_0 = recursive_replace(spend_bundle.coin_spends[0], "coin.puzzle_hash", bytes32([1] * 32))
        new_bundle = recursive_replace(spend_bundle, "coin_spends", [coin_spend_0] + spend_bundle.coin_spends[1:])
        assert spend_bundle is not None
        res = await full_node_1.full_node.respond_transaction(new_bundle, new_bundle.name())
        assert res == (MempoolInclusionStatus.FAILED, Err.INVALID_SPEND_BUNDLE)


class TestPkmPairs:

    h1 = bytes32(b"a" * 32)
    h2 = bytes32(b"b" * 32)
    h3 = bytes32(b"c" * 32)
    h4 = bytes32(b"d" * 32)

    pk1 = G1Element.generator()
    pk2 = G1Element.generator()

    CCA = ConditionOpcode.CREATE_COIN_ANNOUNCEMENT
    CC = ConditionOpcode.CREATE_COIN
    ASM = ConditionOpcode.AGG_SIG_ME
    ASU = ConditionOpcode.AGG_SIG_UNSAFE

    def test_empty_list(self):
        npc_list = []
        pks, msgs = pkm_pairs(npc_list, b"foobar")
        assert pks == []
        assert msgs == []

    def test_no_agg_sigs(self):
        npc_list = [
            NPC(self.h1, self.h2, [(self.CCA, [ConditionWithArgs(self.CCA, [b"msg"])])]),
            NPC(self.h3, self.h4, [(self.CC, [ConditionWithArgs(self.CCA, [self.h1, bytes([1])])])]),
        ]
        pks, msgs = pkm_pairs(npc_list, b"foobar")
        assert pks == []
        assert msgs == []

    def test_agg_sig_me(self):
        npc_list = [
            NPC(
                self.h1,
                self.h2,
                [
                    (
                        self.ASM,
                        [
                            ConditionWithArgs(self.ASM, [bytes(self.pk1), b"msg1"]),
                            ConditionWithArgs(self.ASM, [bytes(self.pk2), b"msg2"]),
                        ],
                    )
                ],
            )
        ]
        pks, msgs = pkm_pairs(npc_list, b"foobar")
        assert [bytes(pk) for pk in pks] == [bytes(self.pk1), bytes(self.pk2)]
        assert msgs == [b"msg1" + self.h1 + b"foobar", b"msg2" + self.h1 + b"foobar"]

    def test_agg_sig_unsafe(self):
        npc_list = [
            NPC(
                self.h1,
                self.h2,
                [
                    (
                        self.ASU,
                        [
                            ConditionWithArgs(self.ASU, [bytes(self.pk1), b"msg1"]),
                            ConditionWithArgs(self.ASU, [bytes(self.pk2), b"msg2"]),
                        ],
                    )
                ],
            )
        ]
        pks, msgs = pkm_pairs(npc_list, b"foobar")
        assert [bytes(pk) for pk in pks] == [bytes(self.pk1), bytes(self.pk2)]
        assert msgs == [b"msg1", b"msg2"]

    def test_agg_sig_mixed(self):
        npc_list = [
            NPC(self.h1, self.h2, [(self.ASM, [ConditionWithArgs(self.ASM, [bytes(self.pk1), b"msg1"])])]),
            NPC(self.h1, self.h2, [(self.ASU, [ConditionWithArgs(self.ASU, [bytes(self.pk2), b"msg2"])])]),
        ]
        pks, msgs = pkm_pairs(npc_list, b"foobar")
        assert [bytes(pk) for pk in pks] == [bytes(self.pk1), bytes(self.pk2)]
        assert msgs == [b"msg1" + self.h1 + b"foobar", b"msg2"]

from pathlib import Path
from secrets import token_bytes
from typing import Optional

import aiosqlite
import pytest
from clvm_tools import binutils

from cryptodoge.types.blockchain_format.coin import Coin
from cryptodoge.types.blockchain_format.program import Program, SerializedProgram
from cryptodoge.types.blockchain_format.sized_bytes import bytes32
from cryptodoge.types.coin_spend import CoinSpend
from cryptodoge.util.db_wrapper import DBWrapper
from cryptodoge.util.ints import uint64

from cryptodoge.wallet.wallet_pool_store import WalletPoolStore


def make_child_solution(coin_spend: CoinSpend, new_coin: Optional[Coin] = None) -> CoinSpend:
    # TODO: address hint error and remove ignore
    #       error: Incompatible types in assignment (expression has type "bytes", variable has type "bytes32")
    #       [assignment]
    new_puzzle_hash: bytes32 = token_bytes(32)  # type: ignore[assignment]
    solution = "()"
    puzzle = f"(q . ((51 0x{new_puzzle_hash.hex()} 1)))"
    puzzle_prog = Program.to(binutils.assemble(puzzle))
    solution_prog = Program.to(binutils.assemble(solution))
    if new_coin is None:
        new_coin = coin_spend.additions()[0]
    sol: CoinSpend = CoinSpend(
        new_coin,
        SerializedProgram.from_program(puzzle_prog),
        SerializedProgram.from_program(solution_prog),
    )
    return sol


class TestWalletPoolStore:
    @pytest.mark.asyncio
    async def test_store(self):
        db_filename = Path("wallet_store_test.db")

        if db_filename.exists():
            db_filename.unlink()

        db_connection = await aiosqlite.connect(db_filename)
        db_wrapper = DBWrapper(db_connection)
        store = await WalletPoolStore.create(db_wrapper)
        try:
            await db_wrapper.begin_transaction()
            coin_0 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            coin_0_alt = Coin(token_bytes(32), token_bytes(32), uint64(12312))
            solution_0: CoinSpend = make_child_solution(None, coin_0)
            solution_0_alt: CoinSpend = make_child_solution(None, coin_0_alt)
            solution_1: CoinSpend = make_child_solution(solution_0)

            assert store.get_spends_for_wallet(0) == []
            assert store.get_spends_for_wallet(1) == []

            await store.add_spend(1, solution_1, 100, True)
            assert store.get_spends_for_wallet(1) == [(100, solution_1)]

            # Idempotent
            await store.add_spend(1, solution_1, 100, True)
            assert store.get_spends_for_wallet(1) == [(100, solution_1)]

            with pytest.raises(ValueError):
                await store.add_spend(1, solution_1, 101, True)

            # Rebuild cache, no longer present
            await db_wrapper.rollback_transaction()
            await store.rebuild_cache()
            assert store.get_spends_for_wallet(1) == []

            await store.rebuild_cache()
            await store.add_spend(1, solution_1, 100, False)
            assert store.get_spends_for_wallet(1) == [(100, solution_1)]

            solution_1_alt: CoinSpend = make_child_solution(solution_0_alt)

            with pytest.raises(ValueError):
                await store.add_spend(1, solution_1_alt, 100, False)

            assert store.get_spends_for_wallet(1) == [(100, solution_1)]

            solution_2: CoinSpend = make_child_solution(solution_1)
            await store.add_spend(1, solution_2, 100, False)
            await store.rebuild_cache()
            solution_3: CoinSpend = make_child_solution(solution_2)
            await store.add_spend(1, solution_3, 100)
            solution_4: CoinSpend = make_child_solution(solution_3)

            with pytest.raises(ValueError):
                await store.add_spend(1, solution_4, 99)

            await store.rebuild_cache()
            await store.add_spend(1, solution_4, 101)
            await store.rebuild_cache()
            await store.rollback(101, 1, False)
            await store.rebuild_cache()
            assert store.get_spends_for_wallet(1) == [
                (100, solution_1),
                (100, solution_2),
                (100, solution_3),
                (101, solution_4),
            ]
            await store.rebuild_cache()
            await store.rollback(100, 1, False)
            await store.rebuild_cache()
            assert store.get_spends_for_wallet(1) == [
                (100, solution_1),
                (100, solution_2),
                (100, solution_3),
            ]
            with pytest.raises(ValueError):
                await store.add_spend(1, solution_1, 105)

            await store.add_spend(1, solution_4, 105)
            solution_5: CoinSpend = make_child_solution(solution_4)
            await store.add_spend(1, solution_5, 105)
            await store.rollback(99, 1, False)
            assert store.get_spends_for_wallet(1) == []

        finally:
            await db_connection.close()
            db_filename.unlink()

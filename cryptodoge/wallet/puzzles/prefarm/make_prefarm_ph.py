from clvm.casts import int_from_bytes
from clvm_tools import binutils

from cryptodoge.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from cryptodoge.types.blockchain_format.program import Program
from cryptodoge.types.condition_opcodes import ConditionOpcode
from cryptodoge.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from cryptodoge.util.condition_tools import parse_sexp_to_conditions
from cryptodoge.util.ints import uint32
from cryptodoge.types.blockchain_format.sized_bytes import bytes32

address1 = "txcd15gx26ndmacfaqlq8m0yajeggzceu7cvmaz4df0hahkukes695rss6lej7h"  # Gene wallet (m/12381/8444/2/42):
address2 = "txcd1c2cguswhvmdyz9hr3q6hak2h6p9dw4rz82g4707k2xy2sarv705qcce4pn"  # Chris address (m/12381/8444/2/0)

ph1 = decode_puzzle_hash(address1)
ph2 = decode_puzzle_hash(address2)

pool_amounts = int(calculate_pool_reward(uint32(0)) / 2)
farmer_amounts = int(calculate_base_farmer_reward(uint32(0)) / 2)

assert pool_amounts * 2 == calculate_pool_reward(uint32(0))
assert farmer_amounts * 2 == calculate_base_farmer_reward(uint32(0))


def make_puzzle(amount: int) -> int:
    puzzle = f"(q . ((51 0x{ph1.hex()} {amount}) (51 0x{ph2.hex()} {amount})))"
    # print(puzzle)

    puzzle_prog = Program.to(binutils.assemble(puzzle))
    print("Program: ", puzzle_prog)
    puzzle_hash = puzzle_prog.get_tree_hash()

    solution = "()"
    prefix = "xcd"
    print("PH", puzzle_hash)
    print(f"Address: {encode_puzzle_hash(puzzle_hash, prefix)}")

    result = puzzle_prog.run(solution)
    error, result_human = parse_sexp_to_conditions(result)

    total_cryptodoge = 0
    if error:
        print(f"Error: {error}")
    else:
        assert result_human is not None
        for cvp in result_human:
            assert len(cvp.vars) == 2
            total_cryptodoge += int_from_bytes(cvp.vars[1])
            print(
                f"{ConditionOpcode(cvp.opcode).name}: {encode_puzzle_hash(bytes32(cvp.vars[0]), prefix)},"
                f" amount: {int_from_bytes(cvp.vars[1])}"
            )
    return total_cryptodoge


total_cryptodoge = 0
print("Pool address: ")
total_cryptodoge += make_puzzle(pool_amounts)
print("\nFarmer address: ")
total_cryptodoge += make_puzzle(farmer_amounts)

assert total_cryptodoge == calculate_base_farmer_reward(uint32(0)) + calculate_pool_reward(uint32(0))

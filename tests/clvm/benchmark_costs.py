from cryptodoge.types.blockchain_format.program import INFINITE_COST
from cryptodoge.types.spend_bundle import SpendBundle
from cryptodoge.types.generator_types import BlockGenerator
from cryptodoge.consensus.cost_calculator import NPCResult
from cryptodoge.consensus.default_constants import DEFAULT_CONSTANTS
from cryptodoge.full_node.bundle_tools import simple_solution_generator
from cryptodoge.full_node.mempool_check_conditions import get_name_puzzle_conditions


def cost_of_spend_bundle(spend_bundle: SpendBundle) -> int:
    program: BlockGenerator = simple_solution_generator(spend_bundle)
    npc_result: NPCResult = get_name_puzzle_conditions(
        program, INFINITE_COST, cost_per_byte=DEFAULT_CONSTANTS.COST_PER_BYTE, mempool_mode=True
    )
    return npc_result.cost

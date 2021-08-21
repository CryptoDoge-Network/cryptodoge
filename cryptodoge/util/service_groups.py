from typing import KeysView, Generator

SERVICES_FOR_GROUP = {
    "all": "cryptodoge_harvester cryptodoge_timelord_launcher cryptodoge_timelord cryptodoge_farmer cryptodoge_full_node cryptodoge_wallet".split(),
    "node": "cryptodoge_full_node".split(),
    "harvester": "cryptodoge_harvester".split(),
    "farmer": "cryptodoge_harvester cryptodoge_farmer cryptodoge_full_node cryptodoge_wallet".split(),
    "farmer-no-wallet": "cryptodoge_harvester cryptodoge_farmer cryptodoge_full_node".split(),
    "farmer-only": "cryptodoge_farmer".split(),
    "timelord": "cryptodoge_timelord_launcher cryptodoge_timelord cryptodoge_full_node".split(),
    "timelord-only": "cryptodoge_timelord".split(),
    "timelord-launcher-only": "cryptodoge_timelord_launcher".split(),
    "wallet": "cryptodoge_wallet cryptodoge_full_node".split(),
    "wallet-only": "cryptodoge_wallet".split(),
    "introducer": "cryptodoge_introducer".split(),
    "simulator": "cryptodoge_full_node_simulator".split(),
}


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def validate_service(service: str) -> bool:
    return any(service in _ for _ in SERVICES_FOR_GROUP.values())

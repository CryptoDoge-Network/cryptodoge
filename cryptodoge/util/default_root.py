import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("CRYPTODOGE_ROOT", "~/.cryptodoge/mainnet"))).resolve()
STANDALONE_ROOT_PATH = Path(
    os.path.expanduser(os.getenv("CRYPTODOGE_STANDALONE_WALLET_ROOT", "~/.cryptodoge/standalone_wallet"))
).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("CRYPTODOGE_KEYS_ROOT", "~/.cryptodoge_keys"))).resolve()

from setuptools import setup

dependencies = [
    "blspy==1.0.6",  # Signature library
    "chiavdf==1.0.3",  # timelord and vdf verification
    "chiabip158==1.0",  # bip158-style wallet filters
    "chiapos==1.0.4",  # proof of space
    "clvm==0.9.7",
    "clvm_rs==0.1.14",
    "clvm_tools==0.4.3",
    "aiohttp==3.7.4",  # HTTP server for full node rpc
    "aiosqlite==0.17.0",  # asyncio wrapper for sqlite, to store blocks
    "bitstring==3.1.9",  # Binary data management library
    "colorama==0.4.4",  # Colorizes terminal output
    "colorlog==5.0.1",  # Adds color to logs
    "concurrent-log-handler==0.9.19",  # Concurrently log and rotate logs
    "cryptography==3.4.7",  # Python cryptography library for TLS - keyring conflict
    "fasteners==0.16.3",  # For interprocess file locking
    "keyring==23.0.1",  # Store keys in MacOS Keychain, Windows Credential Locker
    "keyrings.cryptfile==1.3.4",  # Secure storage for keys on Linux (Will be replaced)
    #  "keyrings.cryptfile==1.3.8",  # Secure storage for keys on Linux (Will be replaced)
    #  See https://github.com/frispete/keyrings.cryptfile/issues/15
    "PyYAML==5.4.1",  # Used for config file format
    "setproctitle==1.2.2",  # Gives the cryptodoge processes readable names
    "sortedcontainers==2.4.0",  # For maintaining sorted mempools
    "websockets==8.1.0",  # For use in wallet RPC and electron UI
    "click==7.1.2",  # For the CLI
    "dnspython==2.1.0",  # Query DNS seeds
    "watchdog==2.1.3",  # Filesystem event watching - watches keyring.yaml
]

upnp_dependencies = [
    "miniupnpc==2.2.2",  # Allows users to open ports on their router
]

dev_dependencies = [
    "pytest",
    "pytest-asyncio",
    "flake8",
    "mypy",
    "black",
    "aiohttp_cors",  # For blackd
    "ipython",  # For asyncio debugging
    "types-setuptools",
]

kwargs = dict(
    name="cryptodoge",
    author="Chris Evan",
    author_email="dev@cryptodoge.cc",
    description="Cryptodoge full node, farmer, timelord, and wallet.",
    url="https://cryptodoge.cc/",
    license="Apache License",
    python_requires=">=3.7, <4",
    keywords="cryptodoge node",
    install_requires=dependencies,
    setup_requires=["setuptools_scm"],
    extras_require=dict(
        uvloop=["uvloop"],
        dev=dev_dependencies,
        upnp=upnp_dependencies,
    ),
    packages=[
        "build_scripts",
        "cryptodoge",
        "cryptodoge.cmds",
        "cryptodoge.clvm",
        "cryptodoge.consensus",
        "cryptodoge.daemon",
        "cryptodoge.full_node",
        "cryptodoge.timelord",
        "cryptodoge.farmer",
        "cryptodoge.harvester",
        "cryptodoge.introducer",
        "cryptodoge.plotting",
        "cryptodoge.pools",
        "cryptodoge.protocols",
        "cryptodoge.rpc",
        "cryptodoge.server",
        "cryptodoge.simulator",
        "cryptodoge.types.blockchain_format",
        "cryptodoge.types",
        "cryptodoge.util",
        "cryptodoge.wallet",
        "cryptodoge.wallet.puzzles",
        "cryptodoge.wallet.rl_wallet",
        "cryptodoge.wallet.cc_wallet",
        "cryptodoge.wallet.did_wallet",
        "cryptodoge.wallet.settings",
        "cryptodoge.wallet.trading",
        "cryptodoge.wallet.util",
        "cryptodoge.ssl",
        "mozilla-ca",
    ],
    entry_points={
        "console_scripts": [
            "cryptodoge = cryptodoge.cmds.cryptodoge:main",
            "cryptodoge_wallet = cryptodoge.server.start_wallet:main",
            "cryptodoge_full_node = cryptodoge.server.start_full_node:main",
            "cryptodoge_harvester = cryptodoge.server.start_harvester:main",
            "cryptodoge_farmer = cryptodoge.server.start_farmer:main",
            "cryptodoge_introducer = cryptodoge.server.start_introducer:main",
            "cryptodoge_timelord = cryptodoge.server.start_timelord:main",
            "cryptodoge_timelord_launcher = cryptodoge.timelord.timelord_launcher:main",
            "cryptodoge_full_node_simulator = cryptodoge.simulator.start_simulator:main",
        ]
    },
    package_data={
        "cryptodoge": ["pyinstaller.spec"],
        "": ["*.clvm", "*.clvm.hex", "*.clib", "*.clinc", "*.clsp", "py.typed"],
        "cryptodoge.util": ["initial-*.yaml", "english.txt"],
        "cryptodoge.ssl": ["cryptodoge_ca.crt", "cryptodoge_ca.key", "dst_root_ca.pem"],
        "mozilla-ca": ["cacert.pem"],
    },
    use_scm_version={"fallback_version": "unknown-no-.git-directory"},
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    zip_safe=False,
)


if __name__ == "__main__":
    setup(**kwargs)

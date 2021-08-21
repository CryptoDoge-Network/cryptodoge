# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project does not yet adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for setuptools_scm/PEP 440 reasons.

## 1.2.0 Cryptodoge 2021-07-07

### Added

- Portable pooled plots are now available using our new plot NFT. These allow you to plot new plots to an NFT that can either self farm or join and leave pools. During development there were changes to the plot NFT so portable pool plots (those made with `-c` option to `cryptodoge plots create`) using code from before June 25th are invalid on mainnet.
OG plots made before this release can continue to be farmed side by side with the new portable pool plots but can not join pools using the official pooling protocol. You can learn more as a farmer by checking out the [pool user guide](https://github.com/Cryptodoge-Network/cryptodoge/wiki/Pooling-User-Guide). Pool operators and those wanting to understand how the official pooling protocol operates should check out our [pooling implementation reference repository](https://github.com/Cryptodoge-Network/pool-reference). If you plan to use plot NFT, all your farmers and harvesters must be on 1.2.0 to function properly for portable pool plots.
- The exact commit after which Plot NFTs should be valid is the 89f7a4b3d6329493cd2b4bc5f346a819c99d3e7b commit (in which `pools.testnet9` branch was merged to main) or 5d62b3d1481c1e225d8354a012727ab263342c0a within the `pools.testnet9` branch.
- `cryptodoge farm summary` and the GUI now use a new RPC endpoint to properly show plots for local and remote harvesters. This should address issues #6563, #5881, #3875, #1461.
- `cryptodoge configure` now supports command line updates to peer count and target peer count.
- Thank you @gldecurtins for adding logging support for remote syslog.
- Thanks to @maran and @Animazing for adding farmer and pool public key display to the RPC.
- We have added translations for Hungarian, Belarusian, Catalan, and Albanian.  For Hungarian thanks to @SirGeoff, @azazio @onokaxxx, @rolandfarkasCOM, @HUNDavid , @horvathpalzsolt, @stishun74, @tusdavgaming, @idotitusz, @rasocsabi, @mail.kope, @gsprblnt, @mbudahazi, @csiberius, @tomatos83, @zok42, @ocel0t, @rwtoptomi, @djxpitke, @ftamas85, @zotya0330, @fnni, @kapabeates, @zamery, @viktor.gonczi, @pal.suta, @miv, and @Joeman_. For Belarusian thanks to @shurix83, @haxycgm, and @metalomaniax. For Catalan thank you to @Poliwhirl, @Pep-33, @marqmarti, @meuca, @Guiwdin, @carlescampi, @jairobtx, @Neoares, @darknsis, @augustfarrerasgimeno, and @fornons. Finally for Albanian thanks to @ATSHOOTER and @lakedeejay. We apologize if we missed anyone and welcome corrections.
- Our release process is now fully automated from tagging a release to publishing installers to all of the appropriate locations and now makes the release artifacts available via torrents as well.
- All Cryptodoge repositories now automatically build M1 wheels and create a new MacOS M1 native installer.
- New CLI command `cryptodoge plotnft` to manage pools.
- We have added a new RPC `get_harvesters` to the farmer. This returns information about remote harvesters and plots.
- We have added a new RPC `check_delete_key` to the wallet, to check keys prior to deleting them.
- We have added a new RPC `delete_unconfirmed_transactions` to the wallet which deletes these transactions for a given wallet ID.
- We have added a new RPC `get_puzzle_and_solution` to the full node, which takes in a coin ID.
- We have added a new RPC `get_recent_signage_point_or_eos` to the full node, to support pooling.
- We have added a new RPC `send_transaction_multi` to the wallet, which sends a payment with multiple payees.

### Changed

- We have made a host of changes to the GUI to support pooling and to improve the wallet experience.
- We updated chiapos to version 1.0.3. This adds parallel reads to GetFullProof. Thanks to @marcoabreu ! We now print target/final directory early in the logs refs and log process ID. Thanks to @grayfallstown ! We are now using Gulrak 1.5.6.
@683280 optimized code in phase1.hpp. @jespino and @mrhacky started migrating to flags instead of booleans parameters for `show_progress` and `nobitfield`. If you are providing third-party tools you may need to make adjustments if relying on the chiapos log.
- Updated chiavdf to version 1.0.2 to fix certain tests.
- Windows builds now rely upon Python 3.9 which obviates the fix in 1.1.7.
- We are now using miniupnpc version 2.2.2 so that we can support Python 3.9 on Windows.
- We updated to clvm 0.9.6 and clvm_rs 0.1.8. CLVMObject now lazily converts python types to CLVM types as elements are inspected in clvm. cvlm_rs now returns python objects rather than a serialized object.
- We now have rudimentary checks to makes sure that fees are less than the amount being spent.
- The harvester API no longer relies upon time:time with thanks to @x1957.
- We have increased the strictness of validating Chialisp in the mempool and clvm.
- Thanks to @ruslanskorb for improvements to the human-readable forms in the CLI.
- Thanks to @etr2460 for improvements to the plotting progress bar in the GUI and enhancements to human-readable sizes.
- @dkackman changed the way that configuration was found on startup.
- We now delay peer start for wallet until after backup init and make sure only one copy is started.
- Wallets now trust the local node more for enhanced wallet sync speed.
- We now store tasks used to initiate peer connections to ensure they are kept alive and to be able to wait for them if we hit the upper limit on number of pending outgoing connections.
- We improved weight proof validation.
- @cvet changed the wallet to take `override` instead of `confirm`.

### Fixed

- The delete plots button in the Windows GUI has been fixed and re-enabled.
- Sometimes upon startup, the GUI takes a while to load the plots to display. We've made a temporary improvement that adds a "Refresh Plots" button whenever the GUI has not yet found plots.
- Correctly display private key in `cryptodoge keys show`.
- Thanks to @gldecurtins for removing a default printout of the private key mnemonic in `cryptodoge keys show`.
- Shutting down the full node is cleaner and manages uPnP better.
- DNS introducer could fail.
- Fixed a potential timelord bug that could lead to a chain stall.
- Add an explicit error message when mnemonic words are not in the dictionary; should help users self-service issues like #3425 faster. Thank you to @elliotback for this PR.
- Thank you to @Nikolaj-K for various typo corrections around the Mozilla CA, code simplifications and improvements in converting to human-readable size estimations, and clean up in the RPCs and logging.
- Thank you to @ChiaMineJP for various improvements.
- @asdf2014 removed some useless code in the wallet node API.
- Thanks to @willi123yao for a fix to under development pool wallets.
- `cryptodoge farm summary` better handles wallet errors.
- @Hoinor fixed formatting issues around the Chinese translation in the GUI.
- Sometimes the GUI would stop refreshing certain fields.
- We have better error handling for misbehaving peers from naive forks/clones.
- We have fixed an error where the wallet could get corrupted, which previously required restarting the application.
- We have fixed an error where transactions were not being resubmitted from the wallet.

### Known Issues

- If you resync your wallet, transactions made with your plot NFTs will show incorrectly in the GUI. The internal accounting, and total balance displayed is correct.


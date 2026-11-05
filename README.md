# Kraskus Crypto — Umbrel App Store

Umbrel-native community app store for Kraskus Crypto apps (umbrelOS 2.0+).

Add it in umbrelOS: **App Store → ⋯ → Community App Stores**, then paste
`https://github.com/kraskuscrypto/Kraskus-Umbrel-Store`.

**Add only one Kraskus store, this one or the Dev store (testers), never both.** Both use
the store id `kraskus`, because Umbrel requires app IDs to start with the store id. They share
app IDs, and Umbrel installs a shared app from whichever store was added first, so with both
added you can silently get the other channel's version.

MystNodes by Kraskus is listed separately:
`https://github.com/kraskuscrypto/Kraskus-Umbrel-Mysterium-Store`.

## Current Main releases

BTC 0.5.6, BCH 0.5.12, Monero 0.3.5, Kaspa 0.5.4, XBT 0.3.3,
Pearl 0.6.4, CHTA 0.6.2 and DigiByte 0.3.1 match the approved Main catalog.
BSV 0.6.3 and Zcash 0.6.1 now include the external-wallet template updates.
Zcash retains its existing pre-NU7 compatibility and storage limits; this update does not qualify a new node/network-upgrade baseline. MystNodes 2.7.0 is in its separate store.

Read each app's migration warning before updating. Updated mining apps use external
reward addresses and remove user-facing native-wallet controls. Move existing holdings
to a wallet you control and keep verified wallet backups before updating. Legacy wallet
data is preserved; preservation does not replace your recovery backup.

## How this store is built

**Do not edit app folders by hand.** The approved production
[Kraskus-Crypto-Store](https://github.com/kraskuscrypto/Kraskus-Crypto-Store)
is the source of truth. `generated-from.json` pins its exact commit.

```bash
KRASKUS_MAIN_SOURCE=/path/to/Kraskus-Crypto-Store python3 tools/umbrel-store-gen/generate.py /path/to/output --stores Kraskus-Umbrel-Store Kraskus-Umbrel-Mysterium-Store
python3 tools/umbrel-store-gen/validate.py /path/to/output/Kraskus-Umbrel-Store /path/to/output/Kraskus-Umbrel-Mysterium-Store
```

The output root contains folders named for the destination repositories. Selecting Main
and Myst does not regenerate Dev. The generator converts the manifest, retains app IDs,
versions, images, data mounts, mining rules and miner/P2P ports, and removes direct UI host
port mappings so Umbrel's authenticated app gateway remains the browser entry point.
JSON Compose inputs may be reformatted; parsed configuration is checked for the
allowed UI-port removal. BSV 0.6.x also converts its explicit API platform declaration
from 5tratumOS to Umbrel, only when both the UI and API have no published ports or
host networking; unexpected declarations are refused. MystNodes payment handling and official node runtime are retained.
Listing-copy overrides are fingerprint-pinned and stop generation if upstream copy changes.
Icons ship in each catalog and are served from that repository.

Qualification covers catalog validation, conversion regression tests and comparison with
the approved Main recipes. Images were qualified for x86-64; this is not a claim of ARM
qualification or a new full installation/migration test on an Umbrel device. Publishing
this catalog does not update or restart installed applications.

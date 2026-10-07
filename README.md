# Kraskus Crypto — Umbrel App Store

Umbrel-native community app store for Kraskus Crypto apps (umbrelOS 2.0+).

Add it in umbrelOS: **App Store → ⋯ → Community App Stores**, then paste
`https://github.com/kraskuscrypto/Kraskus-Umbrel-Store`.

Add **only one** Kraskus store (this one, or the Dev store for testers). Both use the
store id `kraskus`, because Umbrel requires app IDs to start with the store id. When both
are added, Umbrel installs each shared app from whichever store was added first.

MystNodes by Kraskus is listed separately:
`https://github.com/kraskuscrypto/Kraskus-Umbrel-Mysterium-Store`.

## How this store is built

**Do not edit app folders by hand.** They are generated from the 5tratumOS production store
[`Kraskus-Crypto-Store`](https://github.com/kraskuscrypto/Kraskus-Crypto-Store), which stays
the single source of truth:

```
python tools/umbrel-store-gen/generate.py <dir containing the three Umbrel store repos>
python tools/umbrel-store-gen/validate.py Kraskus-Umbrel-Store Kraskus-Umbrel-Dev-Store Kraskus-Umbrel-Mysterium-Store
```

- `umbrel-app.yml` is `5tratstore-app.yml` minus 5tratumOS-only keys (`services`, `uiMode`), plus
  `manifestVersion: 1`, `gallery: []` and an absolute icon URL pinned to the source commit.
- `docker-compose.yml` and all other package files are byte-identical to the source. The one
  exception is the Common Foundry GPU Miner (Dev store): there the hard NVIDIA reservation is
  replaced by `permissions: [GPU]`.
- App IDs, versions, ports and images are never changed.
- Store-listing copy for Umbrel goes in `tools/umbrel-store-gen/overrides.yml`.
- `generated-from.json` records the exact source commit.

Umbrel's own login is the platform authentication boundary for every app (the app gateway's
default). Kraskus apps add no login of their own; the wallet password is the only app
credential, used for sensitive wallet actions.

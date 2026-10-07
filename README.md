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

## How this store is built

**Do not edit app folders by hand.** They are generated from the 5tratumOS production store
[`Kraskus-Crypto-Store`](https://github.com/kraskuscrypto/Kraskus-Crypto-Store), which stays
the single source of truth:

```
python tools/umbrel-store-gen/generate.py <dir containing the three Umbrel store repos>
python tools/umbrel-store-gen/validate.py Kraskus-Umbrel-Store Kraskus-Umbrel-Dev-Store Kraskus-Umbrel-Mysterium-Store
```

- `umbrel-app.yml` is `5tratstore-app.yml` minus 5tratumOS-only keys (`services`, `uiMode`), plus
  `manifestVersion: 1`, `gallery: []` and an absolute icon URL. Icons ship in this repo
  (`<app>/assets/`) and are served from it.
- `docker-compose.yml` and all other package files are byte-identical to the source. The one
  exception is the Common Foundry GPU Miner (Dev store): there the hard NVIDIA reservation is
  replaced by `permissions: [GPU]`.
- App IDs, versions, ports and images are never changed.
- Platform-neutral store-listing copy goes in `tools/umbrel-store-gen/overrides.yml`. Each
  override records a fingerprint of the source copy it replaces, so a source wording change
  stops generation until the Umbrel copy is reviewed.
- `generated-from.json` records the exact source commit.

Umbrel's own login is the platform authentication boundary for every app (the app gateway's
default). Kraskus apps add no login of their own; the wallet password is the only app
credential, used for sensitive wallet actions.

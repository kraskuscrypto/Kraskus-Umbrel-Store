#!/usr/bin/env python3
"""Generate the Umbrel-native Kraskus stores from the 5tratumOS store repos.

The 5tratumOS stores (Kraskus-Crypto-Store / Kraskus-Crypto-Dev-Store) stay the
source of truth and are never modified. For every app this writes:

  <app>/umbrel-app.yml      5tratstore-app.yml minus 5tratumOS-only keys, plus
                            manifestVersion: 1, gallery: [] and an absolute icon URL
  <app>/docker-compose.yml  byte-for-byte copy, except the GPU miner's hard NVIDIA
                            reservation, which Umbrel re-adds via permissions: [GPU],
                            and, for UNPUBLISHED_UI_APPS, the UI service's host port
                            (Umbrel reaches the UI through its logged-in app proxy)
  <app>/...                 every other package file, byte-for-byte

plus a root umbrel-app-store.yml and generated-from.json (source commit).
App IDs are never changed.

usage: generate.py <output-root>   (writes <output-root>/<store repo name>/)
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

import yaml

GENERATOR_VERSION = "1.0.0"
KRASKUS = "D:/Kraskus"
SOURCES = {
    "main": ("Kraskus-Crypto-Store", f"{KRASKUS}/Kraskus-Crypto-Store"),
    "dev": ("Kraskus-Crypto-Dev-Store", f"{KRASKUS}/Kraskus-Crypto-Dev-Store"),
}
SOURCE_REF = "origin/main"

# store repo -> (store id, store name, source channel, app filter)
STORES = {
    "Kraskus-Umbrel-Store": ("kraskus", "Kraskus Crypto", "main", lambda app: app != "mysterium-node"),
    "Kraskus-Umbrel-Dev-Store": ("kraskus", "Kraskus Crypto (Dev)", "dev", lambda app: app != "mysterium-node"),
    "Kraskus-Umbrel-Mysterium-Store": ("mysterium", "MystNodes by Kraskus", "main", lambda app: app == "mysterium-node"),
}

GPU_APPS = {"kraskus-common-foundry-gpu-miner"}

# Apps whose Umbrel package must not publish the UI port on the host: Umbrel
# reaches the UI only through its logged-in app proxy, and the app works there
# without a platform token (app-token fallback). Owner decision 2026-10-08
# (Kraskus Apps V3 Step 6). app id -> first version the rule applies to.
UNPUBLISHED_UI_APPS = {"kraskus-kaspa-solo": (0, 4, 0), "kraskus-bsv-solo": (0, 5, 0), "kraskus-prl-solo": (0, 5, 0), "kraskus-chta-solo": (0, 5, 0)}

# 5tratumOS-only manifest keys with no Umbrel meaning.
DROP_KEYS = {"services", "uiMode"}
# Umbrel manifest key order (matches upstream umbrel-apps convention).
KEY_ORDER = ["manifestVersion", "id", "name", "tagline", "icon", "category", "version", "port", "description",
             "developer", "website", "repo", "support", "gallery", "releaseNotes", "dependencies", "permissions",
             "path", "defaultUsername", "defaultPassword", "submitter", "submission"]
SKIP_FILES = {"5tratstore-app.yml", "5tratstore-review.yml"}


def git(repo, *args, binary=False):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode("utf-8")


def list_apps(repo):
    files = git(repo, "ls-tree", "-r", "--name-only", SOURCE_REF).splitlines()
    return sorted({f.split("/")[0] for f in files
                   if f.count("/") == 1 and f.endswith("/5tratstore-app.yml") and not f.startswith("templates/")})


def extract_app(repo, app, dest):
    data = git(repo, "archive", "--format=tar", SOURCE_REF, app, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        members = [m for m in t.getmembers() if os.path.basename(m.name) not in SKIP_FILES]
        t.extractall(dest, members=members, filter="tar")


def icon_url(store_repo, path):
    # Icons ship inside each Umbrel store repo (copied with the package) and are served from it.
    return f"https://raw.githubusercontent.com/kraskuscrypto/{store_repo}/{STORE_BRANCH}/{path}"


STORE_BRANCH = "main"
OVERRIDES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overrides.yml")
# Only store-listing copy may be overridden; IDs, versions and ports always come from the source.
OVERRIDABLE = {"name", "tagline", "description", "releaseNotes"}


def source_fingerprint(src):
    """Fingerprint of the source listing copy an override replaces (name, tagline, description)."""
    text = "\x1f".join(str(src.get(k, "")) for k in ("name", "tagline", "description"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_overrides():
    if not os.path.exists(OVERRIDES_FILE):
        return {}
    data = yaml.safe_load(open(OVERRIDES_FILE, encoding="utf-8")) or {}
    for app, fields in data.items():
        fields = fields or {}
        bad = set(fields) - OVERRIDABLE - {"replaces"}
        if bad:
            raise SystemExit(f"overrides.yml: {app}: only {sorted(OVERRIDABLE)} may be overridden, not {sorted(bad)}")
        if not fields.get("replaces"):
            raise SystemExit(f"overrides.yml: {app}: missing `replaces` (source copy fingerprints)")
    return data


def apply_override(src, app, override):
    """Return the override fields, refusing if the source copy changed since the override was written."""
    if not override:
        return {}
    fp = source_fingerprint(src)
    if fp not in override["replaces"]:
        raise SystemExit(f"overrides.yml: {app}: source listing copy changed (fingerprint {fp} not in "
                         f"{override['replaces']}); review the Umbrel copy, then add {fp} to `replaces`")
    return {k: v for k, v in override.items() if k != "replaces"}


def build_manifest(src, app, icon_url, gpu, overrides=None):
    m = {k: v for k, v in src.items() if k not in DROP_KEYS}
    m.update(apply_override(src, app, overrides))
    assert m["id"] == app, f"{app}: manifest id {m['id']!r} != directory"
    m["manifestVersion"] = 1
    m["icon"] = icon_url
    m.setdefault("gallery", [])
    if gpu:
        m["permissions"] = sorted(set(m.get("permissions") or []) | {"GPU"})
    ordered = {k: m[k] for k in KEY_ORDER if k in m}
    ordered.update({k: v for k, v in m.items() if k not in ordered})
    return ordered


def strip_nvidia_reservation(compose_text, app):
    """Remove the hard `deploy: resources: reservations: devices: - driver: nvidia` block.

    Text-level so every comment and the rest of the file stay byte-identical;
    the caller verifies the parsed result differs only by that block.
    """
    lines = compose_text.split("\n")
    out, i, removed = [], 0, 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "deploy:":
            indent = len(line) - len(line.lstrip())
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                j += 1
            block = "\n".join(lines[i:j])
            if "driver: nvidia" in block:
                # keep trailing blank/comment-free spacing intact
                while j > i + 1 and not lines[j - 1].strip():
                    j -= 1
                i = j
                removed += 1
                continue
        out.append(line)
        i += 1
    if removed != 1:
        raise SystemExit(f"{app}: expected exactly one NVIDIA deploy block, found {removed}")
    return "\n".join(out)


def version_tuple(value):
    try:
        return tuple(int(x) for x in str(value).split("."))
    except ValueError:
        return ()


def unpublish_ui_port(compose_text, app):
    """Remove the UI service's `ports:` block (the x-5tratumos-secure-proxy ui_service).

    Text-level so every comment and the rest of the file stay byte-identical;
    the caller verifies the parsed result differs only by that block.
    """
    data = yaml.safe_load(compose_text)
    proxy = data.get("x-5tratumos-secure-proxy") or {}
    ui, ui_port = proxy.get("ui_service"), proxy.get("ui_port")
    if not ui or ui not in data.get("services", {}):
        raise SystemExit(f"{app}: no x-5tratumos-secure-proxy ui_service to unpublish")
    lines = compose_text.split("\n")
    out, i, removed, in_ui = [], 0, 0, False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if indent == 2 and stripped.endswith(":") and not stripped.startswith("#"):
            in_ui = stripped[:-1] == ui
        if in_ui and indent == 4 and stripped == "ports:":
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > 4
                                      or lines[j].lstrip().startswith("- ")):
                if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) <= 4:
                    break
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            i = j
            removed += 1
            continue
        out.append(line)
        i += 1
    if removed != 1:
        raise SystemExit(f"{app}: expected exactly one ports block on UI service {ui}, found {removed}")
    ports = data["services"][ui].get("ports") or []
    if len(ports) != 1 or not str(ports[0]).split("/")[0].endswith(":%s" % ui_port):
        raise SystemExit(f"{app}: UI service {ui} publishes more than its UI port: {ports}")
    return "\n".join(out)


def check_ui_unpublish(before, after, app):
    b, a = yaml.safe_load(before), yaml.safe_load(after)
    ui = b["x-5tratumos-secure-proxy"]["ui_service"]
    b["services"][ui].pop("ports")
    assert a == b, f"{app}: compose changed beyond the UI service's ports"


def check_gpu_strip(before, after, app):
    b, a = yaml.safe_load(before), yaml.safe_load(after)
    for name, svc in b["services"].items():
        devs = (((svc.get("deploy") or {}).get("resources") or {}).get("reservations") or {}).get("devices") or []
        if any(d.get("driver") == "nvidia" for d in devs):
            assert set(svc["deploy"]) == {"resources"}, f"{app}/{name}: deploy has more than the GPU reservation"
            svc.pop("deploy")
    assert a == b, f"{app}: compose changed beyond the NVIDIA reservation"


def main(out_root):
    commits = {ch: git(path, "rev-parse", SOURCE_REF).strip() for ch, (_, path) in SOURCES.items()}
    overrides = load_overrides()
    report = {}
    for store_repo, (store_id, store_name, channel, wanted) in STORES.items():
        source_name, source_path = SOURCES[channel]
        commit = commits[channel]
        root = os.path.join(out_root, store_repo)
        os.makedirs(root, exist_ok=True)
        # Regenerate app dirs only; keep .git, tools/, README etc.
        for entry in os.listdir(root):
            p = os.path.join(root, entry)
            if os.path.isdir(p) and os.path.exists(os.path.join(p, "umbrel-app.yml")):
                shutil.rmtree(p)
        with open(os.path.join(root, "umbrel-app-store.yml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f'id: "{store_id}"\nname: "{store_name}"\n')

        apps = [a for a in list_apps(source_path) if wanted(a)]
        report[store_repo] = []
        for app in apps:
            extract_app(source_path, app, root)
            src = yaml.safe_load(git(source_path, "show", f"{SOURCE_REF}:{app}/5tratstore-app.yml"))
            icon_path = f"{app}/{src['icon']}"
            if not os.path.isfile(os.path.join(root, icon_path)):
                raise SystemExit(f"{store_repo}/{app}: icon {icon_path} is not in the package")
            gpu = app in GPU_APPS
            manifest = build_manifest(src, app, icon_url(store_repo, icon_path), gpu, overrides.get(app))
            with open(os.path.join(root, app, "umbrel-app.yml"), "w", encoding="utf-8", newline="\n") as f:
                f.write("# GENERATED by tools/umbrel-store-gen/generate.py from "
                        f"{source_name}@{commit[:12]}:{app}/5tratstore-app.yml - do not edit by hand.\n")
                yaml.safe_dump(manifest, f, sort_keys=False, allow_unicode=True, width=1000)
            if gpu:
                cpath = os.path.join(root, app, "docker-compose.yml")
                before = open(cpath, encoding="utf-8", newline="").read()
                after = strip_nvidia_reservation(before, app)
                check_gpu_strip(before, after, app)
                with open(cpath, "w", encoding="utf-8", newline="") as f:
                    f.write(after)
            min_version = UNPUBLISHED_UI_APPS.get(app)
            ui_unpublished = bool(min_version) and version_tuple(src["version"]) >= min_version
            if ui_unpublished:
                cpath = os.path.join(root, app, "docker-compose.yml")
                before = open(cpath, encoding="utf-8", newline="").read()
                after = unpublish_ui_port(before, app)
                check_ui_unpublish(before, after, app)
                with open(cpath, "w", encoding="utf-8", newline="") as f:
                    f.write(after)
            report[store_repo].append({"id": app, "version": manifest["version"], "gpu": gpu,
                                       "ui_unpublished": ui_unpublished})

        with open(os.path.join(root, "generated-from.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"generator": GENERATOR_VERSION, "source_repo": f"kraskuscrypto/{source_name}",
                       "source_ref": SOURCE_REF, "source_commit": commit, "store_id": store_id,
                       "apps": report[store_repo]}, f, indent=2)
            f.write("\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])

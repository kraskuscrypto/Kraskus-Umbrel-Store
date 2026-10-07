#!/usr/bin/env python3
"""Validate generated Umbrel stores against umbrelOS 2.0 (2.0.0-beta.1) rules.

Rules mirror umbreld source (modules/apps/{schema,app-repository,manifest-compatibility,apps}.ts,
modules/lan-ingress, legacy-compat/app-script) plus Kraskus policy:
  * Umbrel login is the platform auth boundary: no app may set PROXY_AUTH_ADD=false
  * no hard GPU reservations; GPU only through permissions: [GPU]

usage: validate.py <store-dir> [<store-dir> ...] [--offline]
exit 1 on any ERROR.
"""
import os
import re
import sys
import urllib.request

import yaml

UMBREL_VERSION = (2, 0, 0)
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
APP_ID = re.compile(r"^[a-zA-Z0-9-_]+$")
URL = re.compile(r"^https?://[^\s/$.?#].[^\s]*$")
# Ports umbrelOS 2.0 owns on the host (80/443 UI, 2000 app-auth, 22 ssh) and its
# hidden app-gateway listener range start.
UMBREL_RESERVED = {22, 80, 443, 2000}
GATEWAY_HIDDEN_BASE = 23000
# Variables exported to compose by legacy-compat/app-script + app-environment.ts.
UMBREL_VARS = {"APP_DATA_DIR", "APP_DATA_ROOT", "APP_DOMAIN", "APP_HIDDEN_SERVICE", "APP_ID", "APP_PASSWORD",
               "APP_PROXY_PORT", "APP_SEED", "APP_VERSION", "DEVICE_DOMAIN_NAME", "DEVICE_HOSTNAME",
               "GATEWAY_IP", "NETWORK_IP", "TOR_DATA_DIR", "TOR_ENTRYPOINT_SCRIPT", "TOR_HS_APP_DIR",
               "TOR_HS_PORTS", "UMBREL_ROOT", "UMBREL_DATA_DIR", "UMBREL_LEGACY_COMPAT_DIR", "UMBREL_TORRC"}
REQUIRED = {"manifestVersion": (int, float, str), "id": str, "name": str, "tagline": str, "category": str,
            "version": str, "port": int, "description": str, "website": str, "support": str, "gallery": list}
OPTIONAL = {"icon": str, "developer": (str, int), "repo": str, "path": str, "releaseNotes": str,
            "dependencies": list, "permissions": list, "submitter": (str, int), "submission": str,
            "defaultUsername": str, "defaultPassword": str}
KNOWN_KEYS = set(REQUIRED) | set(OPTIONAL) | {
    "disabled", "deterministicPassword", "optimizedForUmbrelHome", "torOnly", "requiresHttps", "installSize",
    "widgets", "defaultShell", "implements", "backupIgnore", "storage", "folderAccess", "environment"}
PERMISSIONS = {"GPU", "STORAGE_DOWNLOADS"}

OFFLINE = "--offline" in sys.argv
errors, warnings = [], []


def err(where, msg):
    errors.append(f"ERROR {where}: {msg}")


def warn(where, msg):
    warnings.append(f"WARN  {where}: {msg}")


def semver_ok(v):
    v = str(v)
    if re.fullmatch(r"\d+(\.\d+)?", v):  # umbreld coerces 1 / 1.1
        v = ".".join((v.split(".") + ["0", "0"])[:3])
    m = SEMVER.match(v)
    return m and tuple(int(x) for x in m.groups()) <= UMBREL_VERSION


def host_ports(svc):
    out = []
    for p in svc.get("ports") or []:
        if isinstance(p, dict):
            if p.get("published"):
                out.append((int(p["published"]), p.get("protocol", "tcp")))
            continue
        s = str(p)
        proto = "udp" if s.endswith("/udp") else "tcp"
        s = s.split("/")[0]
        parts = s.split(":")
        if len(parts) >= 2:
            out.append((int(parts[-2]), proto))
    return out


def check_icon(where, url):
    if not URL.match(url) or not url.startswith("https://"):
        err(where, f"icon must be an absolute https URL, got {url!r}")
        return
    if OFFLINE:
        return
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kraskus-umbrel-validate"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(16)
            if r.status != 200 or not (body.startswith(b"\x89PNG") or body.lstrip().startswith(b"<svg")
                                       or body.startswith(b"<?xml") or body[:3] == b"\xff\xd8\xff"):
                err(where, f"icon {url} -> HTTP {r.status}, not an image")
    except Exception as e:  # noqa: BLE001
        err(where, f"icon {url} unreachable: {e}")


def validate_store(root):
    name = os.path.basename(root.rstrip("/\\"))
    meta_path = os.path.join(root, "umbrel-app-store.yml")
    if not os.path.isfile(meta_path):
        err(name, "missing root umbrel-app-store.yml")
        return []
    meta = yaml.safe_load(open(meta_path, encoding="utf-8"))
    if not (isinstance(meta, dict) and isinstance(meta.get("id"), str) and isinstance(meta.get("name"), str)):
        err(name, "umbrel-app-store.yml needs string id and name")
        return []
    store_id = meta["id"]
    apps = sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "umbrel-app.yml")))
    if not apps:
        err(name, "no */umbrel-app.yml found")
    stray = [d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "5tratstore-app.yml"))]
    if stray:
        err(name, f"5tratumOS manifests present (must not ship in the Umbrel store): {stray}")

    ui_ports, published, rows = {}, {}, []
    for app in apps:
        w = f"{name}/{app}"
        m = yaml.safe_load(open(os.path.join(root, app, "umbrel-app.yml"), encoding="utf-8"))
        if not isinstance(m, dict):
            err(w, "umbrel-app.yml is not a mapping")
            continue
        for k, t in REQUIRED.items():
            if k not in m:
                err(w, f"missing required key {k}")
            elif not isinstance(m[k], t) or isinstance(m[k], bool):
                err(w, f"{k} has wrong type {type(m[k]).__name__}")
        for k, t in OPTIONAL.items():
            if k in m and not isinstance(m[k], t):
                err(w, f"{k} has wrong type {type(m[k]).__name__}")
        for k in ("name", "tagline", "description"):
            hit = re.search(r"5tratum|5stratum|workbench|cannot install", str(m.get(k, "")), re.I)
            if hit:
                warn(w, f"{k} has 5tratumOS-specific wording ({hit.group(0)!r}); add Umbrel copy in overrides.yml")
        for k in set(m) - KNOWN_KEYS:
            warn(w, f"key {k!r} is not an Umbrel manifest key (ignored by umbreld)")
        if "manifestVersion" in m and not semver_ok(m["manifestVersion"]):
            err(w, f"manifestVersion {m['manifestVersion']!r} invalid or newer than umbrelOS 2.0.0")
        if m.get("id") != app:
            err(w, f"id {m.get('id')!r} must equal directory name")
        if not APP_ID.match(str(m.get("id", ""))):
            err(w, "id has characters umbreld rejects")
        if not str(m.get("id", "")).startswith(store_id):
            err(w, f"id must start with store id {store_id!r} or Umbrel hides it")
        for k in ("website", "repo", "submission"):
            if m.get(k) and not URL.match(str(m[k])):
                err(w, f"{k} is not a URL")
        if not isinstance(m.get("gallery"), list):
            err(w, "gallery must be a list (umbrelOS 2.0 UI reads gallery.length unguarded)")
        bad_perm = set(m.get("permissions") or []) - PERMISSIONS
        if bad_perm:
            err(w, f"unknown permissions {bad_perm}")
        if "icon" not in m:
            err(w, "icon missing (Umbrel would fall back to the official gallery URL)")
        else:
            check_icon(w, m["icon"])
        port = m.get("port")
        if isinstance(port, int):
            if not 1024 <= port <= 65535 or port in UMBREL_RESERVED or port >= GATEWAY_HIDDEN_BASE and port < GATEWAY_HIDDEN_BASE + 1000:
                err(w, f"port {port} collides with umbrelOS-owned ports")
            if port in ui_ports:
                err(w, f"UI port {port} already used by {ui_ports[port]}")
            ui_ports[port] = app

        # --- compose
        cpath = os.path.join(root, app, "docker-compose.yml")
        if not os.path.isfile(cpath):
            err(w, "missing docker-compose.yml")
            continue
        text = open(cpath, encoding="utf-8").read()
        c = yaml.safe_load(text)
        svcs = c.get("services") or {}
        proxy = svcs.get("app_proxy")
        if not proxy:
            err(w, "no app_proxy service (Umbrel gateway needs APP_HOST/APP_PORT)")
        else:
            env = proxy.get("environment") or {}
            if isinstance(env, list):
                env = dict(e.split("=", 1) for e in env)
            host, aport = env.get("APP_HOST"), env.get("APP_PORT")
            if host not in svcs:
                err(w, f"APP_HOST {host!r} is not a compose service")
            if not str(aport).isdigit():
                err(w, f"APP_PORT {aport!r} is not a port")
            if str(env.get("PROXY_AUTH_ADD", "")).strip().lower() == "false":
                err(w, "PROXY_AUTH_ADD=false removes the Umbrel login boundary (policy)")
            for k in ("PROXY_AUTH_WHITELIST", "PROXY_AUTH_BLACKLIST"):
                if env.get(k):
                    warn(w, f"{k}={env[k]!r} - review against the platform-login policy")
        used = set(re.findall(r"\$\{?([A-Z_][A-Z0-9_]*)", re.sub(r"(?m)^\s*#.*$", "", text)))
        missing = used - UMBREL_VARS
        if missing:
            err(w, f"compose uses variables Umbrel does not provide: {sorted(missing)}")
        gpu_perm = "GPU" in (m.get("permissions") or [])
        for sname, s in svcs.items():
            sw = f"{w}:{sname}"
            if "build" in s:
                err(sw, "build: is not supported in store packages")
            if sname != "app_proxy" and "image" not in s:
                err(sw, "no image")
            elif sname != "app_proxy" and "@sha256:" not in s["image"]:
                warn(sw, f"image not digest-pinned: {s['image']}")
            devs = (((s.get("deploy") or {}).get("resources") or {}).get("reservations") or {}).get("devices") or []
            if any(d.get("driver") == "nvidia" for d in devs):
                err(sw, "hard NVIDIA reservation; use manifest permissions: [GPU]")
            if s.get("runtime") == "nvidia":
                err(sw, "runtime: nvidia; use manifest permissions: [GPU]")
            if s.get("privileged"):
                warn(sw, "privileged: true")
            for hp, proto in host_ports(s):
                if hp in UMBREL_RESERVED:
                    err(sw, f"publishes umbrelOS-owned host port {hp}")
                key = (hp, proto)
                if key in published and published[key] != app:
                    err(sw, f"host port {hp}/{proto} also published by {published[key]}")
                published.setdefault(key, app)
                if hp != port and hp in ui_ports and ui_ports[hp] != app:
                    err(sw, f"host port {hp} is the UI port of {ui_ports[hp]}")
        rows.append((app, m.get("version"), port, gpu_perm, sorted(f"{p}/{pr}" for (p, pr), a in published.items() if a == app)))

    # second pass: UI ports vs other apps' published ports (order independent)
    for (hp, proto), owner in published.items():
        if hp in ui_ports and ui_ports[hp] != owner:
            err(f"{name}/{owner}", f"publishes {hp}/{proto}, the UI port of {ui_ports[hp]}")
    return [(name, store_id, *r) for r in rows]


def main():
    stores = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows = []
    for s in stores:
        rows += validate_store(s)
    for r in rows:
        print("OK-CHECKED {:<32} id={:<10} {:<34} v{:<8} ui={:<6} gpu={!s:<5} host={}".format(*r))
    for w in warnings:
        print(w)
    for e in errors:
        print(e)
    print(f"\n{len(rows)} apps, {len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Tests for the trusted Umbrel deployment rules (Kraskus foundation 1.6.0, owner YES 2026-10-10).

generate.py declares KRASKUS_PLATFORM: umbrel on the configured token-validating
service only for apps whose UI host port it removes, and only when neither the
UI nor that service publishes a host port afterwards; it refuses a 5tratumOS
source compose that already contains KRASKUS_PLATFORM. validate.py rejects an
Umbrel app that sets KRASKUS_PLATFORM=umbrel while the UI or a declaring
service publishes host ports.

usage: python -m unittest discover -s tools/umbrel-store-gen -p "test_*.py" -v
(needs PyYAML, like the tools themselves)
"""
import difflib
import os
import shutil
import sys
import tempfile
import unittest

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import generate  # noqa: E402
import validate  # noqa: E402

QUANTUS = "kraskus-quantus-solo"

# A minimal 5tratumOS source compose with the Quantus 0.3.0 shape (comments kept on purpose).
SOURCE = """\
services:
  app_proxy:
    environment:
      APP_HOST: ui
      APP_PORT: 80

  node:
    image: example/node@sha256:%(d)s
    ports:
      # Quantus P2P.
      - "30333:30333/tcp"
      # Miner ingress: QUIC (UDP), LAN only.
      - "1935:9833/udp"
    networks:
      - public
      - internal

  adapter:
    image: example/adapter@sha256:%(d)s
    environment:
      LISTEN_PORT: "18430"
      # Foundation 1.1.2 app-token fallback.
      KRASKUS_APP_TOKEN_FILE: /data/state/app-token/token
    networks:
      - internal

  ui:
    image: example/ui@sha256:%(d)s
    ports:
      - "33076:80/tcp"
    networks:
      - public
      - internal

x-5tratumos-secure-proxy:
  version: 1
  ui_service: ui
  ui_port: 80
  token_services: [adapter]

networks:
  public:
    driver: bridge
  internal:
    driver: bridge
    internal: true
""" % {"d": "0" * 64}


def services(text):
    return yaml.safe_load(text)["services"]


class Generate(unittest.TestCase):
    def test_quantus_030_declares_the_deployment_on_the_adapter_only(self):
        text, ui_unpublished, service = generate.umbrel_compose(QUANTUS, "0.3.0", SOURCE)
        self.assertTrue(ui_unpublished)
        self.assertEqual(service, "adapter")
        svcs = services(text)
        self.assertEqual(svcs["adapter"]["environment"]["KRASKUS_PLATFORM"], "umbrel")
        self.assertNotIn("ports", svcs["adapter"])
        self.assertNotIn("ports", svcs["ui"])
        # Coin protocol ports stay published on the node.
        self.assertEqual(svcs["node"]["ports"], ["30333:30333/tcp", "1935:9833/udp"])
        declaring = [n for n, s in svcs.items() if "KRASKUS_PLATFORM" in ((s or {}).get("environment") or {})]
        self.assertEqual(declaring, ["adapter"])
        # Only the UI ports block and the declaration differ; every other byte (comments included) stays.
        diff = [l for l in difflib.ndiff(SOURCE.split("\n"), text.split("\n")) if l[:2] in ("- ", "+ ")]
        removed = [l[2:] for l in diff if l.startswith("- ")]
        added = [l[2:] for l in diff if l.startswith("+ ")]
        self.assertEqual(removed, ["    ports:", '      - "33076:80/tcp"'])
        self.assertEqual(added[-1], "      KRASKUS_PLATFORM: umbrel")
        self.assertTrue(all(l.strip().startswith("#") for l in added[:-1]))

    def test_later_versions_are_declared_too(self):
        self.assertEqual(generate.umbrel_compose(QUANTUS, "0.3.1", SOURCE)[2], "adapter")
        self.assertEqual(generate.umbrel_compose(QUANTUS, "1.0.0", SOURCE)[2], "adapter")

    def test_inert_below_the_ui_unpublish_version(self):
        text, ui_unpublished, service = generate.umbrel_compose(QUANTUS, "0.1.1", SOURCE)
        self.assertEqual((text, ui_unpublished, service), (SOURCE, False, None))

    def test_other_ui_unpublished_apps_get_no_declaration(self):
        for app, version in (("kraskus-kaspa-solo", "0.4.0"), ("kraskus-bsv-solo", "0.5.2"),
                             ("kraskus-prl-solo", "0.5.0"), ("kraskus-chta-solo", "0.5.0")):
            with self.subTest(app=app):
                text, ui_unpublished, service = generate.umbrel_compose(app, version, SOURCE)
                self.assertTrue(ui_unpublished)
                self.assertIsNone(service)
                self.assertNotIn("KRASKUS_PLATFORM", text)

    def test_zec_from_0_5_0_loses_only_the_ui_port(self):
        # Owner YES 2026-10-13: ZEC follows the V3 rule from 0.5.0 (first promoted: 0.5.1).
        zec = ("x-5tratumos-secure-proxy: {version: 1, ui_service: ui, ui_port: 8080, token_services: [kraskus]}\n"
               "services:\n"
               "  kraskus:\n"
               "    image: k\n"
               "    ports:\n"
               "      - 3335:3335\n"
               "  ui:\n"
               "    image: u\n"
               "    ports:\n"
               "      - 33062:8080/tcp\n")
        for version in ("0.5.0", "0.5.1"):
            with self.subTest(version=version):
                text, ui_unpublished, service = generate.umbrel_compose("kraskus-zec-solo", version, zec)
                self.assertTrue(ui_unpublished)
                self.assertIsNone(service)
                self.assertNotIn("33062", text)
                self.assertIn("3335:3335", text)
                self.assertNotIn("KRASKUS_PLATFORM", text)
        self.assertEqual(generate.umbrel_compose("kraskus-zec-solo", "0.4.0", zec), (zec, False, None))
        # The real ZEC compose writes compact lists (`- item` at the key's indent)
        # with comments around the UI ports block; only the block itself goes.
        compact = ("x-5tratumos-secure-proxy: {version: 1, ui_service: ui, ui_port: 8080, token_services: [kraskus]}\n"
                   "services:\n"
                   "  kraskus:\n"
                   "    image: k\n"
                   "    ports:\n"
                   "    - 3335:3335\n"
                   "  ui:\n"
                   "    image: u\n"
                   "    # published once on the manifest port\n"
                   "    ports:\n"
                   "    - 33062:8080/tcp\n"
                   "    # app-token fallback directory\n"
                   "    volumes:\n"
                   "    - ./t:/t:ro\n")
        text, ui_unpublished, _ = generate.umbrel_compose("kraskus-zec-solo", "0.5.1", compact)
        self.assertTrue(ui_unpublished)
        self.assertNotIn("33062", text)
        self.assertIn("    - 3335:3335\n", text)
        self.assertIn("    # app-token fallback directory\n    volumes:\n    - ./t:/t:ro\n", text)

    def test_apps_outside_the_ui_rule_are_untouched(self):
        self.assertEqual(generate.umbrel_compose("kraskus-xmr-solo", "9.9.9", SOURCE), (SOURCE, False, None))

    def test_default_is_no_declaration(self):
        self.assertEqual(generate.UMBREL_DEPLOYMENT_SERVICES, {QUANTUS: "adapter"})
        self.assertIsNone(generate.UMBREL_DEPLOYMENT_SERVICES.get("kraskus-kaspa-solo"))

    def test_source_with_the_declaration_is_refused(self):
        for bad in (SOURCE.replace("      LISTEN_PORT: \"18430\"\n", "      LISTEN_PORT: \"18430\"\n      KRASKUS_PLATFORM: umbrel\n"),
                    SOURCE.replace("      LISTEN_PORT: \"18430\"\n", "      LISTEN_PORT: \"18430\"\n      KRASKUS_PLATFORM: 5tratumos\n"),
                    SOURCE.replace("# Quantus P2P.", "# Quantus P2P. KRASKUS_PLATFORM is Umbrel-only."),
                    SOURCE.replace("    environment:\n      LISTEN_PORT", "    environment:\n      - KRASKUS_PLATFORM=umbrel\n      - LISTEN_PORT").replace(
                        '      LISTEN_PORT: "18430"\n', "")):
            for app, version in ((QUANTUS, "0.3.0"), (QUANTUS, "0.1.1"), ("kraskus-xmr-solo", "0.1.20")):
                with self.subTest(app=app, version=version), self.assertRaises(SystemExit) as ctx:
                    generate.umbrel_compose(app, version, bad)
                self.assertIn("KRASKUS_PLATFORM", str(ctx.exception))

    def test_longer_variable_names_are_not_the_declaration(self):
        ok = SOURCE.replace("KRASKUS_APP_TOKEN_FILE: /data/state/app-token/token",
                            "KRASKUS_APP_TOKEN_FILE: /data/state/app-token/token\n      KRASKUS_PLATFORM_TOKEN_FILE: /run/x")
        self.assertEqual(generate.umbrel_compose(QUANTUS, "0.3.0", ok)[2], "adapter")

    def test_refused_when_the_declaring_service_publishes_ports(self):
        bad = SOURCE.replace("  adapter:\n    image: example/adapter@sha256:%s\n" % ("0" * 64),
                             "  adapter:\n    image: example/adapter@sha256:%s\n    ports:\n      - \"18430:18430/tcp\"\n" % ("0" * 64))
        with self.assertRaises(SystemExit) as ctx:
            generate.umbrel_compose(QUANTUS, "0.3.0", bad)
        self.assertIn("adapter publishes host ports", str(ctx.exception))
        host = SOURCE.replace("    networks:\n      - internal\n\n  ui:", "    network_mode: host\n\n  ui:")
        with self.assertRaises(SystemExit):
            generate.umbrel_compose(QUANTUS, "0.3.0", host)

    def test_refused_when_the_ui_keeps_another_port(self):
        bad = SOURCE.replace('      - "33076:80/tcp"\n', '      - "33076:80/tcp"\n      - "33077:81/tcp"\n')
        with self.assertRaises(SystemExit):
            generate.umbrel_compose(QUANTUS, "0.3.0", bad)

    def test_refused_without_an_environment_block(self):
        bad = SOURCE.replace('    environment:\n      LISTEN_PORT: "18430"\n      # Foundation 1.1.2 app-token fallback.\n'
                             '      KRASKUS_APP_TOKEN_FILE: /data/state/app-token/token\n', "")
        with self.assertRaises(SystemExit) as ctx:
            generate.umbrel_compose(QUANTUS, "0.3.0", bad)
        self.assertIn("no environment block", str(ctx.exception))

    def test_list_form_environment(self):
        src = SOURCE.replace('      LISTEN_PORT: "18430"\n      # Foundation 1.1.2 app-token fallback.\n'
                             '      KRASKUS_APP_TOKEN_FILE: /data/state/app-token/token\n',
                             '      - LISTEN_PORT=18430\n      - KRASKUS_APP_TOKEN_FILE=/data/state/app-token/token\n')
        text, _, service = generate.umbrel_compose(QUANTUS, "0.3.0", src)
        self.assertEqual(service, "adapter")
        self.assertIn("KRASKUS_PLATFORM=umbrel", services(text)["adapter"]["environment"])


class Validate(unittest.TestCase):
    def setUp(self):
        validate.errors.clear()
        validate.warnings.clear()
        self.addCleanup(validate.errors.clear)
        self.addCleanup(validate.warnings.clear)

    def check(self, text):
        validate.errors.clear()
        validate.warnings.clear()
        validate.check_umbrel_deployment("store/app", yaml.safe_load(text))
        return list(validate.errors), list(validate.warnings)

    def generated(self):
        return generate.umbrel_compose(QUANTUS, "0.3.0", SOURCE)[0]

    def test_generated_quantus_compose_passes(self):
        self.assertEqual(self.check(self.generated()), ([], []))

    def test_source_compose_without_the_declaration_is_not_this_rule(self):
        self.assertEqual(self.check(SOURCE), ([], []))  # the UI port is fine without the declaration

    def test_ui_host_port_with_the_declaration_is_rejected(self):
        bad = SOURCE.replace("      LISTEN_PORT: \"18430\"\n", "      LISTEN_PORT: \"18430\"\n      KRASKUS_PLATFORM: umbrel\n")
        errors, _ = self.check(bad)
        self.assertEqual(len(errors), 1)
        self.assertIn("store/app:ui", errors[0])
        self.assertIn("UI service publishes host ports", errors[0])

    def test_declaring_service_with_host_ports_is_rejected(self):
        bad = self.generated().replace("  adapter:\n", "  adapter:\n    ports:\n      - \"127.0.0.1:18430:18430\"\n", 1)
        errors, _ = self.check(bad)
        self.assertEqual(len(errors), 1)
        self.assertIn("store/app:adapter", errors[0])
        bad = self.generated().replace("  adapter:\n", "  adapter:\n    ports:\n      - \"18430\"\n", 1)
        self.assertEqual(len(self.check(bad)[0]), 1)  # an ephemeral host port is still a host port
        bad = self.generated().replace("  adapter:\n", "  adapter:\n    network_mode: host\n", 1)
        self.assertEqual(len(self.check(bad)[0]), 1)

    def test_every_declaring_service_is_checked(self):
        bad = self.generated().replace('      - "1935:9833/udp"\n', '      - "1935:9833/udp"\n    environment:\n      KRASKUS_PLATFORM: umbrel\n')
        errors, _ = self.check(bad)
        self.assertEqual(len(errors), 1)
        self.assertIn("store/app:node", errors[0])

    def test_app_proxy_host_is_the_ui_without_a_secure_proxy_block(self):
        data = yaml.safe_load(SOURCE.replace("      LISTEN_PORT: \"18430\"\n", "      LISTEN_PORT: \"18430\"\n      KRASKUS_PLATFORM: umbrel\n"))
        data.pop("x-5tratumos-secure-proxy")
        validate.check_umbrel_deployment("store/app", data)
        self.assertEqual(len(validate.errors), 1)
        self.assertIn("store/app:ui", validate.errors[0])

    def test_other_values_warn_only(self):
        text = SOURCE.replace("      LISTEN_PORT: \"18430\"\n", "      LISTEN_PORT: \"18430\"\n      KRASKUS_PLATFORM: other\n")
        errors, warnings = self.check(text)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)

    def test_full_store_validation(self):
        root = tempfile.mkdtemp(prefix="umbrel-gen-test-")
        self.addCleanup(shutil.rmtree, root, True)
        store = os.path.join(root, "Kraskus-Umbrel-Dev-Store")
        os.makedirs(os.path.join(store, QUANTUS))
        with open(os.path.join(store, "umbrel-app-store.yml"), "w") as f:
            f.write('id: "kraskus"\nname: "test"\n')
        with open(os.path.join(store, QUANTUS, "icon.svg"), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        manifest = {"manifestVersion": 1, "id": QUANTUS, "name": "Q", "tagline": "t", "category": "crypto",
                    "version": "0.3.0", "port": 33076, "description": "d", "website": "https://example.com",
                    "support": "https://example.com", "gallery": [],
                    "icon": "https://raw.githubusercontent.com/kraskuscrypto/Kraskus-Umbrel-Dev-Store/main/%s/icon.svg" % QUANTUS}
        with open(os.path.join(store, QUANTUS, "umbrel-app.yml"), "w") as f:
            yaml.safe_dump(manifest, f)
        compose = os.path.join(store, QUANTUS, "docker-compose.yml")
        with open(compose, "w", newline="") as f:
            f.write(self.generated())
        validate.validate_store(store)
        self.assertEqual(validate.errors, [])
        with open(compose, "w", newline="") as f:  # the declaration on the 5tratumOS compose (UI port kept)
            f.write(SOURCE.replace("      LISTEN_PORT: \"18430\"\n", "      LISTEN_PORT: \"18430\"\n      KRASKUS_PLATFORM: umbrel\n"))
        validate.errors.clear()
        validate.validate_store(store)
        self.assertEqual(len([e for e in validate.errors if "KRASKUS_PLATFORM" in e]), 1)


class HoldsTest(unittest.TestCase):
    """holds.yml pins an app's package to a full source commit (icon still from SOURCE_REF)."""

    def write(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        p = os.path.join(d, "holds.yml")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_missing_file_means_no_holds(self):
        self.assertEqual(generate.load_holds(os.path.join(tempfile.gettempdir(), "no-such-holds.yml")), {})

    def test_full_commit_is_accepted(self):
        sha = "0e33c0875f0939b81e07bd41380224bfe7c0bc7e"
        holds = generate.load_holds(self.write(f"Kraskus-Umbrel-Store:\n  kraskus-chta-solo: {sha}\n"))
        self.assertEqual(holds, {"Kraskus-Umbrel-Store": {"kraskus-chta-solo": sha}})

    def test_short_commit_is_refused(self):
        with self.assertRaises(SystemExit):
            generate.load_holds(self.write("Kraskus-Umbrel-Store:\n  kraskus-chta-solo: 0e33c08\n"))

    def test_unknown_store_is_refused(self):
        with self.assertRaises(SystemExit):
            generate.load_holds(self.write(
                "Some-Other-Store:\n  kraskus-chta-solo: 0e33c0875f0939b81e07bd41380224bfe7c0bc7e\n"))

    def test_repo_holds_file_loads(self):
        holds = generate.load_holds()
        self.assertEqual(set(holds), {"Kraskus-Umbrel-Store", "Kraskus-Umbrel-Dev-Store"})
        self.assertEqual({a for h in holds.values() for a in h}, {"kraskus-chta-solo"})


if __name__ == "__main__":
    unittest.main()

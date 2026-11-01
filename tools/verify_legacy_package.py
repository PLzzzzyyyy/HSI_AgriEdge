"""Read-only package integrity verification; no product imports or device access."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


def canonical(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Check:
    def __init__(self, root):
        self.root = root.resolve()
        self.errors = []
        self.pending = []
        self.checked = 0
        self.cache = {}

    def path(self, relative):
        if not isinstance(relative, str) or "\\" in relative or ":" in relative:
            raise ValueError("Invalid relative path: " + repr(relative))
        value = PurePosixPath(relative)
        if value.is_absolute() or not value.parts or ".." in value.parts:
            raise ValueError("Unsafe relative path: " + relative)
        result = self.root.joinpath(*value.parts)
        if not result.resolve().is_relative_to(self.root):
            raise ValueError("Path escapes package: " + relative)
        return result

    def load(self, relative):
        with self.path(relative).open(encoding="utf-8-sig") as stream:
            return json.load(stream)

    def digest(self, path):
        key = path.resolve()
        if key not in self.cache:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            self.cache[key] = digest.hexdigest()
        return self.cache[key]

    def equal(self, actual, expected, label):
        if actual != expected:
            self.errors.append(label + " mismatch")

    def record(self, row, label, optional=False, path_key="path", prefix=""):
        relative = prefix + row[path_key]
        path = self.path(relative)
        if not path.is_file():
            message = label + ": missing " + relative
            (self.pending if optional else self.errors).append(message)
            return
        expected_bytes = row.get("bytes", row.get("size"))
        if expected_bytes is not None:
            self.equal(path.stat().st_size, expected_bytes, label + " size " + relative)
        expected_sha = row["sha256"]
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
            raise ValueError("Invalid SHA256 for " + relative)
        self.equal(self.digest(path), expected_sha.lower(), label + " SHA256 " + relative)
        self.checked += 1

    def records(self, rows, label, optional=False, path_key="path", prefix=""):
        if not isinstance(rows, list) or not rows:
            raise ValueError("Empty or invalid " + label)
        seen = set()
        for row in rows:
            relative = row[path_key]
            key = relative.casefold()
            if key in seen:
                raise ValueError("Duplicate " + label + " path: " + relative)
            seen.add(key)
            self.record(row, label, optional, path_key, prefix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-data", action="store_true", help="Require all exported data files")
    args = parser.parse_args()
    check = Check(Path(__file__).resolve().parent)
    release_id = None
    data_count = 0
    manifest_has_data_inventory = False
    try:
        exported = check.load("package_manifest.json")
        check.records(exported["files"], "package")

        deployment = check.load("firmware/keys_20261018/deployment.json")
        bundle_relative = deployment["bundle"].rstrip("/")
        bundle = check.path(bundle_relative)
        if not bundle.is_relative_to(check.root / "build" / "host"):
            raise ValueError("Unexpected deployment bundle directory")
        manifest = check.load(bundle_relative + "/manifest.json")
        facts = manifest["facts"]
        release_id = manifest["release_id"]
        check.equal(manifest["app_id"], "gcs_r1_abi4", "app_id")
        check.equal(facts["app_id"], manifest["app_id"], "facts app_id")
        check.equal(facts["engine_abi"], 4, "engine ABI")
        check.equal(canonical(facts), release_id, "release identity")
        check.equal(deployment["release_id"], release_id, "deployed release identity")
        check.equal(canonical(manifest["sources"]), facts["source_set_sha256"], "source set identity")
        check.equal(canonical(manifest["assets"]), facts["asset_set_sha256"], "asset set identity")
        check.records(manifest["sources"], "release sources")
        check.records(manifest["assets"], "release assets")
        check.records(manifest["files"], "bundled app sources", path_key="destination", prefix=bundle_relative + "/")
        check.record(manifest["local_demo_elf"], "local demo ELF")

        expected_names = {"tt_gcs_keys.bit", "tt_gcs_keys.xsa", "fsbl_a53.elf", "gcs_keys.elf"}
        if set(deployment["files"]) != expected_names:
            raise ValueError("Deployment must contain exactly the four expected firmware files")
        for name, digest in deployment["files"].items():
            check.record({"path": "firmware/keys_20261018/" + name, "sha256": digest}, "deployed firmware")
        check.equal(deployment["files"]["tt_gcs_keys.xsa"], facts["hardware_xsa_sha256"], "hardware XSA identity")
        check.equal(deployment["files"]["gcs_keys.elf"], manifest["local_demo_elf"]["sha256"], "deployed ELF identity")
        if "hardware" in manifest:
            hardware = manifest["hardware"]
            if "xsa" in hardware:
                check.record(hardware["xsa"], "release hardware XSA")
                check.equal(hardware["xsa"]["sha256"], facts["hardware_xsa_sha256"], "manifest XSA identity")
        if "data_inventory" in manifest:
            manifest_has_data_inventory = True
            original_rows = manifest["data_inventory"]["files"]
            check.equal(canonical(original_rows), facts["data_set_sha256"], "release data inventory identity")
            for row in original_rows:
                record = dict(row, path="data/" + row["destination"])
                check.record(record, "release data", optional=not args.with_data)

        data_manifest_path = "data_manifest.json"
        if not check.path(data_manifest_path).is_file() and check.path("data/data_manifest.json").is_file():
            data_manifest_path = "data/data_manifest.json"
        data_manifest = check.load(data_manifest_path)
        data_rows = data_manifest["files"]
        for row in data_rows:
            if not row["path"].startswith("data/"):
                raise ValueError("Data inventory paths must start with data/")
        data_count = len(data_rows)
        check.records(data_rows, "exported data", optional=not args.with_data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        check.errors.append(str(exc))

    status = "FAIL" if check.errors else (
        "PASS_SOURCE_FIRMWARE_DATA_NOT_INSTALLED" if check.pending else "PASS_PACKAGE_FILES"
    )
    print(json.dumps({
        "result": status,
        "scope": "FILE_INTEGRITY_ONLY_NOT_PRODUCT_HARDWARE_OR_PORTABILITY_ACCEPTANCE",
        "release_id": release_id,
        "checks": check.checked,
        "data_manifest_entries": data_count,
        "release_manifest_contains_data_inventory": manifest_has_data_inventory,
        "data_note": (
            "Original demo manifest has no data_inventory; exported data are checked against data_manifest.json."
            if not manifest_has_data_inventory else "Release and exported data inventories checked."
        ),
        "pending_data_count": len(check.pending),
        "pending_data_examples": check.pending[:5],
        "errors": check.errors,
    }, indent=2, ensure_ascii=False))
    return 1 if check.errors else 0


if __name__ == "__main__":
    sys.exit(main())

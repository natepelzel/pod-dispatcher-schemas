#!/usr/bin/env python3
"""Validate every schema YAML in the repo root against pod-dispatcher.schema.json,
plus semantic checks the JSON Schema can't express:

  * schema id matches the filename
  * URL pattern regexes compile (Java named-group syntax, sanity-checked here)
  * resolver param templates only reference captured groups
  * target link templates only reference canonical variables + known filters
  * manifest.json lists exactly the schema files present

Requires: pyyaml, jsonschema
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT
META_SCHEMA = json.loads((ROOT / "pod-dispatcher.schema.json").read_text(encoding="utf-8"))

CANONICAL_VARS = {"feedUrl", "itunesId", "episodeGuid", "episodeTitle", "episodeUrl"}
KNOWN_FILTERS = {"urlencode", "strip-scheme", "base64url"}
TEMPLATE_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)(?:\|([a-z0-9-]+))?\}")
JAVA_GROUP_RE = re.compile(r"\(\?<([A-Za-z][A-Za-z0-9]*)>")


def compile_java_regex(pattern: str) -> str | None:
    """Sanity-compile a Java/Kotlin regex by converting (?<n>) to (?P<n>).
    Returns an error message, or None if it compiles."""
    try:
        re.compile(JAVA_GROUP_RE.sub(r"(?P<\1>", pattern))
        return None
    except re.error as exc:
        return str(exc)


def template_refs(template: str):
    """Yields (variable, filter) pairs referenced by a template string."""
    for match in TEMPLATE_RE.finditer(template):
        yield match.group(1), match.group(2)


def check_file(path: pathlib.Path, validator: Draft202012Validator) -> list[str]:
    errors: list[str] = []

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]

    for error in sorted(validator.iter_errors(data), key=lambda e: e.json_path):
        errors.append(f"{error.json_path}: {error.message}")
    if errors:
        return errors  # structural problems make the semantic checks unreliable

    if data["id"] != path.stem:
        errors.append(f"id '{data['id']}' does not match filename '{path.stem}'")

    source = data.get("source")
    if source:
        captures: set[str] = set()
        for i, pattern in enumerate(source["patterns"]):
            for label, regex in [("path", pattern["path"])] + [
                (f"query.{k}", v) for k, v in pattern.get("query", {}).items()
            ]:
                err = compile_java_regex(regex)
                if err:
                    errors.append(f"patterns[{i}].{label}: regex does not compile: {err}")
                captures.update(JAVA_GROUP_RE.findall(regex))

        resolve_templates = {
            f"params.{k}": v for k, v in source["resolve"].get("params", {}).items()
        }
        if "url" in source["resolve"]:
            resolve_templates["url"] = source["resolve"]["url"]
        for key, template in resolve_templates.items():
            for var, _ in template_refs(template):
                if var not in captures:
                    errors.append(
                        f"resolve.{key}: references '{{{var}}}' which no pattern captures"
                    )

    target = data.get("target")
    if target:
        for level in ("show", "episode"):
            for i, template in enumerate(target["links"].get(level, [])):
                for var, flt in template_refs(template):
                    if var not in CANONICAL_VARS:
                        errors.append(
                            f"links.{level}[{i}]: unknown variable '{{{var}}}' "
                            f"(canonical variables: {', '.join(sorted(CANONICAL_VARS))})"
                        )
                    if flt is not None and flt not in KNOWN_FILTERS:
                        errors.append(f"links.{level}[{i}]: unknown filter '{flt}'")

    return errors


def check_manifest(schema_files: list[pathlib.Path]) -> list[str]:
    manifest_path = SCHEMAS_DIR / "manifest.json"
    if not manifest_path.exists():
        return ["manifest.json is missing"]
    try:
        listed = set(json.loads(manifest_path.read_text(encoding="utf-8"))["files"])
    except (json.JSONDecodeError, KeyError) as exc:
        return [f"manifest.json is invalid: {exc}"]

    actual = {p.name for p in schema_files}
    errors = []
    for missing in sorted(actual - listed):
        errors.append(f"manifest.json: missing entry for {missing}")
    for stale in sorted(listed - actual):
        errors.append(f"manifest.json: lists {stale} which does not exist")
    return errors


def main() -> int:
    validator = Draft202012Validator(META_SCHEMA)
    schema_files = sorted(
        p for p in SCHEMAS_DIR.iterdir() if p.suffix in (".yml", ".yaml")
    )
    if not schema_files:
        print("No schema files found in the repo root", file=sys.stderr)
        return 1

    failed = False
    for path in schema_files:
        errors = check_file(path, validator)
        if errors:
            failed = True
            print(f"FAIL {path.relative_to(ROOT)}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"ok   {path.relative_to(ROOT)}")

    manifest_errors = check_manifest(schema_files)
    if manifest_errors:
        failed = True
        for error in manifest_errors:
            print(f"  - {error}")
    else:
        print("ok   manifest.json")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

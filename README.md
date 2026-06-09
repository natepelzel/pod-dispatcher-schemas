# Pod Dispatcher schemas

The shared, platform-neutral schema repository for Pod Dispatcher
([pod-dispatcher-android](https://github.com/natepelzel/pod-dispatcher-android);
an iOS app is planned): one
declarative YAML file per podcast app/platform describing how to *parse* its
share links (`source`), how to *deep link* into it (`target`), or both.

The native apps (Android today, iOS planned) consume this repository two ways:

* **Bundled** — as a git submodule, so the engine works offline out of the box.
* **Over-the-air** — apps re-download `manifest.json` and the files it lists
  from this repository's `main` branch, no app release required.

Schemas are purely declarative — regex patterns and string templates, no
executable code. See [SCHEMA.md](SCHEMA.md) for the full format reference and
contribution checklist.

## Layout

```
*.yml                        One schema per app/platform (the payload)
manifest.json                Index of schema files — what the apps fetch/bundle
pod-dispatcher.schema.json   JSON Schema the YAML files are validated against
SCHEMA.md                    Format reference + contribution guide
tools/                       CI validator
```

The schema files live at the repository root deliberately: the submodule mount
point *is* the asset directory the apps bundle.

## Validating

```bash
pip install -r tools/requirements.txt
python tools/validate_schemas.py
```

CI runs the same validator on every push and pull request.

## Contributing

Coverage grows by community contribution: add a YAML file, list it in
`manifest.json`, run the validator, open a PR. Full checklist in
[SCHEMA.md](SCHEMA.md#contribution-checklist).

## License

[Apache-2.0](LICENSE)

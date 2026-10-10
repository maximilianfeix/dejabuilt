# Changelog

Notable changes to this project. Versions follow [Semantic Versioning](https://semver.org).

## 0.2.1 - 2026-10-10

- The script no longer copies the whole environment. It reads `GH_TOKEN` and
  `GITHUB_TOKEN` and nothing else, and a test enforces that.

## 0.2.0 - 2026-10-10

- The plugin now lives in `plugin/`. An installation carries the skill, a short
  README, the licence and the icon, and no longer the tests, examples and CI
  files. Installing by hand copies `plugin/skills/dejabuilt`.
- Listing fields in the manifest: icon, documentation and support links.

## 0.1.1 - 2026-10-10

- Privacy policy (`PRIVACY.md`), linked from the plugin manifest and the README.
- Plugin icon.
- Two more example reports, and the install path through the skills CLI.
- Fixed the wording of the `OPEN` reason when one or two repositories were found.

## 0.1.0 - 2026-10-10

First release.

- `search`: several queries per run, merged by repository, sorted by stars.
- `inspect`: latest releases, asset names and platform hints from assets and
  README headings.
- `verdict`: `TAKEN`, `CONTESTED`, `ORPHANED`, `LOW_TRACTION`, `OPEN` and
  `INCONCLUSIVE`, computed by a fixed policy (version 1).
- Reports as Markdown or JSON, with the queries, the thresholds and what was not
  checked.
- Read-only GitHub client: fixed host, refused redirects, bounded rate-limit
  retries, token never shown.
- Installs as a Claude Code plugin or by copying the skill folder.

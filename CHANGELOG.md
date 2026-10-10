# Changelog

Notable changes to this project. Versions follow [Semantic Versioning](https://semver.org).

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

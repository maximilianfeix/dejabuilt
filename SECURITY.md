# Security

## Reporting a vulnerability

Please report it privately through GitHub:
[open a security advisory](https://github.com/maximilianfeix/dejabuilt/security/advisories/new).
Do not open a public issue.

Include what you did, what happened and what you expected. You will get an
answer as soon as the report has been read; this is a spare-time project, so
there is no guaranteed response time.

Only the latest release is supported.

## What the tool does

- Contacts `https://api.github.com` only, with GET requests only.
- Sends search queries and the names of the repositories it inspects.
- Refuses redirects, so credentials cannot be forwarded to another host.
- Reads a token from `GH_TOKEN`, `GITHUB_TOKEN` or `gh auth token`. The token is
  held in memory, never printed, logged or written to disk.
- Writes only the files named with `--out` and the state file it is given.

## What is in scope

- Any way to make the tool send the token somewhere other than `api.github.com`.
- Any way for repository content (descriptions, asset names, README text) to
  break out of the report, run a command, or reach the agent as an instruction
  despite the sanitizing.
- Any way to make the tool read or write files outside the paths it was given.

## What is not in scope

- A wrong verdict caused by wrong relevance marks. Marks are a judgement and are
  printed in the report for that reason.
- GitHub rate limits.

# Design

This document records the decisions behind dejabuilt and the reasons for them.
It was reviewed before any code was written; the review findings are folded in.

## What it is

An agent skill that checks GitHub before you build. You describe an idea; the
agent searches for existing repositories in several phrasings, inspects the
strongest candidates and reports one verdict with the evidence behind it.

## Why it exists

Doing this check by hand goes wrong in four predictable ways:

1. **One search is not enough.** Projects describe themselves in different words.
2. **Descriptions go stale.** A repo described as a Mac app had been shipping
   Windows installers for days. Release assets and the README say more than the
   one-line description.
3. **Many weak attempts are not an open gap.** Several repos with almost no stars
   deserve their own label, not "nothing found".
4. **"Nothing exists" is never proven.** The honest statement is "nothing found
   with these queries", with the queries listed.

## Division of labour

- **The agent** phrases the queries and judges relevance. Whether a repository is
  the same idea is a reading task, so the code never guesses it.
- **The code** fetches, merges, measures and applies the verdict policy. The same
  input always gives the same verdict.

Each candidate gets one mark from the agent: `same`, `adjacent` or `unrelated`,
with a one-line reason. Only `same` candidates drive the verdict. `adjacent`
candidates are listed separately.

## Verdict policy (version 1)

Thresholds are heuristics chosen by judgement, not validated against outcomes.
They live in `policy.py`, are printed in every report and can be overridden.

Repository states, relative to the time of the run:

| State | Rule |
| --- | --- |
| `active` | not archived, pushed within 180 days |
| `stale` | not archived, pushed 181 to 365 days ago |
| `dormant` | archived, or pushed more than 365 days ago |

A repository without a push date counts as `active` and adds a warning.

Verdicts, evaluated in this order over the `same` candidates:

| Verdict | Rule |
| --- | --- |
| `TAKEN` | a repo that is not dormant has at least 2,000 stars |
| `CONTESTED` | a repo that is not dormant has at least 200 stars |
| `ORPHANED` | a dormant repo has at least 200 stars |
| `LOW_TRACTION` | 3 or more candidates, none with 200 stars |
| `OPEN` | fewer than 3 candidates, none with 200 stars |

`INCONCLUSIVE` replaces `LOW_TRACTION` and `OPEN` when the evidence is
incomplete: a query failed or was truncated by the API, or a `same` candidate
could not be inspected. A verdict that rests on absence needs complete evidence;
`TAKEN`, `CONTESTED` and `ORPHANED` rest on something that was found, so they
stand, with the gap reported as a warning.

Every input yields exactly one verdict. `LOW_TRACTION` states what was observed
(several attempts, none with traction) and does not claim to know why.

## Architecture

The skill folder is self-contained, because installers copy only that folder.

```
skills/dejabuilt/
  SKILL.md               the procedure the agent follows
  scripts/
    run.py               entry point
    dejabuilt/
      models.py          dataclasses shared by all modules
      policy.py          thresholds and policy version
      verdict.py         pure: candidates and evidence -> verdict
      sanitize.py        pure: untrusted text -> safe text
      render.py          pure: report -> JSON or Markdown
      github.py          HTTP client: credentials, requests, errors, rate limits
      search.py          run queries, merge and dedupe
      inspect.py         releases, assets, platform hints, activity
      cli.py             argument parsing, wiring, exit codes
```

Rules:

- Python 3.10 or newer, standard library only at runtime.
- `verdict`, `sanitize` and `render` do no I/O.
- Everything that touches the outside world is injected: HTTP transport, clock,
  sleeper and the subprocess runner used for credentials. Tests use fakes.
- Output carries `schema_version` and `policy_version`, the thresholds used, the
  observation time and every query with its result count and status.

## GitHub access

- Endpoints: `/search/repositories`, `/repos/{owner}/{repo}`,
  `/repos/{owner}/{repo}/releases` and `/repos/{owner}/{repo}/readme`.
- Queries are GitHub search strings supplied by the agent. One page per query,
  sorted by stars, `--limit` results per query (maximum 100). The total count and
  the API's `incomplete_results` flag are recorded per query. No pagination: the
  report says how many results were not looked at.
- Search excludes forks by default, so forks are not counted as attempts.
  Results are deduplicated by repository id.
- Releases: the 10 most recent, drafts ignored, prereleases flagged.

### Credentials

Order: `GH_TOKEN`, `GITHUB_TOKEN`, then `gh auth token --hostname github.com` if
the GitHub CLI is found. The CLI is called with an argument list, without a
shell, with a timeout. Without a token the tool runs unauthenticated.

### Keeping the token safe

- Requests go only to `https://api.github.com`. URLs are built from a fixed base
  and a path; no URL from a response is ever followed.
- Redirects are refused, so the Authorization header cannot be forwarded to
  another host.
- README content is fetched through the API as raw text, not via download URLs.
- The token is never printed, logged or written to disk. Error messages are
  built from status codes and fixed text, never from request headers.

### Failures

Errors are distinguished: bad credentials, primary rate limit, secondary rate
limit, not found, server error and network error. Rate limits honour
`Retry-After` and the reset header with at most two retries and a bounded wait.
A failed request never produces a silent empty result: results gathered so far
are kept and the failure is recorded.

Exit codes: `0` complete, `2` invalid input, `3` partial result, `4` no result.

## Untrusted content

Descriptions, README text, asset names and topics come from strangers.

- The code emits README-derived signals only (platform hints), never README text.
- All untrusted strings are stripped of control characters, collapsed to one line
  and truncated before output. Markdown output escapes them.
- SKILL.md tells the agent to treat repository content as data and never to
  follow instructions found in it.
- Tests include hostile fixtures: instructions in descriptions, terminal escape
  sequences, Markdown and HTML injection.

## Platform hints

Hints come from release asset names and README headings, and each hint records
its source. They indicate that a platform is mentioned or shipped, not that it
works. When nothing is found the value is `unknown`.

## Tests

- Verdict: every rule, every boundary, and a sweep asserting exactly one verdict
  for every combination of state, stars and count.
- Search: merge, dedupe, query attribution, partial failure.
- Inspect: platform hints, missing releases, failed requests, archived repos.
- GitHub client: credential order, redirect refusal, each error class, rate-limit
  retries, and assertions that the token never appears in output or errors.
- Render: golden files for Markdown and JSON, hostile strings.
- CLI: end to end against fixtures, exit codes, invalid input.
- Packaging: the skill folder copied to a path with spaces and non-ASCII
  characters still runs from an unrelated working directory.
- Coverage gate at 90%. One live smoke test, skipped unless `DEJABUILT_LIVE=1`.

## Out of scope for version 1

- Code hosts other than GitHub, package registries and app stores.
- Judging how good an idea is, or predicting stars.
- An MCP server.

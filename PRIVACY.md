# Privacy

dejabuilt is a script that runs on your computer. There is no dejabuilt server,
no account and no analytics. The author receives nothing from your use of it.

## What leaves your machine

The script talks to one service: the GitHub API at `https://api.github.com`.
It sends:

- the search queries your agent wrote for your idea,
- the names of the repositories it inspects,
- your GitHub token, if one is available, in the `Authorization` header.

It sends these to GitHub and nowhere else. Requests are GET only, and redirects
are refused, so the token cannot be forwarded to another host. GitHub handles
these requests under the
[GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

## What it reads

- Public repository metadata from GitHub: names, descriptions, star counts,
  dates, release tags, release asset names and README headings. Repository names
  include the account name of the owner.
- A GitHub token from the `GH_TOKEN` or `GITHUB_TOKEN` environment variable, or
  from `gh auth token` if the GitHub CLI is installed. The token is optional. It
  is kept in memory for the duration of the run and is never printed, logged or
  written to a file.

It does not read your source code, your conversation with the agent, the
agent's memory or any other file on your machine.

## What it stores

Only the files you ask for: the state file and the report, in the location you
choose. They contain the queries and the public repository metadata listed
above. They stay on your machine until you delete them.

## Retention

The author retains nothing, because nothing is sent to the author.

## Your agent

dejabuilt runs inside an AI coding agent. What that agent and its provider do
with your conversation is governed by their own terms, not by this document.

## Contact

Questions about this document: open an issue at
<https://github.com/maximilianfeix/dejabuilt/issues>. Security problems: see
[SECURITY.md](SECURITY.md).

Last updated: 2026-10-10.

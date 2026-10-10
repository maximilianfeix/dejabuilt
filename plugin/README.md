# dejabuilt

Check GitHub before you build.

dejabuilt is a skill that finds out whether a project idea already exists on
GitHub. It searches in several phrasings, looks closely at the strongest
candidates and gives one verdict with the numbers behind it.

## What to ask

- "Does a Windows companion app for coding agents already exist?"
- "I want to build a CLI that turns Markdown notes into slide decks. Has someone built this?"
- "Is a skill that checks for existing projects before you build already taken?"

You can also run it directly: `/dejabuilt:dejabuilt <your idea in one sentence>`.

## What you get

A short report: the verdict, a table of the projects that do the same thing
(stars, age, last push, platforms, latest release), adjacent projects, every
query that was run, and what was not checked.

| Verdict | Meaning |
| --- | --- |
| `TAKEN` | A maintained repository with at least 2,000 stars does the same thing. |
| `CONTESTED` | A maintained repository with 200 to 1,999 stars does the same thing. |
| `ORPHANED` | A repository with at least 200 stars did this and is no longer maintained. |
| `LOW_TRACTION` | Three or more attempts, none with 200 stars. |
| `OPEN` | Fewer than three attempts, none with 200 stars. |
| `INCONCLUSIVE` | The search was incomplete, so no absence can be claimed. |

"Maintained" means not archived and pushed within the last 365 days.

The verdict is computed by a script with a fixed policy, not written by the
model. The thresholds are heuristics and every report prints the ones it used. A
verdict describes what exists; it is not advice on whether to build.

## How it works

1. Claude writes six to ten search queries for your idea.
2. The bundled script searches GitHub, merges the results, and reads the latest
   releases and README headings of the top candidates. This is how it notices,
   for example, that a project described as a Mac app ships Windows installers.
3. Claude marks each inspected repository as the same idea, adjacent or unrelated.
4. The script computes the verdict from those marks.

## Requirements

- Python 3.10 or newer on the machine where Claude runs commands. No packages.
- Network access to `api.github.com`.

Where Claude cannot run local commands or reach GitHub, the skill cannot work.

## What it runs, sends and reads

- It runs one bundled Python script, `skills/dejabuilt/scripts/run.py`, through
  Claude's command tool. The script uses only the Python standard library.
- It contacts `https://api.github.com` and nothing else, with GET requests. It
  sends the search queries and the names of the repositories it inspects.
- A GitHub token is optional. If one is present on your machine (the `GH_TOKEN`
  or `GITHUB_TOKEN` environment variable, or a logged-in GitHub CLI), the script
  uses it for GitHub's higher rate limits. It is sent to GitHub only, redirects
  are refused, and it is never printed, logged or written to a file. Without a
  token the skill still works, a few checks an hour.
- It writes two files in a location you choose: a state file with what GitHub
  returned and the report.
- Text from repositories is treated as untrusted data: it is stripped of control
  characters and escaped, and README text is never passed on to Claude.

There is no dejabuilt server and no analytics. See the
[privacy policy](https://github.com/maximilianfeix/dejabuilt/blob/main/PRIVACY.md).

## Limits

- GitHub only: other code hosts, package registries, app stores and
  closed-source products are not searched.
- Each query looks at its top results by stars; the report shows how many
  matches were not looked at.
- Platform hints show what a project ships or mentions, not what works.
- Stars measure attention, not quality or demand.

## More

Source, tests, design notes and three example reports:
<https://github.com/maximilianfeix/dejabuilt>. Problems and questions:
<https://github.com/maximilianfeix/dejabuilt/issues>.

MIT licence. An independent project, not affiliated with or endorsed by GitHub
or Anthropic.

# Examples

Three real runs from 2026-10-10. Each folder holds the state file (what GitHub
returned), the marks (the relevance judgement) and the report. The report can be
rebuilt from the two JSON files without a network connection:

```bash
python skills/dejabuilt/scripts/run.py verdict \
  --from docs/examples/<folder>/state.json \
  --marks docs/examples/<folder>/marks.json
```

Stars and dates are as they were on that day. The repository states in a rebuilt
report (active, stale, dormant) are relative to the day you run it.

| Example | Verdict | What it shows |
| --- | --- | --- |
| [windows-agent-companion](windows-agent-companion/README.md) | `TAKEN` | A project described as a Mac app that ships Windows installers. The release assets gave it away. |
| [markdown-slides-cli](markdown-slides-cli/report.md) | `TAKEN` | A crowded field. This one was run by an agent using the skill end to end; it added two well-known projects by name that none of its nine queries had returned. |
| [idea-check-skill](idea-check-skill/report.md) | `OPEN` | dejabuilt run on its own idea. Two small projects do the same thing, neither has traction, and two more are adjacent. |

## Prompts that produce reports like these

- "Does a Windows companion app for coding agents already exist?"
- "I want to build a CLI that turns Markdown notes into slide decks. Has someone built this?"
- "Check whether an agent skill that looks for existing projects before you build is already taken."

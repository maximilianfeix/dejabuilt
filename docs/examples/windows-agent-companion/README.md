# Example: a Windows companion app for coding agents

Run on 2026-10-10 from the repository root. The numbers will differ when you run
it again, because GitHub changes.

```bash
E=docs/examples/windows-agent-companion
R=skills/dejabuilt/scripts/run.py

python $R search --limit 10 --out $E/state.json \
  -q "notch claude codex" \
  -q "coding agent status island" \
  -q "claude code notch windows" \
  -q "agent approvals menu bar" \
  -q "claude code companion app" \
  -q "dynamic island coding agents"

python $R inspect --from $E/state.json --top 8

python $R verdict --from $E/state.json --marks $E/marks.json --out $E/report.md
```

- [`state.json`](state.json): what the search and the inspection returned.
- [`marks.json`](marks.json): the relevance judgement, written by hand.
- [`report.md`](report.md): the result.

The last command needs no network, so you can reproduce the report from the two
JSON files. The repository states in it (active, stale, dormant) are relative to
the day you run it.

## What this example shows

A first search for this idea found only projects that describe themselves as Mac
apps, which made the idea look open on Windows. The inspection step found
`Coucou-Windows-0.3.0-setup.exe` among the release assets of the most starred
one. Its description still says "in your Mac's notch".

# Contributing

Thanks for looking. Bug reports, fixes and better platform patterns are welcome.

## Set up

```bash
git clone https://github.com/maximilianfeix/dejabuilt.git
cd dejabuilt
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt    # .venv\Scripts\pip on Windows
```

Python 3.10 or newer. The skill itself uses only the standard library; the
packages above are development tools.

## Before you open a pull request

```bash
ruff check .
ruff format --check .
mypy
pytest
python tools/check_skill.py
```

CI runs the same commands on Linux, Windows and macOS.

## Ground rules

- **No runtime dependencies.** The skill folder must run with a bare Python
  install, because installers copy only that folder.
- **`plugin/` is what gets installed.** Keep tests, examples and tooling out of
  it. Its `LICENSE` is a copy of the one at the repository root.
- **No network in tests.** Use the fakes in `tests/helpers.py`. The one live test
  is opt-in with `DEJABUILT_LIVE=1`.
- **Pure modules stay pure.** `verdict`, `sanitize` and `render` do no I/O.
- **A bug fix comes with a test** that fails without the fix.
- **Changing the verdict policy** means bumping `POLICY_VERSION` in `policy.py`,
  updating the tables in `README.md`, `plugin/README.md`, `SKILL.md` and `docs/DESIGN.md`, and
  explaining the change in the pull request. Reports must stay comparable.
- **Changing the JSON output** in a way that breaks readers means bumping
  `SCHEMA_VERSION` in `models.py`.
- **Repository content is untrusted.** Anything read from GitHub goes through
  `sanitize.clean` before it is stored or printed.

Golden files for the report live in `tests/golden/`. After an intended change to
the output, regenerate them with `UPDATE_GOLDEN=1 pytest tests/test_render.py`
and review the diff.

## Good first contributions

- A release asset name whose platform is not detected. Add the name to the
  parametrised cases in `tests/test_inspection.py` and extend the pattern.
- A real idea for which the verdict looks wrong, with the state file and marks.

## Where things are

`docs/DESIGN.md` explains the structure and the reasons behind it.

## Security

Please do not open a public issue for a vulnerability. See `SECURITY.md`.

# Contributing

## Setup

```bash
uv sync --all-extras
uv run pre-commit install
```

## The loop (spec first, tests first)

1. **Spec:** behavior lives in [`docs/specs/`](docs/specs/) as numbered acceptance criteria (AC-001 …).
   Once a test references a spec, the spec is frozen: change it with a dated amendment block, never a silent edit.
2. **Contract:** HTTP changes go into [`docs/api/openapi.yaml`](docs/api/openapi.yaml) first.
3. **Failing tests:** write the test first, name it after the AC (`test_ac_042_…`), and watch it fail.
4. **Validation and security:** decide input rules, who may do what, and what must never leak, before coding.
5. **Implement** the minimum code to pass. No extra features.
6. **Refactor** while green: `ruff format`, `ruff check`, `mypy`, the full `pytest` run.
7. **Review:** a human and an AI review; run the smoke test.
8. **ADR** for any non-obvious decision ([`docs/adr/`](docs/adr/)). ADRs are never edited; a new ADR supersedes an old one.

## Code rules

- **Type hints everywhere.** `mypy --strict` must pass on `keel_gate/`.
- **The domain does no I/O.** `keel_gate/domain/` imports no FastAPI, SQLite, SDKs, or `datetime.now()`. Time comes from the
  `Clock` port.
- **Fail closed.** No bare `except`. An error path returns an explicit deny and logs it (without secrets).
- **No secrets in code, tests, or logs.** Configuration comes from environment variables. Never log tokens or secret values.
- **Money is `Decimal`**, stored as a string. Never `float`.
- **Ported code** from keel v2 keeps a header comment: `# Adapted from keel-v2: engine/keel_engine/<file> (MIT)`.
- **Small commits** with [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `test:`, `docs:` …).

## Tests

See [docs/TESTING.md](docs/TESTING.md). In short: Arrange / Act / Assert, one act per test, no `if` or loops in tests,
hermetic (fake clock, seeded randomness, no real network), factories over fixtures.

## Docs

- Markdown in `docs/` is the only source. The HTML site, the wiki, and the explainer are generated from it.
- Write simple English: short sentences, a diagram first, and hard words added to the [glossary](docs/glossary.md).
- `README.md` stays at 100 lines or fewer (`scripts/check_readme.py`).
- `uv run --extra docs mkdocs build --strict` must pass.

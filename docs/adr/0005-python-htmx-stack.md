# ADR 0005 — Python 3.12 core, FastAPI + Jinja2 + htmx for the UI

* **Status:** Accepted
* **Date:** 2026-11-09

## Context

We have 6 days, and the judges must be able to run the project in minutes. Options:

- **Python** like the keel v2 engine (ported code, fast to build).
- **Kotlin** like the keel v2 API and the platform repo.
- **TypeScript** for a React UI like keel v2's web app.

A React/Vite UI looks modern but adds a Node toolchain and a build step for judges. Kotlin adds JVM start-up and
a bigger setup.

## Decision

- Python 3.12, managed with `uv` (`pyproject.toml`, `uv.lock`).
- Core dependencies only: `pydantic`, `pyyaml`, `tree-sitter`, `tree-sitter-bash` (all MIT).
- Server: FastAPI + uvicorn. UI: server-rendered Jinja2 templates with htmx for live updates. No Node build.
- Storage: SQLite (WAL) and a JSONL file. No database server.
- Docs: MkDocs Material. The explainer is a single plain HTML file.
- Quality: `ruff` (with security rules), `mypy --strict`, `pytest`, `hypothesis`, `pip-audit`.

## Consequences

- **Pros**
  - `uv sync && uv run …` is the whole setup; Docker is optional.
  - Ports straight from keel v2 Python code.
- **Cons**
  - Python is slower than Go or Rust. Mitigated by a pure, compiled-once decision path and a measured p99 budget (AC-160).
  - The htmx UI is simpler than a React app. Good enough for approval cards and a console.
  - Material for MkDocs reaches end of life on May 5, 2027 (it says so at build time). Its successor, Zensical, reads the
    same `mkdocs.yml`, so moving later is cheap.

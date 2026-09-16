# stacks-mcp

Read-only Bitcoin/Stacks MCP server in Python. The full brief is `docs/BRIEF.md`; read it first.

## Rules

- Read-only. Never hold keys, sign, or broadcast. `draft_*` tools return unsigned payloads only.
- No secrets required to run. Optional API keys via env for rate limits.
- Every tool returns a Pydantic model plus a `summary: str`.
- Tests never touch the network: `respx` mocks with recorded fixtures under `tests/fixtures/`.
- Verify upstream API shapes against the live docs before writing a client.

## Commands

```
uv sync                      # env + lockfile
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run pytest
uv run stacks-mcp            # stdio server
```

## Branching

`main` is the release branch, `dev` is integration. Branch `feat/*`, `fix/*`, `docs/*` off `dev`; PR back to `dev`. Conventional commits with scope.

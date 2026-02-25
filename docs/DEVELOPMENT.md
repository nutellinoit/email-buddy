# Development

## Requirements

- Python 3.11+
- [mise](https://mise.jdx.dev/) (optional, for task running)
- Docker and Docker Compose (for container builds)

## Setup

```bash
# Install dev dependencies
pip install -r requirements-dev.txt
```

Dependencies: `litellm`, `instructor`, `pydantic`, `pydantic-settings`. Everything else is Python stdlib (`imaplib`, `email`, `sqlite3`, `ssl`).

Dev tools: `pytest`, `ruff`, `bandit`, `radon`.

## mise Tasks

All tasks can be run with `mise run <task>`:

| Task | Description |
|------|-------------|
| `compile` | Verify all Python files compile without errors |
| `build` | Build Docker image via docker compose |
| `up` | Start all services |
| `down` | Stop all services |
| `logs` | Follow application logs |
| `lint` | Run ruff linter checks |
| `lint:fix` | Auto-fix lint issues and format code |
| `security` | Run bandit SAST security scan |
| `test` | Run test suite |
| `test:cov` | Run tests with coverage report |
| `readability` | Code readability analysis (cyclomatic complexity + maintainability index via radon) |

Without mise, run the underlying commands directly:

```bash
# Tests
python -m pytest tests/ -v

# Lint
ruff check src/ tests/
ruff check --fix src/ tests/ && ruff format src/ tests/

# Security scan
bandit -r src/ -c pyproject.toml

# Tests with coverage
python -m pytest tests/ -v --cov=src --cov-report=term-missing

# Compile check
python -m compileall src/ tests/ -q

# Readability
radon cc src/ -s -n C
radon mi src/ -s
```

## Project Structure

```
src/
  config.py             # Configuration (pydantic-settings, loaded from .env)
  email_client.py       # IMAP orchestration (connection lifecycle, folder resolution, retry)
  imap_ops.py           # Low-level IMAP operations and MIME parsing
  email_classifier.py   # LLM-based email classification
  processor.py          # Main processing loop (fetch, classify, move)
  database.py           # SQLite database manager
  models.py             # Data models (ProcessedEmail, LearningData)
  schemas.py            # Pydantic schemas for LLM structured output
  idle_watcher.py       # IMAP IDLE watcher for real-time detection
  main.py               # Entry point and daemon loop
  daily_summary.py      # Daily HTML summary generation and delivery
  llm/
    __init__.py          # LiteLLM wrapper functions
  learning/
    learning_processor.py  # Folder reconciliation and learning detection
    learning_generator.py  # LLM-based learning summary generation
  api/
    app.py               # FastAPI application (read-only dashboard API)
    routers/              # API endpoint routers (emails, statistics, learning, summaries, system)

tests/                   # pytest test suite
web/                     # Next.js web dashboard
```

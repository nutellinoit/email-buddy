# Email-Buddy

Automated email classifier and organizer. Uses a local or remote LLM to sort incoming emails into user-defined categories and move them to the right IMAP folders.

## Overview

Email-Buddy connects to your mailbox via IMAP, classifies unprocessed emails through an LLM (via [LiteLLM][litellm]), and moves them to configured folders. It tracks every processed email in a local SQLite database so nothing gets classified twice.

It runs as a Docker container in daemon mode (with configurable interval or IMAP IDLE for real-time detection) or as a one-shot process. A web dashboard is included for monitoring classification activity and statistics.

## Features

- Configurable email categories via JSON (not limited to spam/newsletter/regular)
- Any LiteLLM-supported LLM provider (Ollama, LM Studio, OpenAI-compatible, Anthropic, etc.)
- Structured LLM output with schema validation and automatic retry via [Instructor][instructor]
- IMAP IDLE for real-time new-email detection (falls back to polling)
- Adaptive learning from user corrections (folder reconciliation)
- Daily HTML summary email with LLM-generated personalized tips, delivered via IMAP APPEND
- Email backup to disk before IMAP moves (safety net against data loss)
- Category folders as INBOX subfolders (auto-detected hierarchy separator)
- Content-based deduplication with SQLite tracking
- Web dashboard with REST API for monitoring
- Dry run mode for safe testing

## Quick Start

```bash
# Configure
cp .env.example .env
# Edit .env: set IMAP credentials, LITELLM_MODEL, LITELLM_API_BASE

# Test (dry run)
# Set DRY_RUN=true in .env
docker compose up --build

# Deploy
# Set DRY_RUN=false in .env
docker compose up -d --build
```

If you have [mise][mise] installed:

```bash
mise run build     # docker compose build
mise run up        # docker compose up -d
mise run logs      # follow logs
mise run down      # stop
```

## Configuration

All settings are configured via environment variables in `.env`. See [`.env.example`](.env.example) for the full list with comments.

### IMAP

| Variable | Description | Default |
|----------|-------------|---------|
| `IMAP_HOST` | IMAP server | `imap.gmail.com` |
| `IMAP_PORT` | IMAP port | `993` |
| `IMAP_USE_SSL` | Use SSL/TLS | `true` |
| `IMAP_USERNAME` | Email address | - |
| `IMAP_PASSWORD` | Email password or app password | - |
| `INBOX_FOLDER` | IMAP inbox folder name | `INBOX` |
| `CATEGORY_FOLDERS_UNDER_INBOX` | Place category folders as INBOX subfolders | `false` |

### LLM Provider

| Variable | Description | Default |
|----------|-------------|---------|
| `LITELLM_MODEL` | LiteLLM model identifier | `ollama/llama3.1:8b` |
| `LITELLM_API_BASE` | LLM provider URL | `http://ollama:11434` |
| `LITELLM_API_KEY` | API key (`not-needed` for local providers) | `not-needed` |
| `LITELLM_TIMEOUT` | Request timeout in seconds | `300` |

### Processing

| Variable | Description | Default |
|----------|-------------|---------|
| `EMAIL_LIMIT` | Emails to process per cycle | `5` |
| `EMAIL_FETCH_DAYS` | How far back to search for unprocessed emails | `7` |
| `PROCESS_INTERVAL` | Seconds between cycles (0 = one-shot) | `3600` |
| `IDLE_ENABLED` | Use IMAP IDLE instead of polling | `true` |
| `MARK_AS_READ_WHEN_MOVE` | Mark emails as read when moving to category folders | `true` |
| `DRY_RUN` | Classify without moving emails | `false` |

### Database & Retention

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_PATH` | SQLite database path | `/app/data/email_buddy.db` |
| `MAX_FETCH_BATCH` | Max emails to fetch in one batch | `50` |
| `EMAIL_RETENTION_DAYS` | Days to keep processed emails in DB (0 = forever) | `365` |
| `LOG_LEVEL` | Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO` |

### Email Backup

| Variable | Description | Default |
|----------|-------------|---------|
| `EMAIL_BACKUP_ENABLED` | Save raw .eml to disk before moving emails | `false` |
| `EMAIL_BACKUP_PATH` | Directory for .eml backups | `/app/data/emails` |

### Learning

| Variable | Description | Default |
|----------|-------------|---------|
| `LEARNING_ENABLED` | Enable adaptive learning system | `true` |
| `LEARNING_RETENTION_DAYS` | Days to keep learning data (0 = forever) | `0` |
| `MAX_LEARNING_CONTEXT` | Max learning entries included in LLM prompts | `10` |

### Daily Summary

| Variable | Description | Default |
|----------|-------------|---------|
| `DAILY_SUMMARY_ENABLED` | Enable daily summary email | `false` |
| `DAILY_SUMMARY_HOUR` | Hour to send the summary (0-23) | `8` |
| `DAILY_SUMMARY_LANGUAGE` | Language for LLM-generated tips | `English` |

## Architecture

```
    ┌─────────────┐
    │ IMAP Server │
    └──────┬──────┘
           │
  fetch / move / IDLE
           │
    ┌──────┴──────┐      ┌──────────────┐
    │ Email-Buddy │◄────►│ LLM Provider │
    │  (Docker)   │      │ (via LiteLLM)│
    └──┬──────┬───┘      └──────────────┘
       │      │
       │   ┌──┴──────────┐      ┌──────────────────┐
       │   │ REST API     │◄────►│ Web Dashboard     │
       │   │ (FastAPI)    │      │ (Next.js :3123)   │
       │   │ :8000        │      └──────────────────┘
       │   └──────────────┘
    ┌──┴──────────┐
    │  SQLite DB  │
    │ - processed │
    │ - learning  │
    │ - summaries │
    └─────────────┘
```

Processing flow:

1. Fetch unprocessed emails from INBOX (content-hash based deduplication)
2. Classify each email via LLM with confidence scoring and sender history
3. Optionally save a raw .eml backup to disk (if `EMAIL_BACKUP_ENABLED=true`)
4. Move emails above the confidence threshold to the configured IMAP folder
5. If LLM is unavailable, skip the email and retry next cycle
6. Scan folders for user corrections and generate learning rules
7. Wait for next cycle (IMAP IDLE or sleep)

## Categories

Categories are fully configurable via the `CATEGORIES` environment variable (JSON array). Each category defines a name, target IMAP folder, confidence threshold, and a description that the LLM uses for classification. Exactly one category must be marked as default (emails stay in INBOX).

Default configuration:

| Category | Folder | Threshold | Default |
|----------|--------|-----------|---------|
| `spam` | `Suspicious` | 0.7 | no |
| `newsletter` | `Newsletters` | 0.7 | no |
| `regular` | _(stays in INBOX)_ | 0.5 | yes |

Custom example (add your own):

```env
CATEGORIES=[{"name":"spam","folder":"Suspicious","threshold":0.85,"description":"Unwanted or malicious emails"},{"name":"newsletter","folder":"Newsletters","threshold":0.85,"description":"Promotional and marketing emails"},{"name":"orders","folder":"Orders","threshold":0.7,"description":"Purchase confirmations and receipts"},{"name":"regular","folder":"","threshold":0.5,"description":"Personal and important emails","is_default":true}]
```

## Subfolder Mode

By default, Email-Buddy creates category folders at the top level of your mailbox (e.g. `Suspicious`, `Newsletters`). If you prefer them as subfolders of INBOX, set:

```env
CATEGORY_FOLDERS_UNDER_INBOX=true
```

The IMAP hierarchy separator is auto-detected from your server via RFC 3501 `LIST` command:

| Server | Separator | Result |
|--------|-----------|--------|
| Dovecot, Courier, Cyrus | `.` | `INBOX.Suspicious` |
| Gmail, Exchange | `/` | `INBOX/Suspicious` |

If detection fails, `.` is used as fallback. No migration is performed when toggling this setting — existing folders remain as-is and new folders are created with the new naming scheme.

## Learning

Email-Buddy learns from your corrections using folder reconciliation. When the system moves an email to a folder and you later move it somewhere else, the system detects the discrepancy and generates a learning rule.

How it works:

1. Email-Buddy classifies an email and moves it to `Suspicious`
2. You disagree and move it back to `INBOX` (or to any other folder)
3. On the next reconciliation cycle, the system detects that the email is no longer where it placed it
4. It analyzes the correction, generates a learning summary via LLM, and saves it
5. Future classifications use these learning rules as additional context

Learning data is kept indefinitely by default (`LEARNING_RETENTION_DAYS=0`). Set a positive value to auto-expire old entries.

## Email Backup

When enabled, Email-Buddy saves a raw `.eml` copy of each email to disk before performing the IMAP move operation. This acts as a safety net against data loss if the move fails mid-operation.

```env
EMAIL_BACKUP_ENABLED=true
EMAIL_BACKUP_PATH=/app/data/emails
```

Backup files are organized by category: `{EMAIL_BACKUP_PATH}/{category}/{content_id}.eml`. Old backups are automatically deleted when the corresponding database record expires via `EMAIL_RETENTION_DAYS`.

## Daily Summary

When enabled (`DAILY_SUMMARY_ENABLED=true`), Email-Buddy generates a daily HTML report and delivers it as an unread email in your INBOX via IMAP APPEND.

The summary includes:
- Classification statistics for the past 24 hours
- Per-category breakdown and top senders
- LLM-generated personalized tips based on individual email details (sender, subject, confidence)

Configure the delivery hour with `DAILY_SUMMARY_HOUR` and the tips language with `DAILY_SUMMARY_LANGUAGE`.

## LLM Providers

Email-Buddy uses [LiteLLM][litellm] for provider abstraction. The provider is inferred from the model prefix.

**Ollama** (recommended for local):
```env
LITELLM_MODEL=ollama/llama3.1:8b
LITELLM_API_BASE=http://localhost:11434
```

**LM Studio** (or any OpenAI-compatible server):
```env
LITELLM_MODEL=openai/google/gemma-2-9b
LITELLM_API_BASE=http://192.168.1.53:1234/v1
```

At startup, Email-Buddy sends a structured-output probe to the LLM to verify compatibility. If the model does not support structured output, the process exits immediately.

See [LiteLLM providers][litellm-providers] for the full list of supported model prefixes.

## Development

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for setup instructions, available mise tasks, and project structure.

## Troubleshooting

**IMAP connection fails** — Verify host, port, and credentials. Gmail requires an [app password][gmail-app-pw], not your regular password.

**LLM not available** — Check that `LITELLM_API_BASE` is reachable and the model is loaded. Email-Buddy skips emails when the LLM is down and retries next cycle.

**No emails processed** — Check `EMAIL_FETCH_DAYS` (default: 7 days back). Increase `EMAIL_LIMIT` if needed. Already-processed emails are tracked in the database.

**Learning not working** — Move a misclassified email to the correct folder. The system detects the correction on the next reconciliation cycle. Check `LEARNING_ENABLED=true` and inspect logs with `mise run logs`.

**Startup probe fails** — The configured model does not support structured output. Try a different model (e.g., `ollama/llama3.1:8b`).

Enable debug logging for detailed output:
```env
LOG_LEVEL=DEBUG
```

## License

See [LICENSE](LICENSE).

<!-- Links -->
[litellm]: https://docs.litellm.ai/
[litellm-providers]: https://docs.litellm.ai/docs/providers
[instructor]: https://github.com/jxnl/instructor
[mise]: https://mise.jdx.dev/
[gmail-app-pw]: https://support.google.com/accounts/answer/185833

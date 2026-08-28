# Access Log Analyzer

A CLI tool for Jira and Confluence Data Center administrators to analyze API usage patterns and predict rate limiting issues before migrating to Atlassian Cloud.

## What It Does

When migrating from Jira/Confluence Data Center to Atlassian Cloud, your instance will be subject to strict API rate limits. This tool reads your existing DC access logs and calculates:

1. **Points-based hourly quota** — Would your current API usage exceed Cloud's hourly point limits?
2. **Burst rate limits** — Are any integrations sending too many requests per second?
3. **Per-issue write limits** — Are any automations updating the same issue too frequently?

## Key Features

- **Multi-format log parsing** — Automatically detects and parses standard, Jira DC custom, and Confluence proxy log formats
- **Large-log streaming** — Handles 60+ GB logs without memory exhaustion using disk-backed SQLite aggregation
- **Real-time progress** — Shows live parsing metrics, throughput, and ETA during analysis
- **Native macOS app** — Packaged as a true `.app` bundle; appears in Dock with app icon, not Python process
- **Clear completion state** — Knows exactly when analysis is done and the PDF is ready
- **Safe cancellation** — Stop analysis at any time without corrupting the output
- **Internal traffic filtering** — Excludes Jira/Confluence application-link traffic from reports

## Atlassian Cloud Rate Limits

Based on [Atlassian's rate limiting documentation](https://developer.atlassian.com/cloud/jira/platform/rate-limiting/):

| Plan | Points/Hour |
|------|------------|
| Standard | 10,000 |
| Premium | 50,000 |
| Enterprise | 250,000 |
| Enterprise (large org) | 500,000 |

## Installation

> **Note:** Requires Python 3.11. This project is currently constrained to `<3.14` because `pymupdf==1.23.8` did not build cleanly under Python 3.14 in this environment.

### Option 1: Native macOS App (Easiest)

Copy the pre-built app to Applications (one-time):

```bash
cp -R "/path/to/dist/Access Log Analyzer.app" /Applications/
```

Then launch from **Applications**, **Spotlight**, or **Launchpad**. The app appears as "Access Log Analyzer" in the Dock with the app icon.

### Option 2: From Source (Development)

```bash
# Install uv, Python 3.11, tkinter, and poppler if needed
brew install uv python@3.11 python-tk@3.11 poppler

cd access-log-analyzer
uv python install 3.11
uv sync --python 3.11 --group dev
```

This creates a local `.venv`, installs runtime dependencies from `pyproject.toml`, and includes the development tools.

### Rebuilding the macOS App

After making code changes, rebuild the app bundle:

```bash
cd access-log-analyzer
./build-macos-app.sh
cp -R "dist/Access Log Analyzer.app" /Applications/
```

The `build-macos-app.sh` script uses PyInstaller to package the analyzer as a native macOS application.

## Development Commands

```bash
# Lint
uv run ruff check .

# Type check
uv run ty check .

# Refresh lockfile after dependency changes
uv lock --python 3.11
```

## Usage

### GUI App (Recommended)
```bash
uv run access-log-analyzer-gui
```

### CLI

```bash
# Analyze a Jira access log against Standard plan limits
uv run access-log-analyzer --log /path/to/jira/access.log --product jira

# Analyze against Premium plan limits
uv run access-log-analyzer --log /path/to/jira/access.log --product jira --plan premium

# Analyze against Enterprise max limits (large orgs with 500k points/hour)
uv run access-log-analyzer --log /path/to/jira/access.log --product jira --plan enterprise-max

# Analyze a Confluence access log
uv run access-log-analyzer --log /path/to/confluence/access.log --product confluence

# Try with the included sample log
uv run access-log-analyzer --log sample_logs/jira-access.log --product jira
```

If you prefer, these equivalent direct commands also work:

```bash
uv run python app.py
uv run python main.py --log sample_logs/jira-access.log --product jira
```

## Dependency Files

- `pyproject.toml` is the source of truth for project metadata, runtime dependencies, dev dependencies, and tool config.
- `uv.lock` locks exact dependency versions for reproducible installs.
- `.python-version` pins the repository to Python 3.11 for uv.
- `requirements.txt` is kept for compatibility, but uv is now the default workflow.

## Where to Find Your DC Access Logs

**Jira DC:**
```
<jira-home>/log/access.log
# or
/var/atlassian/application-data/jira/log/access.log
```

**Confluence DC:**
```
<confluence-home>/logs/access.log
# or
/var/atlassian/application-data/confluence/logs/access.log
```

## Output

The tool generates a report with 5 sections:
1. **Summary** — Overall stats
2. **Hourly Quota Analysis** — Points used per hour vs Cloud limits
3. **Burst Rate Analysis** — Requests/second per endpoint
4. **Per-Issue Write Analysis** — Write frequency per issue
5. **Recommendations** — Actionable steps to address any issues

## Risk Levels

| Icon | Meaning |
|------|---------|
| 🟢 OK | Within safe limits |
| 🟡 WARNING | >75% of limit, monitor closely |
| 🔴 BREACH | Would exceed Cloud rate limits |

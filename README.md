# Access Log Analyzer

A CLI tool for Jira and Confluence Data Center administrators to analyze API usage patterns and predict rate limiting issues before migrating to Atlassian Cloud.

## What It Does

When migrating from Jira/Confluence Data Center to Atlassian Cloud, your instance will be subject to strict API rate limits. This tool reads your existing DC access logs and calculates:

1. **Points-based hourly quota** — Would your current API usage exceed Cloud's hourly point limits?
2. **Burst rate limits** — Are any integrations sending too many requests per second?
3. **Per-issue write limits** — Are any automations updating the same issue too frequently?

## Atlassian Cloud Rate Limits

Based on [Atlassian's rate limiting documentation](https://developer.atlassian.com/cloud/jira/platform/rate-limiting/):

| Plan | Points/Hour |
|------|------------|
| Standard | 10,000 |
| Premium | 50,000 |
| Enterprise | 250,000 |

## Installation

```bash
cd access-log-analyzer
pip install -r requirements.txt
```

## Usage

```bash
# Analyze a Jira access log against Standard plan limits
python main.py --log /path/to/jira/access.log --product jira

# Analyze against Premium plan limits
python main.py --log /path/to/jira/access.log --product jira --plan premium

# Analyze a Confluence access log
python main.py --log /path/to/confluence/access.log --product confluence

# Try with the included sample log
python main.py --log sample_logs/jira-access.log --product jira
```

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

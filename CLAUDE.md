# Access Log Analyzer — Rovo Dev Context

## What This App Does
A macOS desktop GUI app (built with Tkinter + PyInstaller) that analyzes Jira and Confluence Data Center access logs to predict API rate limiting issues when migrating to Atlassian Cloud.

It parses DC access logs, calculates points consumption against Atlassian Cloud rate limit tiers, and generates a professional PDF report for migration planning.

## Architecture

```
access-log-analyzer/
├── app.py                  # Tkinter GUI app (main entry point for the .app bundle)
├── main.py                 # CLI entry point (for command-line usage)
├── analyzer/
│   ├── parser.py           # Parses Jira/Confluence DC access log lines into APICall objects
│   ├── calculator.py       # Points calculation, quota analysis, burst rate, per-issue write analysis
│   ├── pdf_exporter.py     # Generates the PDF report using ReportLab
│   └── reporter.py         # CLI text report output (used by main.py)
├── sample_logs/            # Sample log files for testing
├── Access Log Analyzer.spec  # PyInstaller spec for building the macOS .app
└── AppIcon.icns            # App icon
```

## Building the Mac App
```bash
pyinstaller "Access Log Analyzer.spec" --noconfirm
# Output: dist/Access Log Analyzer.app
cp -R "dist/Access Log Analyzer.app" ~/Desktop/
```

**Note:** The app depends on `poppler` (via Homebrew at `/opt/homebrew/bin`) for the in-app PDF preview. If poppler is not installed, the PDF is still generated correctly — the app shows a friendly fallback message directing the user to the output file location.

## Key Features

### GUI (app.py)
- Multi log file picker (+ Add Log File)
- Product + Edition dropdowns (Jira/Confluence, Standard/Premium/Enterprise)
- User count field (enables Tier 2 per-tenant quota formula when filled)
- **System call exclusion toggle** — checkbox to exclude unauthenticated/system calls from all analysis (checked by default). Auto re-runs analysis when toggled if a PDF already exists.
- IP exclusion field (up to 10 IPs, comma-separated)
- PDF output path picker (auto-generates temp path if not set)
- In-app PDF preview with scroll support (requires poppler)

### PDF Report Sections (pdf_exporter.py)
1. **Summary table** — call counts, points, IPs, users, plan, quota, system call count
2. **Load balancer warning** — fires if >90% of traffic from single IP
3. **Hourly Quota Analysis** — table + bar chart, coloured by risk level
4. **Burst Rate Analysis** — per-endpoint RPS vs Cloud limits
5. **Per-Issue Write Analysis** — detects issues with excessive write rates
6. **Top Consumers** — split into Authenticated Users, Service Accounts, Unauthenticated
7. **Recommendations** — auto-generated based on findings
8. **Appendix: Methodology & Disclaimer** — explains points estimation, object count heuristics, limitations, and X-Forwarded-For recommendation

### Analysis (calculator.py)
- **Tier 1** (global pool): 65,000 points/hour (no user count)
- **Tier 2** (per-tenant): `base + (multiplier × users)`, capped at 500,000 points/hour
- Points per call: writes = 1 pt flat; reads = 1 pt + estimated objects × cost per object
- Object counts estimated from response bytes using endpoint-aware heuristics
- **Call classification**: `authenticated_user`, `service_account` (matched by username patterns), `unauthenticated` (username is `-`)
- Service account patterns: `svc_`, `svc-`, `service`, `bot`, `automation`, `admin`, `integration`, `sync`, `api`, `system`, `daemon`, `job`, `tasktop`, `qtest`, `jenkins`, `bamboo`, `script`

## System Call Exclusion Toggle
When "Exclude unauthenticated / system API calls" is checked:
- Only `authenticated_user` and `service_account` calls are passed to all analysis functions
- `unauthenticated` calls (username = `-`) are excluded — these are internal system-to-system or load-balancer-proxied calls that won't hit Cloud rate limits
- The PDF summary table shows the excluded count and mode label
- The PDF header metadata line reflects the current mode

## Known Limitations / Sharing with Coworkers
- App is not signed with an Apple Developer certificate — coworkers need to right-click → Open to bypass Gatekeeper
- Built for Apple Silicon (arm64) — Intel Mac users may have issues
- Poppler is not bundled — PDF preview won't work without Homebrew + poppler, but PDF generation still works fine
- The app shows a friendly error message if poppler is missing, directing users to the output file

## Recent Changes (as of April 2026)
- Added system call exclusion toggle to UI and PDF
- Added X-Forwarded-For recommendation to Methodology & Disclaimer appendix
- Improved PDF preview error handling for machines without poppler
- Split Top Consumers into authenticated users, service accounts, and unauthenticated traffic
- Added IP exclusion field and load balancer detection warning
- Added per-node analysis

## Outstanding Ideas / Future Work
- Bundle poppler into the PyInstaller spec for fully self-contained distribution
- Sign the app with an Apple Developer certificate for easier sharing
- Build a universal binary (arm64 + x86_64) to support Intel Macs
- Parse `X-Forwarded-For` header from logs if present, for better per-client IP analysis

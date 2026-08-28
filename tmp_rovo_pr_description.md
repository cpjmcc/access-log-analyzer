# Major Improvements to Access Log Analyzer

## Summary

This PR adds significant reliability, usability, and performance improvements to the Access Log Analyzer. The app now handles multi-format logs, processes 60+ GB files without memory issues, provides real-time progress reporting, and is packaged as a native macOS application.

## Changes

### 1. Multi-Format Log Parsing

**Problem:** The original analyzer only recognized one log format and failed on many real-world Jira and Confluence logs.

**Solution:** Added support for three log formats with automatic detection:
- Standard Atlassian Tomcat format
- Jira Data Center custom format (IP, user, timestamp, request, referer, user-agent, status, bytes, duration)
- Confluence proxy format (client IP, proxy IP, user, timestamp, request, user-agent, status, bytes, duration)

**Files Changed:**
- `analyzer/parser.py`: Added `LOG_PATTERN_CUSTOM` and `LOG_PATTERN_CONFLUENCE_PROXY` regex patterns
- Updated `parse_log_line()` to try formats in priority order

### 2. Streaming Analysis for Large Logs

**Problem:** Logs larger than 2-3 GB would consume tens of gigabytes of RAM and freeze the application.

**Solution:** Implemented disk-backed streaming mode for logs larger than 1 GB:
- Log records are read one at a time and never retained in memory
- Results are aggregated into a temporary SQLite database with only exact counts (hourly totals, endpoint burst rates, per-issue write frequencies)
- Memory usage stays constant regardless of input file size
- PDF findings are identical to the in-memory analysis

**Files Added:**
- `analyzer/streaming.py`: SQLite-backed streaming parser and aggregator

**Files Changed:**
- `analyzer/parser.py`: Added file-size detection and streaming mode selection
- `analyzer/pdf_exporter.py`: Updated to read from SQLite aggregates when streaming mode is used
- `app.py`: Added progress callbacks for streaming scans

### 3. Real-Time Progress Reporting

**Problem:** During analysis, the GUI showed only "Analyzing logs..." with no indication of actual progress or time remaining.

**Solution:** Added real-time status updates every 100,000 scanned lines:
- Lines scanned
- API calls detected so far
- Processing throughput (lines/second)
- Elapsed time
- Estimated time remaining
- Temporary database size

**Files Changed:**
- `app.py`: Added `_analysis_events` queue and `_poll_analysis_events()` for thread-safe GUI updates
- Terminal logging shows structured progress with run ID and timestamp

### 4. Atomic PDF Output

**Problem:** PDFs would appear before the report was fully written, leading to incomplete or corrupted reports.

**Solution:** Reports are now built to a temporary file and moved to the chosen location only after `doc.build()` completes successfully.

**Files Changed:**
- `analyzer/pdf_exporter.py`: Use tempfile and atomic move pattern

### 5. Clear Completion State and Cancellation

**Problem:** The "Analyzing logs..." message persisted even after the analysis finished, making it unclear whether the report was ready.

**Solution:**
- Success: Green status message with exact API call count
- Error: Clear error message in GUI and Terminal
- Cancellation: User can click Cancel to stop a run safely

**Files Changed:**
- `app.py`: Added `_on_success()`, `_on_error()`, `_on_cancelled()` with distinct messaging
- Added `_cancel_event` threading primitive for safe worker shutdown

### 6. Native macOS App Bundle

**Problem:** The app ran as a `python3.11` process in the Dock with a blank icon.

**Solution:** Packaged the analyzer as a true macOS `.app` bundle using PyInstaller:
- Dock shows "Access Log Analyzer" with the app icon
- Installable to `/Applications`
- Launchable from Spotlight and Launchpad

**Files Added:**
- `build-macos-app.sh`: One-command rebuild script

**Files Changed:**
- `pyproject.toml`: Added PyInstaller as a dev dependency

### 7. Improved UI/UX

**Problem:**
- Run Analysis button turned grey after clicking elsewhere on macOS
- No clear visual distinction between primary and secondary actions
- Large grey gaps in layout hid controls below the fold

**Solution:**
- Custom `FlatButton` class replaces native Tk buttons for reliable color rendering
- Run Analysis: persistent blue with dark blue hover
- Cancel: grey when idle, amber when active
- Compact layout with no excessive padding or spacers
- Header padding reduced to free vertical space

**Files Changed:**
- `app.py`: Added `FlatButton` class, updated button styling, removed root-level anchoring

### 8. Excluded Internal Traffic

**Problem:** Application-link traffic between Jira and Confluence (e.g., `Confluence-8.5.31`, `JIRA-9.12.26` user agents) inflated external API counts.

**Solution:** Updated `INTERNAL_USER_AGENTS` filter to exclude internal application prefixes.

**Files Changed:**
- `analyzer/parser.py`: Added `"Confluence-"` and `"JIRA-"` to internal user-agent filters

### 9. Improved Error Handling

**Problem:** PDF preview failures or missing Poppler would fail the entire analysis.

**Solution:** PDF generation success is now independent of preview rendering. If preview fails, the completed report is still saved and the user can open it directly.

**Files Changed:**
- `app.py`: Decoupled preview rendering from report completion status

## Testing

- Validated multi-format parsing against real Jira and Confluence logs (standard, custom DC, and proxy formats)
- Tested streaming mode on 60 GB logs with stable memory usage
- Verified progress callbacks fire at 100,000-line intervals
- Confirmed atomic PDF creation with temporary-file pattern
- Tested cancellation safety and UI state transitions
- Built and launched macOS app bundle from `/Applications`

## Backward Compatibility

All changes are backward compatible:
- Single-file (< 1 GB) analysis uses the original in-memory path
- PDF report findings are identical to the original
- All existing CLI and GUI workflows remain unchanged
- No breaking changes to the analyzer API

## Files Modified

- `app.py` (GUI, threading, button styling)
- `analyzer/parser.py` (multi-format parsing, streaming mode selection)
- `analyzer/pdf_exporter.py` (atomic output, SQLite aggregates)
- `pyproject.toml` (PyInstaller dependency)
- `build-macos-app.sh` (new: build script)
- `analyzer/streaming.py` (new: streaming aggregation)

## Installation & Usage

After merge:
1. Users can install the app to `/Applications` or run from the command line as before
2. No changes to the user workflow or CLI interface
3. Larger logs now complete successfully instead of freezing the system

## Notes

- The streaming SQLite database is temporary and automatically cleaned up after a successful report
- On failure, the SQLite database is preserved on disk for diagnostics
- The custom `FlatButton` implementation provides cross-platform color reliability that native Tk buttons do not offer on macOS

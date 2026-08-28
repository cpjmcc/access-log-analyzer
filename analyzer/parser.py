"""
parser.py
Parses Jira and Confluence Data Center access logs and extracts
external API calls with metadata needed for rate limit analysis.

Jira DC access log format (default):
  127.0.0.1 - user [08/Apr/2026:10:00:01 +0000] "GET /rest/api/2/issue/ABC-123 HTTP/1.1" 200 1234 "-" "curl/7.79.1" 45

Confluence DC access log format (default):
  127.0.0.1 - user [08/Apr/2026:10:00:01 +0000] "GET /rest/api/content/12345 HTTP/1.1" 200 5678 "-" "python-requests/2.28.0" 120
"""

import re
from datetime import datetime
from dataclasses import dataclass, field
from collections.abc import Callable, Iterator
from typing import Optional

# Regex for Standard Combined Log Format (used by sample/simple DC configs):
#   IP - user [timestamp] "METHOD path HTTP/x" status bytes "referer" "ua" duration
LOG_PATTERN_STANDARD = re.compile(
    r'(?P<ip>\S+)\s+'
    r'\S+\s+'                                                    # ident (-)
    r'(?P<user>\S+)\s+'
    r'\[(?P<timestamp>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<bytes>\S+)'
    r'(?:\s+"(?P<referer>[^"]*)"\s+"(?P<user_agent>[^"]*)")?'
    r'(?:\s+(?P<duration>\d+))?'
)

# Regex for Jira DC extended log format:
#   IP requestId userId [timestamp] "METHOD path HTTP/x" status bytes duration "referer" "ua" "sessionId"
LOG_PATTERN_JIRA_DC = re.compile(
    r'(?P<ip>\S+)\s+'
    r'\S+\s+'                                                    # requestId (0x...)
    r'(?P<user>\S+)\s+'                                          # userId or -
    r'\[(?P<timestamp>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<bytes>\S+)\s+'
    r'(?P<duration>\d+)\s+'                                      # duration comes BEFORE referer
    r'"(?P<referer>[^"]*)"\s+'
    r'"(?P<user_agent>[^"]*)"'
    r'(?:\s+"[^"]*")?'                                           # optional session id
)

# Regex for Confluence DC logs behind a proxy:
#   clientIP, proxyIP user [timestamp] "METHOD path HTTP/x" "ua" status bytes duration
LOG_PATTERN_CONFLUENCE_PROXY = re.compile(
    r'(?P<ip>\S+?)(?:,\s*\S+)*\s+'
    r'(?P<user>\S+)\s+'
    r'\[(?P<timestamp>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'"(?P<user_agent>[^"]*)"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<bytes>\S+)'
    r'(?:\s+(?P<duration>\d+))?'
)

# Regex for custom DC format:
#   IP user [timestamp] "METHOD path HTTP/x" "referer" "ua" status bytes duration
LOG_PATTERN_CUSTOM = re.compile(
    r'(?P<ip>\S+)\s+'
    r'(?P<user>\S+)\s+'
    r'\[(?P<timestamp>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'"(?P<referer>[^"]*)"\s+'
    r'"(?P<user_agent>[^"]*)"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<bytes>\S+)'
    r'(?:\s+(?P<duration>\d+))?'
)

# Timestamp format used in DC logs
TIMESTAMP_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

# Internal/system user agents to exclude (these are Atlassian internal calls)
INTERNAL_USER_AGENTS = [
    "Atlassian",
    "JiraInternal",
    "ConfluenceInternal",
    "com.atlassian",
    "Confluence-",
    "JIRA-",
]

# Paths that are NOT external API calls (internal/UI traffic)
NON_API_PATHS = [
    "/secure/",
    "/plugins/",
    "/s/",
    "/download/",
    "/images/",
    "/styles/",
    "/static/",
    "/favicon",
    "/login",
    "/logout",
]

# API paths we DO want to analyze
API_PATH_PREFIXES = {
    "jira": ["/rest/api/", "/rest/agile/", "/rest/auth/", "/rest/servicedeskapi/"],
    "confluence": ["/rest/api/", "/rest/mobile/", "/wiki/rest/api/"],
}


@dataclass
class APICall:
    """Represents a single parsed external API call."""
    ip: str
    user: str
    timestamp: datetime
    method: str
    path: str
    status: int
    response_bytes: int
    user_agent: str
    duration_ms: Optional[int]
    product: str
    # Populated by calculator
    points: int = 0
    endpoint_key: str = ""


def is_external_api_call(path: str, user_agent: str, product: str) -> bool:
    """Returns True if this log line represents an external API call."""
    # Must be an API path
    prefixes = API_PATH_PREFIXES.get(product, API_PATH_PREFIXES["jira"])
    if not any(path.startswith(p) for p in prefixes):
        return False

    # Must not be internal UI/static path
    if any(path.startswith(p) for p in NON_API_PATHS):
        return False

    # Must not be an internal Atlassian system agent
    if any(agent.lower() in user_agent.lower() for agent in INTERNAL_USER_AGENTS):
        return False

    return True


def parse_log_line(line: str, product: str) -> Optional[APICall]:
    """Parse a single log line and return an APICall if it's a relevant external API call."""
    # Try the most specific DC formats before falling back to standard logs.
    match = LOG_PATTERN_JIRA_DC.match(line.strip())
    if not match:
        match = LOG_PATTERN_CONFLUENCE_PROXY.match(line.strip())
    if not match:
        match = LOG_PATTERN_CUSTOM.match(line.strip())
    if not match:
        match = LOG_PATTERN_STANDARD.match(line.strip())
    if not match:
        return None

    path = match.group("path")
    user_agent = match.group("user_agent") or ""
    method = match.group("method")
    status = int(match.group("status"))

    if not is_external_api_call(path, user_agent, product):
        return None

    # Parse timestamp
    try:
        timestamp = datetime.strptime(match.group("timestamp"), TIMESTAMP_FORMAT)
    except ValueError:
        return None

    # Parse response bytes
    bytes_str = match.group("bytes")
    response_bytes = int(bytes_str) if bytes_str != "-" else 0

    # Parse duration
    duration_str = match.group("duration")
    duration_ms = int(duration_str) if duration_str else None

    return APICall(
        ip=match.group("ip"),
        user=match.group("user"),
        timestamp=timestamp,
        method=method,
        path=path,
        status=status,
        response_bytes=response_bytes,
        user_agent=user_agent,
        duration_ms=duration_ms,
        product=product,
    )


# Bound the memory used to scan malformed input. Access-log records should be
# much smaller than 1 MiB; records beyond this limit are skipped safely.
READ_CHUNK_BYTES = 64 * 1024
MAX_LOG_LINE_BYTES = 1 * 1024 * 1024


def iter_log_lines(filepath: str) -> Iterator[Optional[str]]:
    """Yield decoded log records while keeping memory bounded for malformed files.

    ``None`` represents a skipped record that exceeded ``MAX_LOG_LINE_BYTES``.
    The reader works from fixed-size byte chunks rather than relying on the text
    iterator, which can allocate an unbounded string when a log is missing a
    newline or contains a corrupted oversized record.
    """
    pending = b""
    discarding_oversized_record = False

    with open(filepath, "rb") as log_file:
        while chunk := log_file.read(READ_CHUNK_BYTES):
            if discarding_oversized_record:
                newline_index = chunk.find(b"\n")
                if newline_index == -1:
                    continue
                chunk = chunk[newline_index + 1:]
                discarding_oversized_record = False

            data = pending + chunk
            complete_records = data.split(b"\n")
            pending = complete_records.pop()

            for raw_record in complete_records:
                if len(raw_record) > MAX_LOG_LINE_BYTES:
                    yield None
                    continue
                yield raw_record.decode("utf-8", errors="replace")

            if len(pending) > MAX_LOG_LINE_BYTES:
                # Do not retain or repeatedly append an oversized partial line.
                yield None
                pending = b""
                discarding_oversized_record = True

    if pending and not discarding_oversized_record:
        if len(pending) > MAX_LOG_LINE_BYTES:
            yield None
        else:
            yield pending.decode("utf-8", errors="replace")


def iter_parsed_calls(
    filepath: str,
    product: str,
    excluded_ips: Optional[list[str]] = None,
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
) -> Iterator[APICall]:
    """
    Stream-parse a log file, yielding APICall objects without loading all into memory.
    
    Args:
        filepath: Path to the log file
        product: 'jira' or 'confluence'
        excluded_ips: List of IP addresses to exclude (e.g. the server's own IP)
        progress_callback: Optional callback(total_lines, api_calls_yielded) for progress
    
    Yields:
        APICall objects one at a time
    """
    excluded_set = set(ip.strip() for ip in (excluded_ips or []) if ip.strip())
    total = 0
    yielded = 0
    bytes_scanned = 0
    
    try:
        for line in iter_log_lines(filepath):
            total += 1
            if line is not None:
                bytes_scanned += len(line.encode("utf-8", errors="replace")) + 1
                call = parse_log_line(line, product)
                if call and call.ip not in excluded_set:
                    yield call
                    yielded += 1
            
            if progress_callback and total % 100_000 == 0:
                progress_callback(total, yielded, bytes_scanned)
    except FileNotFoundError:
        raise FileNotFoundError(f"Log file not found: {filepath}")


def parse_log_file(
    filepath: str,
    product: str,
    excluded_ips: Optional[list[str]] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[APICall]:
    """Parse an entire log file and return all external API calls.
    
    Args:
        filepath: Path to the log file
        product: 'jira' or 'confluence'
        excluded_ips: List of IP addresses to exclude (e.g. the server's own IP)
    """
    calls = []
    skipped = 0
    oversized = 0
    excluded = 0
    total = 0
    excluded_set = set(ip.strip() for ip in (excluded_ips or []) if ip.strip())

    try:
        for line in iter_log_lines(filepath):
            total += 1
            if line is None:
                oversized += 1
                skipped += 1
            else:
                call = parse_log_line(line, product)
                if call:
                    if call.ip in excluded_set:
                        excluded += 1
                    else:
                        calls.append(call)
                else:
                    skipped += 1

            if progress_callback and total % 100_000 == 0:
                progress_callback(total, len(calls))
    except FileNotFoundError:
        raise FileNotFoundError(f"Log file not found: {filepath}")

    msg = f"  Parsed {total} log lines → {len(calls)} external API calls ({skipped} skipped)"
    if oversized:
        msg += f", {oversized} oversized records skipped"
    if excluded:
        msg += f", {excluded} excluded (system IPs)"
    print(msg)
    return calls

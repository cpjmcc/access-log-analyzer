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

# Timestamp format used in DC logs
TIMESTAMP_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

# Internal/system user agents to exclude (these are Atlassian internal calls)
INTERNAL_USER_AGENTS = [
    "Atlassian",
    "JiraInternal",
    "ConfluenceInternal",
    "com.atlassian",
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
    # Try Jira DC extended format first (more specific), then standard
    match = LOG_PATTERN_JIRA_DC.match(line.strip())
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


def parse_log_file(filepath: str, product: str) -> list[APICall]:
    """Parse an entire log file and return all external API calls."""
    calls = []
    skipped = 0
    total = 0

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                total += 1
                call = parse_log_line(line, product)
                if call:
                    calls.append(call)
                else:
                    skipped += 1
    except FileNotFoundError:
        raise FileNotFoundError(f"Log file not found: {filepath}")

    print(f"  Parsed {total} log lines → {len(calls)} external API calls ({skipped} skipped)")
    return calls

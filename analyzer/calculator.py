"""
calculator.py
Applies Atlassian Cloud's points-based rate limiting system to parsed API calls.

Based on: https://developer.atlassian.com/cloud/jira/platform/rate-limiting/

Rate Limiting Systems:
1. Points-based quota (per hour): Each API call costs points based on complexity
2. Burst rate limits (per second): Max requests/second per endpoint
3. Per-issue write limits: Max writes per issue per time window

Points System:
- Base cost: 1 point per request
- Read operations: 1 base + (objects returned × cost per object type)
  - Issues: 1 point each
  - Users/Group members: 2 points each
  - Comments, worklogs, etc: 1 point each
- Write operations: 1 point flat (regardless of object type)

Cloud Quota Limits (enforced from March 2, 2026):
- Standard plan:  ~10,000 points/hour
- Premium plan:   ~50,000 points/hour  
- Enterprise:     ~250,000 points/hour
(We use the most restrictive Standard limit as a conservative baseline)
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import DefaultDict
from .parser import APICall

# ---------------------------------------------------------------------------
# Cloud quota limits (points per hour) by plan tier
# ---------------------------------------------------------------------------
CLOUD_QUOTA_LIMITS = {
    "standard": 10_000,
    "premium": 50_000,
    "enterprise": 250_000,
    "enterprise-max": 500_000,  # Enterprise with large user counts
}

# Default plan to warn against (most conservative)
DEFAULT_PLAN = "standard"

# ---------------------------------------------------------------------------
# Burst rate limits (requests per second) — approximate steady-state values
# from Atlassian documentation
# ---------------------------------------------------------------------------
BURST_STEADY_STATE_RPS = 10  # requests per second per endpoint (steady-state)
BURST_BUCKET_SIZE = 100       # token bucket max size

# ---------------------------------------------------------------------------
# Per-issue write limit
# ---------------------------------------------------------------------------
PER_ISSUE_WRITE_LIMIT = 10    # max writes per issue per minute

# ---------------------------------------------------------------------------
# Endpoint pattern → point cost rules
# ---------------------------------------------------------------------------
# Each rule is (regex_pattern, method_filter, base_points, per_object_points, object_type)
# method_filter: None = any, "GET" = reads only, "POST"/"PUT"/"DELETE" = writes
ENDPOINT_RULES = [
    # Issues
    (re.compile(r"^/rest/api/[23]/issue/[^/]+$"), "GET", 1, 1, "issue"),
    (re.compile(r"^/rest/api/[23]/issue/[^/]+$"), None, 1, 0, "write"),
    # Issue search
    (re.compile(r"^/rest/api/[23]/search"), "GET", 1, 1, "issue"),
    # Group members (users cost 2 points each)
    (re.compile(r"^/rest/api/[23]/group/member"), "GET", 1, 2, "user"),
    # Users
    (re.compile(r"^/rest/api/[23]/user"), "GET", 1, 2, "user"),
    # Comments
    (re.compile(r"^/rest/api/[23]/issue/[^/]+/comment"), "GET", 1, 1, "comment"),
    (re.compile(r"^/rest/api/[23]/issue/[^/]+/comment"), None, 1, 0, "write"),
    # Confluence content
    (re.compile(r"^/rest/api/content"), "GET", 1, 1, "content"),
    (re.compile(r"^/rest/api/content"), None, 1, 0, "write"),
    # Agile/Scrum boards
    (re.compile(r"^/rest/agile/"), "GET", 1, 1, "issue"),
    # Catch-all: 1 point base for anything else
    (re.compile(r".*"), None, 1, 0, "generic"),
]


def estimate_object_count(call: APICall) -> int:
    """
    Estimate how many objects were returned in the response.
    Uses response bytes as a rough proxy when exact counts aren't available in logs.
    A typical Jira issue JSON is ~2-5KB; we estimate conservatively.
    """
    if call.method != "GET":
        return 0
    if call.response_bytes <= 0:
        return 1
    # Rough estimate: ~3KB per object
    estimated = max(1, call.response_bytes // 3000)
    return min(estimated, 1000)  # cap at 1000 to avoid outliers


def get_endpoint_key(path: str) -> str:
    """Normalize a path to an endpoint key for grouping (strips IDs)."""
    # Replace issue keys like ABC-123
    path = re.sub(r"/[A-Z]+-\d+", "/{issueKey}", path)
    # Replace numeric IDs
    path = re.sub(r"/\d+", "/{id}", path)
    # Strip query string
    path = path.split("?")[0]
    return path


def calculate_points(call: APICall) -> int:
    """Calculate the cloud rate limit points cost for a single API call."""
    endpoint_key = get_endpoint_key(call.path)

    for pattern, method_filter, base_points, per_object_points, _ in ENDPOINT_RULES:
        if not pattern.match(call.path.split("?")[0]):
            continue
        if method_filter and call.method != method_filter:
            continue

        if call.method in ("POST", "PUT", "PATCH", "DELETE"):
            return base_points  # Writes always cost 1 point flat

        object_count = estimate_object_count(call)
        return base_points + (object_count * per_object_points)

    return 1  # fallback


def enrich_calls(calls: list[APICall]) -> list[APICall]:
    """Enrich all API calls with point costs and endpoint keys."""
    for call in calls:
        call.endpoint_key = get_endpoint_key(call.path)
        call.points = calculate_points(call)
    return calls


def analyze_hourly_quota(calls: list[APICall], plan: str = DEFAULT_PLAN) -> dict:
    """
    Group calls by hour and calculate total points consumed per hour.
    Returns analysis vs cloud quota limits.
    """
    limit = CLOUD_QUOTA_LIMITS[plan]
    hourly: DefaultDict[str, int] = defaultdict(int)
    hourly_calls: DefaultDict[str, int] = defaultdict(int)

    for call in calls:
        hour_key = call.timestamp.strftime("%Y-%m-%d %H:00")
        hourly[hour_key] += call.points
        hourly_calls[hour_key] += 1

    results = []
    for hour, points in sorted(hourly.items()):
        pct = (points / limit) * 100
        results.append({
            "hour": hour,
            "calls": hourly_calls[hour],
            "points": points,
            "limit": limit,
            "usage_pct": round(pct, 1),
            "would_breach": points > limit,
            "risk_level": "🔴 BREACH" if points > limit else ("🟡 WARNING" if pct > 75 else "🟢 OK"),
        })

    return {
        "plan": plan,
        "limit_per_hour": limit,
        "hourly_breakdown": results,
        "peak_hour": max(results, key=lambda x: x["points"]) if results else None,
        "breach_count": sum(1 for r in results if r["would_breach"]),
        "warning_count": sum(1 for r in results if not r["would_breach"] and r["usage_pct"] > 75),
    }


def analyze_burst_rates(calls: list[APICall]) -> dict:
    """
    Analyze per-second request rates per endpoint to identify burst limit risks.
    """
    # Group by endpoint + second
    per_endpoint_per_second: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))

    for call in calls:
        second_key = call.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        per_endpoint_per_second[call.endpoint_key][second_key] += 1

    endpoint_analysis = []
    for endpoint, seconds in per_endpoint_per_second.items():
        max_rps = max(seconds.values())
        avg_rps = sum(seconds.values()) / len(seconds)
        breach_seconds = sum(1 for rps in seconds.values() if rps > BURST_STEADY_STATE_RPS)

        endpoint_analysis.append({
            "endpoint": endpoint,
            "max_rps": max_rps,
            "avg_rps": round(avg_rps, 2),
            "breach_seconds": breach_seconds,
            "steady_state_limit": BURST_STEADY_STATE_RPS,
            "risk_level": (
                "🔴 HIGH" if max_rps > BURST_BUCKET_SIZE else
                ("🟡 MEDIUM" if max_rps > BURST_STEADY_STATE_RPS else "🟢 LOW")
            ),
        })

    return {
        "steady_state_rps_limit": BURST_STEADY_STATE_RPS,
        "burst_bucket_size": BURST_BUCKET_SIZE,
        "endpoints": sorted(endpoint_analysis, key=lambda x: x["max_rps"], reverse=True),
    }


def analyze_per_issue_writes(calls: list[APICall]) -> dict:
    """
    Analyze write frequency per issue to identify per-issue write limit risks.
    """
    # Group write calls by issue key + minute
    issue_writes: DefaultDict[str, DefaultDict[str, int]] = defaultdict(lambda: defaultdict(int))

    issue_pattern = re.compile(r"/([A-Z]+-\d+|{issueKey})")

    for call in calls:
        if call.method not in ("POST", "PUT", "PATCH", "DELETE"):
            continue
        match = issue_pattern.search(call.endpoint_key)
        if not match:
            continue
        issue_key = match.group(1)
        minute_key = call.timestamp.strftime("%Y-%m-%d %H:%M")
        issue_writes[issue_key][minute_key] += 1

    risky_issues = []
    for issue, minutes in issue_writes.items():
        max_writes_per_min = max(minutes.values())
        if max_writes_per_min > PER_ISSUE_WRITE_LIMIT:
            risky_issues.append({
                "issue": issue,
                "max_writes_per_minute": max_writes_per_min,
                "limit": PER_ISSUE_WRITE_LIMIT,
                "risk_level": "🔴 HIGH",
            })

    return {
        "per_issue_write_limit": PER_ISSUE_WRITE_LIMIT,
        "risky_issues": risky_issues,
    }

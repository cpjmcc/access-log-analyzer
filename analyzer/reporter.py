"""
reporter.py
Generates human-readable reports for admins showing current API usage
vs Atlassian Cloud rate limits, with clear risk indicators.
"""

from tabulate import tabulate
from colorama import Fore, Style, init
from .parser import APICall
from .calculator import (
    analyze_hourly_quota,
    analyze_burst_rates,
    analyze_per_issue_writes,
    CLOUD_QUOTA_LIMITS,
)

# Initialize colorama for cross-platform color support
init(autoreset=True)


def print_header(title: str):
    print(f"\n{Fore.CYAN}{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}{Style.RESET_ALL}")


def print_section(title: str):
    print(f"\n{Fore.YELLOW}── {title} {'─' * (65 - len(title))}{Style.RESET_ALL}")


def generate_report(calls: list[APICall], product: str, plan: str = "standard", user_count: int = 0, excluded_ips: list = None):
    """Generate a full rate limit risk report for the given API calls."""

    from .calculator import calculate_quota
    effective_quota = calculate_quota(plan, user_count)
    tier = 2 if user_count > 0 else 1

    print_header(f"ACCESS LOG ANALYZER — {product.upper()} DC → CLOUD MIGRATION RISK REPORT")

    if not calls:
        print(f"\n{Fore.RED}  No external API calls found in log file.{Style.RESET_ALL}")
        print("  Check that you specified the correct --product flag and that the log contains REST API calls.\n")
        return

    # ── Summary ──────────────────────────────────────────────────────────────
    print_section("Summary")
    total_points = sum(c.points for c in calls)
    unique_ips = len(set(c.ip for c in calls))
    unique_users = len(set(c.user for c in calls if c.user != "-"))
    unique_endpoints = len(set(c.endpoint_key for c in calls))
    methods = {}
    for c in calls:
        methods[c.method] = methods.get(c.method, 0) + 1

    tier_label = f"Tier 2 Per-Tenant Pool ({user_count:,} users)" if user_count > 0 else "Tier 1 Global Pool"
    print(tabulate([
        ["Total API calls analyzed", f"{len(calls):,}"],
        ["Total points consumed", f"{total_points:,}"],
        ["Unique client IPs", unique_ips],
        ["Unique authenticated users", unique_users],
        ["Unique endpoints hit", unique_endpoints],
        ["HTTP methods", ", ".join(f"{m}:{n}" for m, n in sorted(methods.items()))],
        ["Cloud plan analyzed against", plan.capitalize()],
        ["Rate limit tier", tier_label],
        ["Cloud hourly quota", f"{effective_quota:,} points/hour"],
    ], tablefmt="simple"), "\n")

    # ── Load Balancer / Single IP Warning ────────────────────────────────────
    from collections import Counter
    ip_counts = Counter(c.ip for c in calls)
    if ip_counts:
        top_ip, top_count = ip_counts.most_common(1)[0]
        top_pct = (top_count / len(calls)) * 100
        if top_pct > 90:
            print(f"{Fore.YELLOW}  ⚠️  NOTICE: {top_pct:.0f}% of API traffic originates from a single IP ({top_ip}).{Style.RESET_ALL}")
            print(f"  This is likely a load balancer or reverse proxy forwarding external traffic.")
            print(f"  Do NOT exclude this IP — it would remove all meaningful traffic from the analysis.")
            print(f"  Traffic classification is based on User-Agent and path patterns instead.\n")

    # ── Hourly Quota Analysis ─────────────────────────────────────────────────
    print_section("1. Points-Based Hourly Quota Analysis")
    quota_analysis = analyze_hourly_quota(calls, plan, user_count)

    if quota_analysis["breach_count"] > 0:
        print(f"{Fore.RED}  ⚠️  WARNING: {quota_analysis['breach_count']} hour(s) would BREACH the cloud quota limit!{Style.RESET_ALL}")
    elif quota_analysis["warning_count"] > 0:
        print(f"{Fore.YELLOW}  ⚠️  CAUTION: {quota_analysis['warning_count']} hour(s) are using >75% of cloud quota.{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}  ✅  Usage looks safe — no hours exceed 75% of cloud quota.{Style.RESET_ALL}")

    print()
    rows = [
        [r["hour"], f"{r['calls']:,}", f"{r['points']:,}", f"{r['limit']:,}", f"{r['usage_pct']}%", r["risk_level"]]
        for r in quota_analysis["hourly_breakdown"]
    ]
    print(tabulate(rows, headers=["Hour", "API Calls", "Points Used", "Cloud Limit", "Usage %", "Risk"], tablefmt="simple"))

    if quota_analysis["peak_hour"]:
        p = quota_analysis["peak_hour"]
        print(f"\n  📊 Peak hour: {p['hour']} — {p['points']:,} points ({p['usage_pct']}% of limit)")

    # ── Burst Rate Analysis ───────────────────────────────────────────────────
    print_section("2. Burst Rate Limit Analysis (Requests/Second per Endpoint)")
    burst_analysis = analyze_burst_rates(calls)

    high_risk = [e for e in burst_analysis["endpoints"] if "HIGH" in e["risk_level"]]
    medium_risk = [e for e in burst_analysis["endpoints"] if "MEDIUM" in e["risk_level"]]

    if high_risk:
        print(f"{Fore.RED}  ⚠️  {len(high_risk)} endpoint(s) would likely hit burst limits on Cloud!{Style.RESET_ALL}")
    elif medium_risk:
        print(f"{Fore.YELLOW}  ⚠️  {len(medium_risk)} endpoint(s) occasionally exceed steady-state burst limits.{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}  ✅  All endpoints are within burst rate limits.{Style.RESET_ALL}")

    print(f"\n  Steady-state limit: {burst_analysis['steady_state_rps_limit']} req/sec | Burst bucket: {burst_analysis['burst_bucket_size']} tokens\n")

    # Show top 10 endpoints by max RPS
    top_endpoints = burst_analysis["endpoints"][:10]
    rows = [
        [e["endpoint"][:55], e["max_rps"], e["avg_rps"], e["breach_seconds"], e["risk_level"]]
        for e in top_endpoints
    ]
    print(tabulate(rows, headers=["Endpoint", "Max RPS", "Avg RPS", "Seconds Over Limit", "Risk"], tablefmt="simple"))

    # ── Per-Issue Write Analysis ──────────────────────────────────────────────
    print_section("3. Per-Issue Write Limit Analysis")
    write_analysis = analyze_per_issue_writes(calls)

    if write_analysis["risky_issues"]:
        print(f"{Fore.RED}  ⚠️  {len(write_analysis['risky_issues'])} issue(s) have write rates that would hit Cloud per-issue limits!{Style.RESET_ALL}")
        rows = [
            [i["issue"], i["max_writes_per_minute"], i["limit"], i["risk_level"]]
            for i in write_analysis["risky_issues"]
        ]
        print()
        print(tabulate(rows, headers=["Issue Key", "Max Writes/Min", "Cloud Limit", "Risk"], tablefmt="simple"))
    else:
        print(f"{Fore.GREEN}  ✅  No per-issue write limit violations detected.{Style.RESET_ALL}")

    # ── Top API Consumers ─────────────────────────────────────────────────────
    print_section("4. Top API Consumers (by Points)")
    from collections import defaultdict
    user_points: dict = defaultdict(int)
    user_calls: dict = defaultdict(int)
    for call in calls:
        key = call.user if call.user != "-" else call.ip
        user_points[key] += call.points
        user_calls[key] += 1

    top_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)[:10]
    rows = [
        [user, f"{user_calls[user]:,}", f"{pts:,}", f"{round((pts/total_points)*100, 1)}%"]
        for user, pts in top_users
    ]
    print(tabulate(rows, headers=["User / IP", "API Calls", "Points Used", "% of Total"], tablefmt="simple"))

    # ── Recommendations ───────────────────────────────────────────────────────
    print_section("5. Recommendations")
    recs = []

    if quota_analysis["breach_count"] > 0:
        recs.append(f"🔴 Reduce API call frequency or upgrade to Premium/Enterprise plan (higher quotas)")
        recs.append(f"🔴 Identify and optimize the top consuming users/integrations listed above")
    if high_risk:
        recs.append(f"🟡 Implement request throttling/backoff in integrations hitting high burst rates")
        recs.append(f"🟡 Spread API calls over time instead of batching in tight loops")
    if write_analysis["risky_issues"]:
        recs.append(f"🟡 Review automations that write to the same issue repeatedly in short windows")
    if not recs:
        recs.append(f"✅ Current usage patterns look compatible with Atlassian Cloud rate limits")
        recs.append(f"✅ Continue monitoring as usage grows before migration")

    for rec in recs:
        print(f"  {rec}")

    print(f"\n{Fore.CYAN}{'='*70}{Style.RESET_ALL}\n")

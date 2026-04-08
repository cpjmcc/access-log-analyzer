#!/usr/bin/env python3
"""
main.py — Access Log Analyzer CLI
Analyzes Jira and Confluence Data Center access logs to predict
rate limiting issues when migrating to Atlassian Cloud.

Usage:
  python main.py --log /path/to/access.log --product jira
  python main.py --log /path/to/access.log --product confluence --plan premium
  python main.py --log sample_logs/jira-access.log --product jira
"""

import argparse
import sys
from analyzer.parser import parse_log_file
from analyzer.calculator import enrich_calls, CLOUD_QUOTA_LIMITS
from analyzer.reporter import generate_report
from analyzer.pdf_exporter import generate_pdf


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Jira/Confluence DC access logs for Cloud rate limit risks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --log /var/log/jira/access.log --product jira
  python main.py --log /var/log/confluence/access.log --product confluence --plan premium
  python main.py --log sample_logs/jira-access.log --product jira --plan standard
        """
    )

    parser.add_argument(
        "--log", required=True,
        help="Path to the Jira or Confluence DC access log file"
    )
    parser.add_argument(
        "--product", required=True, choices=["jira", "confluence"],
        help="Which product the log is from (jira or confluence)"
    )
    parser.add_argument(
        "--plan", default="standard", choices=list(CLOUD_QUOTA_LIMITS.keys()),
        help="Atlassian Cloud plan to analyze against (default: standard). Use 'enterprise-max' for large Enterprise orgs (500,000 points/hour)."
    )
    parser.add_argument(
        "--output", default=None,
        help="Optional path to save a PDF report (e.g. --output report.pdf)"
    )
    parser.add_argument(
        "--users", default=0, type=int,
        help=(
            "Number of licensed users in your Atlassian instance. "
            "When provided, uses the Tier 2 Per-Tenant Pool formula: "
            "Standard: 100,000 + (10 × users), "
            "Premium: 130,000 + (20 × users), "
            "Enterprise: 150,000 + (30 × users), capped at 500,000. "
            "Without --users, Tier 1 Global Pool (65,000 points/hour) is used."
        )
    )

    args = parser.parse_args()

    from analyzer.calculator import calculate_quota
    effective_quota = calculate_quota(args.plan, args.users)
    tier = 2 if args.users > 0 else 1

    print(f"\n🔍 Analyzing {args.product.capitalize()} DC access log: {args.log}")
    print(f"   Cloud plan:  {args.plan.capitalize()}")
    if args.users > 0:
        print(f"   Users:       {args.users:,}  →  Tier 2 Per-Tenant Pool")
    else:
        print(f"   Users:       not specified  →  Tier 1 Global Pool")
    print(f"   Hourly quota: {effective_quota:,} points/hour\n")

    try:
        calls = parse_log_file(args.log, args.product)
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}\n")
        sys.exit(1)

    if not calls:
        print("⚠️  No external API calls found. Check your log file and --product flag.\n")
        sys.exit(0)

    calls = enrich_calls(calls)
    generate_report(calls, args.product, args.plan, args.users)

    if args.output:
        generate_pdf(calls, args.product, args.plan, args.output, args.users)


if __name__ == "__main__":
    main()

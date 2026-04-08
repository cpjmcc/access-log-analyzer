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
        help="Atlassian Cloud plan to analyze against (default: standard)"
    )

    args = parser.parse_args()

    print(f"\n🔍 Analyzing {args.product.capitalize()} DC access log: {args.log}")
    print(f"   Cloud plan: {args.plan.capitalize()} ({CLOUD_QUOTA_LIMITS[args.plan]:,} points/hour)\n")

    try:
        calls = parse_log_file(args.log, args.product)
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}\n")
        sys.exit(1)

    if not calls:
        print("⚠️  No external API calls found. Check your log file and --product flag.\n")
        sys.exit(0)

    calls = enrich_calls(calls)
    generate_report(calls, args.product, args.plan)


if __name__ == "__main__":
    main()

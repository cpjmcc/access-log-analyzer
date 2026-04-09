#!/usr/bin/env python3
"""
generate_user_guide.py
Generates a standalone PDF user guide for the Access Log Analyzer tool.
Run with: python3 generate_user_guide.py
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, PageBreak, ListFlowable, ListItem
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime

# ── Colour palette ────────────────────────────────────────────────────────────
ATLASSIAN_BLUE  = colors.HexColor("#0052CC")
ATLASSIAN_LIGHT = colors.HexColor("#DEEBFF")
RED             = colors.HexColor("#DE350B")
RED_LIGHT       = colors.HexColor("#FFEBE6")
YELLOW          = colors.HexColor("#FF991F")
YELLOW_LIGHT    = colors.HexColor("#FFFAE6")
GREEN           = colors.HexColor("#00875A")
GREEN_LIGHT     = colors.HexColor("#E3FCEF")
GREY_LIGHT      = colors.HexColor("#F4F5F7")
GREY_MID        = colors.HexColor("#DFE1E6")
TEXT_DARK       = colors.HexColor("#172B4D")
TEXT_MID        = colors.HexColor("#42526E")
CODE_BG         = colors.HexColor("#F0F0F0")


def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(TEXT_MID)
    canvas.drawCentredString(A4[0] / 2, 10 * mm,
        f"Page {doc.page}  |  Access Log Analyzer — User Guide  |  Generated {datetime.now().strftime('%Y-%m-%d')}")
    canvas.restoreState()


def code_block(text: str, W: float) -> Table:
    """Renders a monospaced code block."""
    rows = [[Paragraph(f'<font name="Courier" size="8" color="#172B4D">{line if line else " "}</font>',
                       ParagraphStyle("code", fontName="Courier", fontSize=8, leading=13))]
            for line in text.strip().split("\n")]
    t = Table(rows, colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), CODE_BG),
        ("BOX",           (0, 0), (-1, -1), 0.5, GREY_MID),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def main():
    output_path = "Access-Log-Analyzer-User-Guide.pdf"
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm,
    )

    W = A4[0] - 36*mm
    styles = {
        "h1": ParagraphStyle("h1", fontSize=22, textColor=ATLASSIAN_BLUE,
                              fontName="Helvetica-Bold", spaceAfter=4),
        "h2": ParagraphStyle("h2", fontSize=14, textColor=ATLASSIAN_BLUE,
                              fontName="Helvetica-Bold", spaceBefore=16, spaceAfter=6),
        "h3": ParagraphStyle("h3", fontSize=11, textColor=TEXT_DARK,
                              fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", fontSize=9.5, textColor=TEXT_DARK,
                                fontName="Helvetica", spaceAfter=5, leading=14),
        "subtitle": ParagraphStyle("subtitle", fontSize=11, textColor=TEXT_MID,
                                    fontName="Helvetica", spaceAfter=12),
        "note": ParagraphStyle("note", fontSize=9, textColor=TEXT_MID,
                                fontName="Helvetica-Oblique", spaceAfter=5, leading=13),
        "footer": ParagraphStyle("footer", fontSize=7, textColor=TEXT_MID,
                                  fontName="Helvetica", alignment=TA_CENTER),
        "warning": ParagraphStyle("warning", fontSize=9, textColor=RED,
                                   fontName="Helvetica-Bold", spaceAfter=4),
        "tip": ParagraphStyle("tip", fontSize=9, textColor=GREEN,
                               fontName="Helvetica-Bold", spaceAfter=4),
    }

    def base_table(data, col_widths, header_bg=ATLASSIAN_BLUE):
        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), header_bg),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0), 9),
            ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",      (0, 1), (-1, -1), 8.5),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
            ("GRID",          (0, 0), (-1, -1), 0.4, GREY_MID),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        return t

    story = []

    # ── Cover ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20*mm))
    story.append(Paragraph("Access Log Analyzer", styles["h1"]))
    story.append(Paragraph("User Guide — Jira &amp; Confluence DC → Cloud Migration", styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=2, color=ATLASSIAN_BLUE, spaceAfter=12))
    story.append(Paragraph(
        "This tool helps Jira and Confluence Data Center administrators analyze their existing "
        "access logs to predict API rate limiting issues before migrating to Atlassian Cloud. "
        "It identifies which integrations, automations, and users are most likely to hit Cloud "
        "rate limits — so you can fix them before they become production incidents.",
        styles["body"]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y')}", styles["note"]))
    story.append(Paragraph(
        "Source: <u>https://github.com/leevan-lambert/access-log-analyzer</u>", styles["note"]
    ))
    story.append(Spacer(1, 8*mm))

    # Quick reference box
    qr_data = [
        ["Quick Reference", ""],
        ["Analyze Jira logs",         "python3 main.py --log access.log --product jira"],
        ["Analyze Confluence logs",    "python3 main.py --log access.log --product confluence"],
        ["Specify plan",              "... --plan standard | premium | enterprise | enterprise-max"],
        ["Include user count",        "... --users 5000"],
        ["Export PDF report",         "... --output report.pdf"],
    ]
    t = Table(qr_data, colWidths=[W*0.3, W*0.7])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), ATLASSIAN_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("SPAN",          (0, 0), (-1, 0)),
        ("ALIGN",         (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME",      (0, 1), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",      (1, 1), (1, -1), "Courier"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.4, GREY_MID),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(t)

    story.append(PageBreak())

    # ── Section 1: Prerequisites ───────────────────────────────────────────────
    story.append(Paragraph("1. Prerequisites", styles["h2"]))
    story.append(Paragraph(
        "Before running the analyzer, ensure you have the following installed on your machine:",
        styles["body"]
    ))

    story.append(Paragraph("Python 3.8 or higher", styles["h3"]))
    story.append(Paragraph("Check your Python version:", styles["body"]))
    story.append(code_block("python3 --version", W))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "If Python is not installed, download it from <u>https://python.org</u> or install via Homebrew on macOS:",
        styles["body"]
    ))
    story.append(code_block("brew install python3", W))
    story.append(Spacer(1, 5))

    story.append(Paragraph("pip3 (Python package manager)", styles["h3"]))
    story.append(Paragraph("Usually included with Python. Verify with:", styles["body"]))
    story.append(code_block("pip3 --version", W))

    # ── Section 2: Installation ────────────────────────────────────────────────
    story.append(Paragraph("2. Installation", styles["h2"]))
    story.append(Paragraph("Step 1 — Clone or download the repository:", styles["h3"]))
    story.append(code_block(
        "git clone https://github.com/leevan-lambert/access-log-analyzer.git\n"
        "cd access-log-analyzer", W
    ))
    story.append(Spacer(1, 5))

    story.append(Paragraph("Step 2 — Install dependencies:", styles["h3"]))
    story.append(code_block("pip3 install -r requirements.txt", W))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "This installs three libraries: tabulate (terminal tables), colorama (terminal colors), "
        "and reportlab (PDF generation).",
        styles["note"]
    ))

    story.append(Paragraph("Step 3 — Verify the installation:", styles["h3"]))
    story.append(code_block(
        "python3 main.py --log sample_logs/jira-access.log --product jira", W
    ))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "You should see a color-coded report in your terminal. If so, you're ready to go!",
        styles["body"]
    ))

    # ── Section 3: Finding Your Logs ──────────────────────────────────────────
    story.append(Paragraph("3. Finding Your Access Logs", styles["h2"]))
    story.append(Paragraph(
        "Access logs are generated by your Jira or Confluence Data Center instance. "
        "Default locations are shown below — your administrator may have configured a custom path.",
        styles["body"]
    ))

    log_data = [
        ["Product", "Default Log Location"],
        ["Jira DC",       "/var/atlassian/application-data/jira/log/access.log"],
        ["Jira DC (alt)", "<jira-home>/log/access.log"],
        ["Confluence DC", "/var/atlassian/application-data/confluence/logs/access.log"],
        ["Confluence DC (alt)", "<confluence-home>/logs/access.log"],
    ]
    story.append(base_table(log_data, [W*0.3, W*0.7]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "💡 Tip: Logs are typically rotated daily. Analyze multiple days for a more accurate picture of your usage patterns.",
        styles["note"]
    ))

    # ── Section 4: Usage ──────────────────────────────────────────────────────
    story.append(Paragraph("4. Running the Analyzer", styles["h2"]))

    story.append(Paragraph("Basic usage:", styles["h3"]))
    story.append(code_block(
        "python3 main.py --log <path-to-log> --product <jira|confluence>", W
    ))
    story.append(Spacer(1, 5))

    story.append(Paragraph("All available options:", styles["h3"]))
    args_data = [
        ["Flag", "Required?", "Description"],
        ["--log",      "✅ Yes", "Path to your Jira or Confluence DC access log file"],
        ["--product",  "✅ Yes", "Which product: jira or confluence"],
        ["--plan",     "Optional", "Cloud plan to analyze against (default: standard). Options: standard, premium, enterprise, enterprise-max"],
        ["--users",    "Optional", "Number of licensed users. Enables Tier 2 Per-Tenant quota formula (more generous limits)"],
        ["--output",   "Optional", "File path to save a PDF report (e.g. --output report.pdf)"],
    ]
    story.append(base_table(args_data, [W*0.2, W*0.15, W*0.65]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Examples:", styles["h3"]))
    story.append(code_block(
        "# Basic Jira analysis against Standard plan\n"
        "python3 main.py --log /var/atlassian/jira/log/access.log --product jira\n\n"
        "# Premium plan with 3,000 users and PDF export\n"
        "python3 main.py --log /var/atlassian/jira/log/access.log \\\n"
        "    --product jira --plan premium --users 3000 --output report.pdf\n\n"
        "# Confluence analysis\n"
        "python3 main.py --log /var/atlassian/confluence/logs/access.log \\\n"
        "    --product confluence --plan enterprise --users 10000 --output confluence-report.pdf",
        W
    ))

    # ── Section 5: Understanding the Quota System ─────────────────────────────
    story.append(Paragraph("5. Understanding Atlassian Cloud Rate Limits", styles["h2"]))
    story.append(Paragraph(
        "Atlassian Cloud uses a points-based rate limiting system. Each API call consumes points "
        "based on its complexity. There are two quota tiers depending on your app type:",
        styles["body"]
    ))

    story.append(Paragraph("Tier 1 — Global Pool (default)", styles["h3"]))
    story.append(Paragraph(
        "All apps share a single global pool of 65,000 points per hour. "
        "Use this when you don't know your user count or are doing an initial assessment.",
        styles["body"]
    ))

    story.append(Paragraph("Tier 2 — Per-Tenant Pool (with --users flag)", styles["h3"]))
    story.append(Paragraph(
        "High-usage apps may qualify for a per-tenant pool. The quota scales with your user count, "
        "capped at 500,000 points/hour. Use --users to unlock this calculation:",
        styles["body"]
    ))

    quota_data = [
        ["Plan", "Flag", "Formula", "Example (5,000 users)", "Cap"],
        ["Standard",   "--plan standard",   "100,000 + (10 × users)", "150,000 pts/hr", "500,000"],
        ["Premium",    "--plan premium",    "130,000 + (20 × users)", "230,000 pts/hr", "500,000"],
        ["Enterprise", "--plan enterprise", "150,000 + (30 × users)", "300,000 pts/hr", "500,000"],
    ]
    story.append(base_table(quota_data, [W*0.15, W*0.22, W*0.28, W*0.22, W*0.13]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("How points are calculated:", styles["h3"]))
    points_data = [
        ["Operation Type", "Point Cost"],
        ["Any write (POST, PUT, PATCH, DELETE)", "1 point flat"],
        ["Read single object (GET issue, page, etc.)", "1 + 1 per object returned"],
        ["Read users / group members", "1 + 2 per user returned"],
        ["Search results", "1 + 1 per issue/item in response"],
    ]
    story.append(base_table(points_data, [W*0.6, W*0.4]))

    # ── Section 6: Understanding the Report ───────────────────────────────────
    story.append(Paragraph("6. Understanding the Report", styles["h2"]))
    story.append(Paragraph(
        "The report has 5 sections. Here's how to interpret each one:", styles["body"]
    ))

    story.append(Paragraph("Section 1 — Points-Based Hourly Quota Analysis", styles["h3"]))
    story.append(Paragraph(
        "Shows how many points your instance consumed each hour vs the Cloud limit. "
        "This is the most important section — any 🔴 BREACH means that hour's worth of API calls "
        "would be rate-limited on Cloud, causing 429 errors for your users and integrations.",
        styles["body"]
    ))

    story.append(Paragraph("Section 2 — Burst Rate Limit Analysis", styles["h3"]))
    story.append(Paragraph(
        "Shows the maximum requests per second (RPS) hitting each endpoint. "
        "Cloud enforces a steady-state limit of ~10 RPS per endpoint with a burst bucket of 100 tokens. "
        "🔴 HIGH endpoints are likely to trigger 429s immediately on Cloud.",
        styles["body"]
    ))

    story.append(Paragraph("Section 3 — Per-Issue Write Limit Analysis", styles["h3"]))
    story.append(Paragraph(
        "Atlassian Cloud limits how many times a single issue can be written to per minute (limit: 10). "
        "Automations that repeatedly update the same issue (e.g. status syncs) commonly hit this.",
        styles["body"]
    ))

    story.append(Paragraph("Section 4 — Top API Consumers", styles["h3"]))
    story.append(Paragraph(
        "Shows which users, service accounts, or IP addresses are consuming the most points. "
        "This helps identify which integrations to prioritize for optimization.",
        styles["body"]
    ))

    story.append(Paragraph("Section 5 — Recommendations", styles["h3"]))
    story.append(Paragraph(
        "Actionable steps prioritized by risk level to address any issues found.",
        styles["body"]
    ))

    risk_data = [
        ["Icon", "Meaning", "Action Required"],
        ["🟢 OK",      "Within safe limits",           "No action needed"],
        ["🟡 WARNING", "75–100% of quota",             "Monitor closely; consider optimizing"],
        ["🔴 BREACH",  "Would exceed Cloud limits",    "Must fix before migration"],
    ]
    story.append(base_table(risk_data, [W*0.18, W*0.32, W*0.5]))

    # ── Section 7: Common Fixes ────────────────────────────────────────────────
    story.append(Paragraph("7. Common Fixes for Rate Limit Issues", styles["h2"]))

    fixes = [
        ("Add delays between API calls",
         "If an integration makes hundreds of calls in a loop, add a sleep() between calls.\n"
         "Example (Python): import time; time.sleep(0.1)  # 100ms between calls"),
        ("Use bulk/batch endpoints",
         "Instead of fetching issues one by one, use /rest/api/2/search with JQL to get many at once.\n"
         "This reduces total call count significantly."),
        ("Implement exponential backoff",
         "When you receive a 429 response, wait and retry with increasing delays:\n"
         "1s → 2s → 4s → 8s → 16s"),
        ("Cache responses",
         "If the same data is fetched multiple times, cache it locally and only refresh periodically."),
        ("Reduce maxResults in searches",
         "Large maxResults values (e.g. 10,000) cost many points. Use pagination with smaller pages."),
        ("Upgrade your Cloud plan",
         "If usage is legitimately high, upgrading from Standard to Premium or Enterprise\n"
         "gives you significantly more quota headroom."),
        ("Specify --users for accurate quota",
         "Run the analyzer with --users <count> to get the Tier 2 per-tenant quota,\n"
         "which may show you have more headroom than you thought."),
    ]

    for i, (title, detail) in enumerate(fixes, 1):
        story.append(Paragraph(f"{i}. {title}", styles["h3"]))
        story.append(code_block(detail, W) if "\n" in detail and ":" in detail
                     else Paragraph(detail, styles["body"]))
        story.append(Spacer(1, 4))

    # ── Section 8: Sample Logs ────────────────────────────────────────────────
    story.append(Paragraph("8. Sample Logs Included", styles["h2"]))
    story.append(Paragraph(
        "The repository includes sample logs to help you get familiar with the tool:", styles["body"]
    ))

    sample_data = [
        ["File", "Product", "Lines", "Scenario"],
        ["sample_logs/jira-access.log",         "Jira", "48",    "Basic — all green"],
        ["sample_logs/jira-access-large.log",   "Jira", "500",   "Medium traffic, mixed users"],
        ["sample_logs/jira-heavy-traffic.log",  "Jira", "2,025", "🔴 Breach & warning scenarios"],
        ["sample_logs/confluence-access.log",   "Confluence", "800", "🟡 Warning scenario"],
    ]
    story.append(base_table(sample_data, [W*0.42, W*0.15, W*0.1, W*0.33]))
    story.append(Spacer(1, 8))
    story.append(code_block(
        "# Try the heavy traffic sample to see what breach warnings look like:\n"
        "python3 main.py --log sample_logs/jira-heavy-traffic.log --product jira --output test.pdf",
        W
    ))

    # ── Section 9: Troubleshooting ────────────────────────────────────────────
    story.append(Paragraph("9. Troubleshooting", styles["h2"]))

    ts_data = [
        ["Error", "Fix"],
        ["No external API calls found",
         "Check --product flag matches the log file. Ensure the log contains /rest/api/ paths."],
        ["FileNotFoundError",
         "Check the path in --log. Use the full absolute path if needed."],
        ["pip: command not found",
         "Use pip3 instead of pip."],
        ["ModuleNotFoundError: No module named 'tabulate'",
         "Run: pip3 install -r requirements.txt"],
        ["Very few API calls parsed",
         "Your log may use a non-standard format. Check the first few lines with: head -5 access.log"],
        ["PDF not generating",
         "Ensure reportlab is installed: pip3 install reportlab"],
    ]
    story.append(base_table(ts_data, [W*0.38, W*0.62]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "For additional help, open an issue at: https://github.com/leevan-lambert/access-log-analyzer/issues",
        styles["note"]
    ))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"\n📄 User guide saved to: {output_path}\n")


if __name__ == "__main__":
    main()

"""
pdf_exporter.py
Generates a clean, professional PDF report of the rate limit analysis
for Jira/Confluence DC → Cloud migration planning.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph,
    Spacer, HRFlowable, PageBreak
)
from reportlab.graphics.shapes import Drawing, Rect, Line, String, Group
from reportlab.graphics import renderPDF
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime
from .parser import APICall
from .calculator import (
    analyze_hourly_quota,
    analyze_burst_rates,
    analyze_per_issue_writes,
    CLOUD_QUOTA_LIMITS,
    calculate_quota,
)
from collections import defaultdict

# ── Colour palette ────────────────────────────────────────────────────────────
ATLASSIAN_BLUE   = colors.HexColor("#0052CC")
ATLASSIAN_LIGHT  = colors.HexColor("#DEEBFF")
RED              = colors.HexColor("#DE350B")
RED_LIGHT        = colors.HexColor("#FFEBE6")
YELLOW           = colors.HexColor("#FF991F")
YELLOW_LIGHT     = colors.HexColor("#FFFAE6")
GREEN            = colors.HexColor("#00875A")
GREEN_LIGHT      = colors.HexColor("#E3FCEF")
GREY_LIGHT       = colors.HexColor("#F4F5F7")
GREY_MID         = colors.HexColor("#DFE1E6")
TEXT_DARK        = colors.HexColor("#172B4D")
TEXT_MID         = colors.HexColor("#42526E")


def risk_color(risk_level: str):
    if "BREACH" in risk_level or "HIGH" in risk_level:
        return RED
    if "WARNING" in risk_level or "MEDIUM" in risk_level:
        return YELLOW
    return GREEN


def risk_bg(risk_level: str):
    if "BREACH" in risk_level or "HIGH" in risk_level:
        return RED_LIGHT
    if "WARNING" in risk_level or "MEDIUM" in risk_level:
        return YELLOW_LIGHT
    return GREEN_LIGHT


def make_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", fontSize=20, textColor=ATLASSIAN_BLUE,
                                 fontName="Helvetica-Bold", spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontSize=11, textColor=TEXT_MID,
                                    fontName="Helvetica", spaceAfter=12),
        "section": ParagraphStyle("section", fontSize=13, textColor=ATLASSIAN_BLUE,
                                   fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6),
        "body": ParagraphStyle("body", fontSize=9, textColor=TEXT_DARK,
                                fontName="Helvetica", spaceAfter=4),
        "warning": ParagraphStyle("warning", fontSize=9, textColor=RED,
                                   fontName="Helvetica-Bold", spaceAfter=6),
        "ok": ParagraphStyle("ok", fontSize=9, textColor=GREEN,
                              fontName="Helvetica-Bold", spaceAfter=6),
        "caution": ParagraphStyle("caution", fontSize=9, textColor=YELLOW,
                                   fontName="Helvetica-Bold", spaceAfter=6),
        "footer": ParagraphStyle("footer", fontSize=7, textColor=TEXT_MID,
                                  fontName="Helvetica", alignment=TA_CENTER),
    }


def base_table_style(header_bg=ATLASSIAN_BLUE):
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  header_bg),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.4, GREY_MID),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ])


def build_hourly_chart(hourly_breakdown: list, quota_limit: int, width: float, height: float = 140) -> Drawing:
    """Build a bar chart of hourly API points usage with a quota limit line."""
    if not hourly_breakdown:
        return Drawing(width, height)

    padding_left = 60
    padding_right = 20
    padding_top = 20
    padding_bottom = 40
    chart_w = width - padding_left - padding_right
    chart_h = height - padding_top - padding_bottom

    # Calculate scale — always show at least the quota limit on Y axis
    max_points = max(max(r["points"] for r in hourly_breakdown), quota_limit)
    y_scale = chart_h / max_points

    drawing = Drawing(width, height)

    # Background
    drawing.add(Rect(padding_left, padding_bottom, chart_w, chart_h,
                     fillColor=GREY_LIGHT, strokeColor=GREY_MID, strokeWidth=0.5))

    # Y axis gridlines + labels (5 intervals)
    intervals = 5
    for i in range(intervals + 1):
        y_val = (max_points / intervals) * i
        y_pos = padding_bottom + (y_val * y_scale)
        # Gridline
        drawing.add(Line(padding_left, y_pos, padding_left + chart_w, y_pos,
                         strokeColor=GREY_MID, strokeWidth=0.5))
        # Y label
        label = f"{int(y_val):,}"
        drawing.add(String(padding_left - 4, y_pos - 3, label,
                           fontSize=6, fillColor=TEXT_MID, textAnchor="end"))

    # Bars
    n = len(hourly_breakdown)
    bar_spacing = chart_w / n
    bar_width = bar_spacing * 0.6

    for i, row in enumerate(hourly_breakdown):
        x = padding_left + (i * bar_spacing) + (bar_spacing - bar_width) / 2
        bar_h = max(row["points"] * y_scale, 1)
        y = padding_bottom

        # Bar colour based on risk
        if "BREACH" in row["risk_level"]:
            bar_color = RED
        elif "WARNING" in row["risk_level"]:
            bar_color = YELLOW
        else:
            bar_color = colors.HexColor("#0065FF")

        drawing.add(Rect(x, y, bar_width, bar_h,
                         fillColor=bar_color, strokeColor=None))

        # Points label above bar
        drawing.add(String(x + bar_width / 2, y + bar_h + 3,
                           f"{row['points']:,}",
                           fontSize=6, fillColor=TEXT_DARK, textAnchor="middle"))

        # X axis label (hour)
        hour_label = row["hour"].split(" ")[1]  # just "HH:00"
        drawing.add(String(x + bar_width / 2, padding_bottom - 12,
                           row["hour"].split(" ")[0],
                           fontSize=5.5, fillColor=TEXT_MID, textAnchor="middle"))
        drawing.add(String(x + bar_width / 2, padding_bottom - 20,
                           hour_label,
                           fontSize=6, fillColor=TEXT_DARK, textAnchor="middle"))

    # Quota limit line (red dashed)
    limit_y = padding_bottom + (quota_limit * y_scale)
    if limit_y <= padding_bottom + chart_h:
        drawing.add(Line(padding_left, limit_y, padding_left + chart_w, limit_y,
                         strokeColor=RED, strokeWidth=1.5, strokeDashArray=[4, 3]))
        drawing.add(String(padding_left + chart_w + 2, limit_y - 3,
                           "Limit", fontSize=6.5, fillColor=RED, textAnchor="start"))

    # Y axis title
    drawing.add(String(10, padding_bottom + chart_h / 2, "Points Used",
                       fontSize=7, fillColor=TEXT_MID, textAnchor="middle"))

    # Chart title
    drawing.add(String(padding_left + chart_w / 2, height - 12,
                       "Hourly API Points Usage vs Cloud Quota Limit",
                       fontSize=8, fillColor=TEXT_DARK, textAnchor="middle",
                       fontName="Helvetica-Bold"))

    return drawing


def add_page_number(canvas, doc):
    """Add footer with page number and generation timestamp."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(TEXT_MID)
    page_text = f"Page {doc.page}  |  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Access Log Analyzer"
    canvas.drawCentredString(A4[0] / 2, 10 * mm, page_text)
    canvas.restoreState()


def generate_pdf(calls: list[APICall], product: str, plan: str, output_path: str, user_count: int = 0):
    """Generate a PDF report and save to output_path."""

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15*mm, leftMargin=15*mm,
        topMargin=18*mm, bottomMargin=18*mm,
    )

    styles = make_styles()
    story = []
    W = A4[0] - 30*mm  # usable width

    effective_quota = calculate_quota(plan, user_count)
    tier = 2 if user_count > 0 else 1
    tier_label = (
        f"Tier 2 Per-Tenant Pool · {user_count:,} users"
        if user_count > 0 else "Tier 1 Global Pool"
    )

    # ── Title ─────────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"{product.capitalize()} DC → Cloud Migration", styles["title"]
    ))
    story.append(Paragraph(
        f"API Rate Limit Risk Report  ·  Plan: <b>{plan.capitalize()}</b>  ·  "
        f"{tier_label}  ·  "
        f"Quota: <b>{effective_quota:,} points/hour</b>  ·  "
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        styles["subtitle"]
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=ATLASSIAN_BLUE, spaceAfter=10))

    # ── Summary table ─────────────────────────────────────────────────────────
    story.append(Paragraph("Summary", styles["section"]))

    total_points = sum(c.points for c in calls)
    unique_ips = len(set(c.ip for c in calls))
    unique_users = len(set(c.user for c in calls if c.user != "-"))
    methods = defaultdict(int)
    for c in calls:
        methods[c.method] += 1
    method_str = "  ".join(f"{m}: {n}" for m, n in sorted(methods.items()))

    summary_data = [
        ["Metric", "Value"],
        ["Total API calls analyzed",    f"{len(calls):,}"],
        ["Total points consumed",        f"{total_points:,}"],
        ["Unique client IPs",            str(unique_ips)],
        ["Unique authenticated users",   str(unique_users)],
        ["HTTP methods",                 method_str],
        ["Cloud plan",                   plan.capitalize()],
        ["Rate limit tier",              tier_label],
        ["Hourly quota limit",           f"{effective_quota:,} points/hour"],
    ]
    t = Table(summary_data, colWidths=[W * 0.45, W * 0.55])
    t.setStyle(base_table_style())
    story.append(t)
    story.append(Spacer(1, 8))

    # ── 1. Hourly Quota ───────────────────────────────────────────────────────
    story.append(Paragraph("1. Points-Based Hourly Quota Analysis", styles["section"]))
    quota = analyze_hourly_quota(calls, plan, user_count)

    if quota["breach_count"] > 0:
        story.append(Paragraph(
            f"⚠ WARNING: {quota['breach_count']} hour(s) would BREACH the cloud quota limit!",
            styles["warning"]
        ))
    elif quota["warning_count"] > 0:
        story.append(Paragraph(
            f"⚠ CAUTION: {quota['warning_count']} hour(s) are using >75% of cloud quota.",
            styles["caution"]
        ))
    else:
        story.append(Paragraph(
            "✓ Usage looks safe — no hours exceed 75% of cloud quota.",
            styles["ok"]
        ))

    quota_rows = [["Hour", "API Calls", "Points Used", "Cloud Limit", "Usage %", "Risk"]]
    quota_style = base_table_style()
    for i, r in enumerate(quota["hourly_breakdown"], start=1):
        quota_rows.append([
            r["hour"], f"{r['calls']:,}", f"{r['points']:,}",
            f"{r['limit']:,}", f"{r['usage_pct']}%", r["risk_level"].replace("🔴 ", "").replace("🟡 ", "").replace("🟢 ", "")
        ])
        bg = risk_bg(r["risk_level"])
        quota_style.add("BACKGROUND", (0, i), (-1, i), bg)
        quota_style.add("TEXTCOLOR", (5, i), (5, i), risk_color(r["risk_level"]))
        quota_style.add("FONTNAME", (5, i), (5, i), "Helvetica-Bold")

    t = Table(quota_rows, colWidths=[W*0.25, W*0.12, W*0.16, W*0.16, W*0.12, W*0.19])
    t.setStyle(quota_style)
    story.append(t)
    story.append(Spacer(1, 10))

    # ── Hourly chart ──────────────────────────────────────────────────────────
    chart = build_hourly_chart(quota["hourly_breakdown"], effective_quota, float(W))
    story.append(chart)
    story.append(Spacer(1, 4))

    # Legend
    legend_data = [["🟦 Normal", "🟨 Warning (>75%)", "🟥 Breach", "--- Quota Limit"]]
    legend_t = Table(legend_data, colWidths=[W*0.25]*4)
    legend_t.setStyle(TableStyle([
        ("FONTSIZE",    (0, 0), (-1, -1), 7),
        ("TEXTCOLOR",   (0, 0), (-1, -1), TEXT_MID),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",  (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
    ]))
    story.append(legend_t)
    story.append(Spacer(1, 8))

    # ── 2. Burst Rate ─────────────────────────────────────────────────────────
    story.append(Paragraph("2. Burst Rate Limit Analysis (Requests/Second per Endpoint)", styles["section"]))
    burst = analyze_burst_rates(calls)

    high = [e for e in burst["endpoints"] if "HIGH" in e["risk_level"]]
    medium = [e for e in burst["endpoints"] if "MEDIUM" in e["risk_level"]]
    if high:
        story.append(Paragraph(f"⚠ {len(high)} endpoint(s) would likely hit burst limits on Cloud!", styles["warning"]))
    elif medium:
        story.append(Paragraph(f"⚠ {len(medium)} endpoint(s) occasionally exceed steady-state burst limits.", styles["caution"]))
    else:
        story.append(Paragraph("✓ All endpoints are within burst rate limits.", styles["ok"]))

    burst_rows = [["Endpoint", "Max RPS", "Avg RPS", "Seconds Over Limit", "Risk"]]
    burst_style = base_table_style()
    for i, e in enumerate(burst["endpoints"][:15], start=1):
        burst_rows.append([
            e["endpoint"][:60], str(e["max_rps"]), str(e["avg_rps"]),
            str(e["breach_seconds"]),
            e["risk_level"].replace("🔴 ", "").replace("🟡 ", "").replace("🟢 ", "")
        ])
        burst_style.add("TEXTCOLOR", (4, i), (4, i), risk_color(e["risk_level"]))
        burst_style.add("FONTNAME", (4, i), (4, i), "Helvetica-Bold")

    t = Table(burst_rows, colWidths=[W*0.42, W*0.1, W*0.1, W*0.22, W*0.16])
    t.setStyle(burst_style)
    story.append(t)
    story.append(Spacer(1, 8))

    # ── 3. Per-Issue Writes ───────────────────────────────────────────────────
    story.append(Paragraph("3. Per-Issue Write Limit Analysis", styles["section"]))
    writes = analyze_per_issue_writes(calls)

    if writes["risky_issues"]:
        story.append(Paragraph(
            f"⚠ {len(writes['risky_issues'])} issue(s) have write rates that would hit Cloud per-issue limits!",
            styles["warning"]
        ))
        write_rows = [["Issue Key", "Max Writes/Min", "Cloud Limit", "Risk"]]
        write_style = base_table_style()
        for i, issue in enumerate(writes["risky_issues"], start=1):
            write_rows.append([
                issue["issue"], str(issue["max_writes_per_minute"]),
                str(issue["limit"]),
                issue["risk_level"].replace("🔴 ", "")
            ])
            write_style.add("BACKGROUND", (0, i), (-1, i), RED_LIGHT)
            write_style.add("TEXTCOLOR", (3, i), (3, i), RED)
            write_style.add("FONTNAME", (3, i), (3, i), "Helvetica-Bold")
        t = Table(write_rows, colWidths=[W*0.3, W*0.25, W*0.25, W*0.2])
        t.setStyle(write_style)
        story.append(t)
    else:
        story.append(Paragraph("✓ No per-issue write limit violations detected.", styles["ok"]))

    story.append(Spacer(1, 8))

    # ── 4. Top Consumers ──────────────────────────────────────────────────────
    story.append(Paragraph("4. Top API Consumers (by Points)", styles["section"]))

    user_points: dict = defaultdict(int)
    user_calls: dict = defaultdict(int)
    for call in calls:
        key = call.user if call.user != "-" else call.ip
        user_points[key] += call.points
        user_calls[key] += 1

    top_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)[:10]
    consumer_rows = [["User / IP", "API Calls", "Points Used", "% of Total"]]
    for user, pts in top_users:
        consumer_rows.append([
            user, f"{user_calls[user]:,}", f"{pts:,}",
            f"{round((pts/total_points)*100, 1)}%"
        ])

    t = Table(consumer_rows, colWidths=[W*0.35, W*0.2, W*0.25, W*0.2])
    t.setStyle(base_table_style())
    story.append(t)
    story.append(Spacer(1, 8))

    # ── 5. Recommendations ────────────────────────────────────────────────────
    story.append(Paragraph("5. Recommendations", styles["section"]))

    recs = []
    if quota["breach_count"] > 0:
        recs.append(("HIGH", "Reduce API call frequency or upgrade to Premium/Enterprise plan (higher quotas)."))
        recs.append(("HIGH", "Identify and optimize the top consuming users/integrations listed above."))
    if high:
        recs.append(("MEDIUM", "Implement request throttling/backoff in integrations hitting high burst rates."))
        recs.append(("MEDIUM", "Spread API calls over time instead of batching in tight loops."))
    if writes["risky_issues"]:
        recs.append(("MEDIUM", "Review automations that write to the same issue repeatedly in short windows."))
    if not recs:
        recs.append(("OK", "Current usage patterns look compatible with Atlassian Cloud rate limits."))
        recs.append(("OK", "Continue monitoring as usage grows before migration."))

    rec_rows = [["Priority", "Recommendation"]]
    rec_style = base_table_style()
    for i, (priority, text) in enumerate(recs, start=1):
        rec_rows.append([priority, text])
        if priority == "HIGH":
            rec_style.add("BACKGROUND", (0, i), (-1, i), RED_LIGHT)
            rec_style.add("TEXTCOLOR", (0, i), (0, i), RED)
            rec_style.add("FONTNAME", (0, i), (0, i), "Helvetica-Bold")
        elif priority == "MEDIUM":
            rec_style.add("BACKGROUND", (0, i), (-1, i), YELLOW_LIGHT)
            rec_style.add("TEXTCOLOR", (0, i), (0, i), YELLOW)
            rec_style.add("FONTNAME", (0, i), (0, i), "Helvetica-Bold")
        else:
            rec_style.add("BACKGROUND", (0, i), (-1, i), GREEN_LIGHT)
            rec_style.add("TEXTCOLOR", (0, i), (0, i), GREEN)
            rec_style.add("FONTNAME", (0, i), (0, i), "Helvetica-Bold")

    t = Table(rec_rows, colWidths=[W*0.15, W*0.85])
    t.setStyle(rec_style)
    story.append(t)

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"\n📄 PDF report saved to: {output_path}\n")

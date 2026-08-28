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
    split_calls_by_type,
)
from collections import defaultdict
from typing import Optional

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


def _round_up_y_max(max_val: int) -> int:
    """Round up to a clean Y-axis maximum with a 10% buffer."""
    buffered = max_val * 1.1  # 10% buffer above max
    # Round up to nearest clean number based on magnitude
    magnitude = 10 ** (len(str(int(buffered))) - 2)
    return int((buffered // magnitude + 1) * magnitude)


def build_hourly_chart(hourly_breakdown: list, quota_limit: int, width: float, height: float = 160, date_label: str = "") -> Drawing:
    """Build a bar chart of hourly API points usage with a quota limit line."""
    if not hourly_breakdown:
        return Drawing(width, height)

    padding_left = 72
    padding_right = 40
    padding_top = 24
    padding_bottom = 44
    chart_w = width - padding_left - padding_right
    chart_h = height - padding_top - padding_bottom

    # Calculate Y axis max — buffer above both max points AND quota limit
    data_max = max(r["points"] for r in hourly_breakdown)
    y_max = _round_up_y_max(max(data_max, quota_limit))
    y_scale = chart_h / y_max

    drawing = Drawing(width, height)

    # Background
    drawing.add(Rect(padding_left, padding_bottom, chart_w, chart_h,
                     fillColor=GREY_LIGHT, strokeColor=GREY_MID, strokeWidth=0.5))

    # Y axis gridlines + labels (5 intervals)
    intervals = 5
    for i in range(intervals + 1):
        y_val = (y_max / intervals) * i
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

        # X axis label — hour only
        hour_label = row["hour"].split(" ")[1]  # just "HH:00"
        drawing.add(String(x + bar_width / 2, padding_bottom - 14,
                           hour_label,
                           fontSize=6.5, fillColor=TEXT_DARK, textAnchor="middle"))

    # Quota limit line (red dashed) — always visible since y_max > quota_limit
    limit_y = padding_bottom + (quota_limit * y_scale)
    drawing.add(Line(padding_left, limit_y, padding_left + chart_w, limit_y,
                     strokeColor=RED, strokeWidth=1.5, strokeDashArray=[4, 3]))
    drawing.add(String(padding_left + chart_w + 4, limit_y - 3,
                       f"Limit\n{quota_limit:,}", fontSize=6, fillColor=RED, textAnchor="start"))

    # Y axis title
    drawing.add(String(10, padding_bottom + chart_h / 2, "Points Used",
                       fontSize=7, fillColor=TEXT_MID, textAnchor="middle"))

    # Chart title — include date range if available
    title = f"Hourly API Points Usage vs Cloud Quota Limit"
    if date_label:
        title += f"  ({date_label})"
    drawing.add(String(padding_left + chart_w / 2, height - 12,
                       title,
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


def generate_pdf(calls: list[APICall], product: str, plan: str, output_path: str, user_count: int = 0, excluded_ips: Optional[list] = None, exclude_system: bool = True):
    """Generate a PDF report and save to output_path."""

    # Filter out unauthenticated/system calls if requested
    split_all = split_calls_by_type(calls)
    if exclude_system:
        analysis_calls = split_all["authenticated_user"] + split_all["service_account"]
    else:
        analysis_calls = calls

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
    system_mode_label = "Excluding System / Unauthenticated Calls" if exclude_system else "Including All Calls (incl. System / Unauthenticated)"

    story.append(Paragraph(
        f"{product.capitalize()} DC → Cloud Migration", styles["title"]
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"API Rate Limit Risk Report",
        styles["subtitle"]
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Plan: <b>{plan.capitalize()}</b>  ·  {tier_label}  ·  Quota: <b>{effective_quota:,} points/hour</b>  ·  {system_mode_label}  ·  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ParagraphStyle("meta", fontSize=8, textColor=TEXT_MID, fontName="Helvetica", spaceAfter=10)
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=ATLASSIAN_BLUE, spaceAfter=14))

    # ── Summary table ─────────────────────────────────────────────────────────
    story.append(Paragraph("Summary", styles["section"]))

    total_points = sum(c.points for c in analysis_calls)
    unique_ips = len(set(c.ip for c in analysis_calls))
    unique_users = len(set(c.user for c in analysis_calls if c.user != "-"))
    methods = defaultdict(int)
    for c in analysis_calls:
        methods[c.method] += 1
    method_str = "  ".join(f"{m}: {n}" for m, n in sorted(methods.items()))

    system_call_count = len(calls) - len(analysis_calls)
    summary_data = [
        ["Metric", "Value"],
        ["Total API calls analyzed",    f"{len(analysis_calls):,}"],
        ["Total points consumed",        f"{total_points:,}"],
        ["Unique client IPs",            str(unique_ips)],
        ["Unique authenticated users",   str(unique_users)],
        ["HTTP methods",                 method_str],
        ["Cloud plan",                   plan.capitalize()],
        ["Rate limit tier",              tier_label],
        ["Hourly quota limit",           f"{effective_quota:,} points/hour"],
        ["System / unauthenticated calls", f"{system_call_count:,} {'(excluded from analysis)' if exclude_system else '(included in analysis)'}"],
    ]
    if excluded_ips:
        summary_data.append(["System IPs excluded", ", ".join(excluded_ips)])
    t = Table(summary_data, colWidths=[W * 0.45, W * 0.55])
    t.setStyle(base_table_style())
    story.append(t)
    story.append(Spacer(1, 8))

    # ── Load Balancer / Single IP Warning ────────────────────────────────────
    from collections import Counter as _Counter
    ip_counts = _Counter(c.ip for c in analysis_calls)
    if ip_counts:
        top_ip, top_count = ip_counts.most_common(1)[0]
        top_pct = (top_count / len(analysis_calls)) * 100
        if top_pct > 90:
            warn_style = ParagraphStyle("lb_warn", fontSize=9, textColor=YELLOW,
                                         fontName="Helvetica-Bold", spaceAfter=4,
                                         backColor=YELLOW_LIGHT, leftIndent=8,
                                         rightIndent=8, borderPad=6)
            note_style = ParagraphStyle("lb_note", fontSize=8.5, textColor=TEXT_DARK,
                                         fontName="Helvetica", spaceAfter=10,
                                         backColor=YELLOW_LIGHT, leftIndent=8,
                                         rightIndent=8, borderPad=4)
            story.append(Paragraph(
                f"⚠ Notice: {top_pct:.0f}% of API traffic originates from a single IP ({top_ip})",
                warn_style
            ))
            story.append(Paragraph(
                "This is likely a load balancer or reverse proxy forwarding external traffic to your "
                "Jira/Confluence server. Do NOT exclude this IP — it would remove all meaningful traffic "
                "from the analysis. Traffic classification is based on User-Agent and path patterns instead.",
                note_style
            ))
            story.append(Spacer(1, 6))

    # ── 1. Hourly Quota ───────────────────────────────────────────────────────
    story.append(Paragraph("1. Points-Based Hourly Quota Analysis", styles["section"]))
    quota = analyze_hourly_quota(analysis_calls, plan, user_count)

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
    # Extract date range from hourly breakdown for chart title
    if quota["hourly_breakdown"]:
        dates = sorted(set(r["hour"].split(" ")[0] for r in quota["hourly_breakdown"]))
        date_label = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
    else:
        date_label = ""
    chart = build_hourly_chart(quota["hourly_breakdown"], effective_quota, float(W), date_label=date_label)
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

    body_style = ParagraphStyle("body2", fontSize=8.5, textColor=TEXT_MID, fontName="Helvetica",
                                 spaceAfter=6, leading=13)
    story.append(Paragraph(
        "Jira Cloud enforces burst rate limits that control how many requests a single tenant can send "
        "<b>per second</b> to a given REST API endpoint. This is separate from the hourly points quota and "
        "uses a <b>token bucket algorithm</b>: each endpoint has a burst buffer (bucket size) that allows "
        "temporary spikes, and a steady-state refill rate that represents the sustained throughput your "
        "integration should be designed around.",
        body_style
    ))
    story.append(Paragraph(
        "Key parameters: <b>Steady-state limit: 10 requests/second</b> per endpoint (design target). "
        "<b>Burst buffer: 100 tokens</b> per endpoint (allows short spikes above steady-state). "
        "Even if your hourly points quota is not exceeded, sending too many requests per second to a "
        "specific endpoint will return <b>HTTP 429</b> for that endpoint until tokens refill. "
        "Endpoints are independent — hitting the limit on one does not affect others.",
        body_style
    ))

    burst = analyze_burst_rates(analysis_calls)

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
    writes = analyze_per_issue_writes(analysis_calls)

    story.append(Paragraph(
        "Jira Cloud enforces a <b>per-issue write limit</b> that restricts how frequently a single issue "
        "can be modified. This limit is independent of the hourly points quota and burst rate limits — "
        "it specifically targets write operations (POST, PUT, PATCH, DELETE) on individual issues.",
        body_style
    ))
    story.append(Paragraph(
        "This limit exists to prevent excessive updates to individual resources, which can degrade "
        "performance for other users accessing the same issue. Common causes include automated status sync "
        "scripts, webhook-triggered update loops, and bulk update scripts that repeatedly process the same "
        "issue. When exceeded, Jira returns <b>HTTP 429</b> with header "
        "<b>RateLimit-Reason: jira-per-issue-on-write</b>. "
        "Cloud limit: <b>" + str(10) + " write operations per issue per minute.</b>",
        body_style
    ))

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
    story.append(Paragraph(
        "API calls are split into three categories based on the authenticated username in the log: "
        "<b>Authenticated Users</b> (real human sessions), <b>Service Accounts</b> (automated integrations "
        "identified by username patterns), and <b>Unauthenticated / System</b> (no username — anonymous "
        "or load-balancer-proxied calls without a user session).",
        ParagraphStyle("consumers_desc", fontSize=8.5, textColor=TEXT_MID, fontName="Helvetica",
                        spaceAfter=8, leading=13)
    ))

    split = split_calls_by_type(analysis_calls)

    def consumer_table(call_subset, label, header_bg=ATLASSIAN_BLUE):
        if not call_subset:
            return
        pts_map = defaultdict(int)
        calls_map = defaultdict(int)
        for c in call_subset:
            key = c.user if c.user != "-" else c.ip
            pts_map[key] += c.points
            calls_map[key] += 1
        subset_pts = sum(pts_map.values())
        subset_pct = round((subset_pts / total_points) * 100, 1) if total_points else 0
        top = sorted(pts_map.items(), key=lambda x: x[1], reverse=True)[:10]

        story.append(Paragraph(
            f"{label} — {len(call_subset):,} calls · {subset_pts:,} points · {subset_pct}% of total",
            ParagraphStyle("consumer_label", fontSize=9, textColor=TEXT_DARK,
                            fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4)
        ))
        rows = [["User / IP", "API Calls", "Points Used", "% of Total"]]
        for user, pts in top:
            rows.append([user, f"{calls_map[user]:,}", f"{pts:,}",
                         f"{round((pts/total_points)*100, 1)}%"])
        t = Table(rows, colWidths=[W*0.38, W*0.18, W*0.24, W*0.2])
        t.setStyle(base_table_style(header_bg=header_bg))
        story.append(t)

    consumer_table(split["authenticated_user"], "👤 Authenticated Users",     ATLASSIAN_BLUE)
    consumer_table(split["service_account"],    "🤖 Service Accounts",        colors.HexColor("#403294"))
    consumer_table(split["unauthenticated"],    "❓ Unauthenticated / System", colors.HexColor("#42526E"))
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

    # ── Methodology & Disclaimer Page ────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Appendix: Methodology & Disclaimer", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID, spaceAfter=10))

    method_style = ParagraphStyle("method", fontSize=8.5, textColor=TEXT_DARK,
                                   fontName="Helvetica", spaceAfter=6, leading=13)
    heading_style = ParagraphStyle("mheading", fontSize=9.5, textColor=ATLASSIAN_BLUE,
                                    fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)

    story.append(Paragraph("How Points Are Calculated", heading_style))
    story.append(Paragraph(
        "Atlassian Cloud uses a points-based model to measure API usage. Rather than simply counting "
        "requests, each API call consumes points based on the work it performs — specifically the amount "
        "of data returned and the complexity of the operation. Every request starts with <b>1 base point</b>. "
        "Write operations (POST, PUT, PATCH, DELETE) always cost <b>1 point flat</b>, regardless of payload size. "
        "Read operations (GET) cost <b>1 base point + additional points per object returned</b>:",
        method_style
    ))

    points_data = [
        ["Object Type", "Cost Per Object", "Notes"],
        ["Jira Issues",            "1 point each",  "Returned by /issue and /search endpoints"],
        ["Comments / Worklogs",    "1 point each",  "Returned by /issue/{key}/comment etc."],
        ["Confluence Pages",       "1 point each",  "Returned by /rest/api/content"],
        ["Users / Group Members",  "2 points each", "Most expensive — large group lookups can cost thousands of points"],
    ]
    pt = Table(points_data, colWidths=[W*0.28, W*0.22, W*0.5])
    pt.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), ATLASSIAN_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.4, GREY_MID),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(pt)

    story.append(Paragraph("How Object Counts Are Estimated", heading_style))
    story.append(Paragraph(
        "Jira and Confluence Data Center access logs record the <b>response size in bytes</b> for each "
        "request, but do not record how many objects (issues, users, pages, etc.) were actually returned. "
        "Since the Atlassian Cloud points system charges per object returned, this analyzer estimates "
        "object counts from response size using endpoint-aware bytes-per-object values:",
        method_style
    ))

    est_data = [
        ["Object Type", "Bytes Per Object", "Rationale"],
        ["Jira Issue",         "~3,000 bytes (3 KB)",  "Typical issue JSON with key, summary, status, assignee, custom fields"],
        ["User / Group Member","~500 bytes",            "Compact user record; note these cost 2 points each on Cloud"],
        ["Comment",            "~1,500 bytes (1.5 KB)", "Comment body + metadata"],
        ["Confluence Page",    "~10,000 bytes (10 KB)", "Page title, body excerpt, metadata, version info"],
        ["Generic (fallback)", "~3,000 bytes (3 KB)",   "Used for endpoints not matching specific patterns above"],
    ]
    et = Table(est_data, colWidths=[W*0.25, W*0.28, W*0.47])
    et.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), ATLASSIAN_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.4, GREY_MID),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(et)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Guardrails applied: minimum of 1 object per successful GET request; maximum of 1,000 objects "
        "per request to prevent runaway estimates from unusually large responses.",
        method_style
    ))

    story.append(Paragraph("Disclaimer & Limitations", heading_style))

    bullet_style = ParagraphStyle("bullet", fontSize=8.5, textColor=TEXT_DARK,
                                   fontName="Helvetica-Bold", spaceAfter=2, leading=13,
                                   leftIndent=12, bulletIndent=0)
    sub_bullet_style = ParagraphStyle("sub_bullet", fontSize=8, textColor=TEXT_MID,
                                       fontName="Helvetica", spaceAfter=6, leading=12,
                                       leftIndent=28, bulletIndent=16)

    disclaimers = [
        ("Object counts are estimated from response bytes, not actual API response data",
         "Point costs may be over or underestimated by 20–50% depending on data density."),
        ("Logs may not capture all API traffic (e.g. internal node-to-node calls)",
         "Actual Cloud usage may differ slightly from what is shown here."),
        ("DC access logs do not include OAuth app identity",
         "All traffic from a single IP is grouped together regardless of which app made the call."),
        ("Burst rate analysis uses per-second granularity from log timestamps",
         "Sub-second bursts within the same logged second are not detectable."),
        ("If traffic passes through a load balancer, per-client IP analysis may be inaccurate",
         "Configure your load balancer to forward the X-Forwarded-For header "
         "(e.g. 'proxy_set_header X-Forwarded-For $remote_addr;' in nginx, or equivalent in HAProxy/F5/AWS ALB). "
         "This preserves the original client IP in the access log, enabling accurate per-client breakdowns "
         "and avoiding the single-IP load balancer warning in this report."),
        ("Cloud rate limits may change over time",
         "Always verify current limits at developer.atlassian.com/cloud/jira/platform/rate-limiting/"),
    ]

    for limitation, impact in disclaimers:
        story.append(Paragraph(f"• {limitation}", bullet_style))
        story.append(Paragraph(f"◦ Impact: {impact}", sub_bullet_style))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "This report is intended as a planning tool to help administrators understand migration risk. "
        "Results should be used as directional guidance, not as precise rate limit predictions. "
        "For authoritative rate limit information, refer to the Atlassian Developer Documentation: "
        "https://developer.atlassian.com/cloud/jira/platform/rate-limiting/",
        ParagraphStyle("disc_footer", fontSize=8, textColor=TEXT_MID, fontName="Helvetica-Oblique",
                        leading=12, spaceAfter=6)
    ))

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"\n📄 PDF report saved to: {output_path}\n")


def generate_streaming_pdf(
    aggregator,
    product: str,
    plan: str,
    output_path: str,
    user_count: int = 0,
    excluded_ips: Optional[list] = None,
    exclude_system: bool = True,
):
    """
    Generate a PDF report using a StreamingAggregator (SQLite-backed).
    
    This function mirrors generate_pdf() but queries aggregated data from the aggregator
    instead of loading APICall objects into Python. This enables large-log processing
    without memory overhead.
    
    Args:
        aggregator: StreamingAggregator instance with ingested calls
        product: 'jira' or 'confluence'
        plan: Cloud plan tier ('free', 'standard', 'premium', 'enterprise')
        output_path: Path to write the PDF
        user_count: Number of cloud tenant users (for Tier 2 quota calculation)
        excluded_ips: List of system IPs excluded from analysis
        exclude_system: If True, exclude unauthenticated/system calls from analysis
    """
    
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

    system_mode_label = "Excluding System / Unauthenticated Calls" if exclude_system else "Including All Calls (incl. System / Unauthenticated)"

    # ── Title ─────────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"{product.capitalize()} DC → Cloud Migration", styles["title"]
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"API Rate Limit Risk Report",
        styles["subtitle"]
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"Plan: <b>{plan.capitalize()}</b>  ·  {tier_label}  ·  Quota: <b>{effective_quota:,} points/hour</b>  ·  {system_mode_label}  ·  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ParagraphStyle("meta", fontSize=8, textColor=TEXT_MID, fontName="Helvetica", spaceAfter=10)
    ))
    story.append(HRFlowable(width="100%", thickness=1.5, color=ATLASSIAN_BLUE, spaceAfter=14))

    # ── Summary table ─────────────────────────────────────────────────────────
    story.append(Paragraph("Summary", styles["section"]))

    # Get summary stats from aggregator
    summary = aggregator.get_summary_stats(
        include_unauthenticated=not exclude_system,
        exclude_unauthenticated=exclude_system
    )
    
    total_calls = summary["total_calls"]
    total_points = summary["total_points"]
    unique_ips = summary["unique_ips"]
    unique_users = summary["unique_users"]
    unique_methods = summary["unique_methods"]
    
    # Get method breakdown from aggregator using aggregate query methods
    methods = aggregator.get_method_counts(exclude_unauthenticated=exclude_system)
    method_str = "  ".join(f"{m}: {n}" for m, n in sorted(methods.items()))
    
    # Get system call count from classification breakdown
    classification_breakdown = aggregator.get_classification_breakdown()
    system_call_count = classification_breakdown.get("unauthenticated", {}).get("calls", 0)

    summary_data = [
        ["Metric", "Value"],
        ["Total API calls analyzed",    f"{total_calls:,}"],
        ["Total points consumed",        f"{total_points:,}"],
        ["Unique client IPs",            str(unique_ips)],
        ["Unique authenticated users",   str(unique_users)],
        ["HTTP methods",                 method_str],
        ["Cloud plan",                   plan.capitalize()],
        ["Rate limit tier",              tier_label],
        ["Hourly quota limit",           f"{effective_quota:,} points/hour"],
        ["System / unauthenticated calls", f"{system_call_count:,} {'(excluded from analysis)' if exclude_system else '(included in analysis)'}"],
    ]
    if excluded_ips:
        summary_data.append(["System IPs excluded", ", ".join(excluded_ips)])
    t = Table(summary_data, colWidths=[W * 0.45, W * 0.55])
    t.setStyle(base_table_style())
    story.append(t)
    story.append(Spacer(1, 8))

    # ── Load Balancer / Single IP Warning ────────────────────────────────────
    ip_counts = aggregator.get_unique_ips()
    if ip_counts and total_calls > 0:
        # Get top IP and its count from aggregator
        top_ip_list = aggregator.get_ip_counts(exclude_unauthenticated=exclude_system, limit=1)
        if top_ip_list:
            top_ip = top_ip_list[0]["ip"]
            top_count = top_ip_list[0]["call_count"]
            top_pct = (top_count / total_calls) * 100
            if top_pct > 90:
                warn_style = ParagraphStyle("lb_warn", fontSize=9, textColor=YELLOW,
                                             fontName="Helvetica-Bold", spaceAfter=4,
                                             backColor=YELLOW_LIGHT, leftIndent=8,
                                             rightIndent=8, borderPad=6)
                note_style = ParagraphStyle("lb_note", fontSize=8.5, textColor=TEXT_DARK,
                                             fontName="Helvetica", spaceAfter=10,
                                             backColor=YELLOW_LIGHT, leftIndent=8,
                                             rightIndent=8, borderPad=4)
                story.append(Paragraph(
                    f"⚠ Notice: {top_pct:.0f}% of API traffic originates from a single IP ({top_ip})",
                    warn_style
                ))
                story.append(Paragraph(
                    "This is likely a load balancer or reverse proxy forwarding external traffic to your "
                    "Jira/Confluence server. Do NOT exclude this IP — it would remove all meaningful traffic "
                    "from the analysis. Traffic classification is based on User-Agent and path patterns instead.",
                    note_style
                ))
                story.append(Spacer(1, 6))

    # ── 1. Hourly Quota ───────────────────────────────────────────────────────
    story.append(Paragraph("1. Points-Based Hourly Quota Analysis", styles["section"]))
    quota_limit = calculate_quota(plan, user_count)
    hourly_rows = aggregator.get_hourly_quota(exclude_unauthenticated=exclude_system)
    hourly_breakdown = []
    for row in hourly_rows:
        points = row["total_points"]
        usage_pct = round((points / quota_limit) * 100, 1) if quota_limit else 0
        risk_level = (
            "🔴 BREACH" if points > quota_limit else
            ("🟡 WARNING" if points > quota_limit * 0.75 else "🟢 OK")
        )
        hourly_breakdown.append({
            "hour": str(row["hour_bucket"])[:13] + ":00",
            "calls": row["call_count"], "points": points,
            "limit": quota_limit, "usage_pct": usage_pct, "risk_level": risk_level,
        })
    quota = {
        "hourly_breakdown": hourly_breakdown,
        "breach_count": sum(1 for row in hourly_breakdown if "BREACH" in row["risk_level"]),
        "warning_count": sum(1 for row in hourly_breakdown if "WARNING" in row["risk_level"]),
    }

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
    if quota["hourly_breakdown"]:
        dates = sorted(set(r["hour"].split(" ")[0] for r in quota["hourly_breakdown"]))
        date_label = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"
    else:
        date_label = ""
    chart = build_hourly_chart(quota["hourly_breakdown"], effective_quota, float(W), date_label=date_label)
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

    body_style = ParagraphStyle("body2", fontSize=8.5, textColor=TEXT_MID, fontName="Helvetica",
                                 spaceAfter=6, leading=13)
    story.append(Paragraph(
        "Jira Cloud enforces burst rate limits that control how many requests a single tenant can send "
        "<b>per second</b> to a given REST API endpoint. This is separate from the hourly points quota and "
        "uses a <b>token bucket algorithm</b>: each endpoint has a burst buffer (bucket size) that allows "
        "temporary spikes, and a steady-state refill rate that represents the sustained throughput your "
        "integration should be designed around.",
        body_style
    ))
    story.append(Paragraph(
        "Key parameters: <b>Steady-state limit: 10 requests/second</b> per endpoint (design target). "
        "<b>Burst buffer: 100 tokens</b> per endpoint (allows short spikes above steady-state). "
        "Even if your hourly points quota is not exceeded, sending too many requests per second to a "
        "specific endpoint will return <b>HTTP 429</b> for that endpoint until tokens refill. "
        "Endpoints are independent — hitting the limit on one does not affect others.",
        body_style
    ))

    burst = aggregator.get_burst_rates(exclude_unauthenticated=exclude_system)

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
    writes = aggregator.get_per_issue_writes(exclude_system)

    story.append(Paragraph(
        "Jira Cloud enforces a <b>per-issue write limit</b> that restricts how frequently a single issue "
        "can be modified. This limit is independent of the hourly points quota and burst rate limits — "
        "it specifically targets write operations (POST, PUT, PATCH, DELETE) on individual issues.",
        body_style
    ))
    story.append(Paragraph(
        "This limit exists to prevent excessive updates to individual resources, which can degrade "
        "performance for other users accessing the same issue. Common causes include automated status sync "
        "scripts, webhook-triggered update loops, and bulk update scripts that repeatedly process the same "
        "issue. When exceeded, Jira returns <b>HTTP 429</b> with header "
        "<b>RateLimit-Reason: jira-per-issue-on-write</b>. "
        "Cloud limit: <b>" + str(10) + " write operations per issue per minute.</b>",
        body_style
    ))

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
    story.append(Paragraph(
        "API calls are split into three categories based on the authenticated username in the log: "
        "<b>Authenticated Users</b> (real human sessions), <b>Service Accounts</b> (automated integrations "
        "identified by username patterns), and <b>Unauthenticated / System</b> (no username — anonymous "
        "or load-balancer-proxied calls without a user session).",
        ParagraphStyle("consumers_desc", fontSize=8.5, textColor=TEXT_MID, fontName="Helvetica",
                        spaceAfter=8, leading=13)
    ))

    breakdown = aggregator.get_classification_breakdown()
    classifications = ["authenticated_user", "service_account"]
    if not exclude_system:
        classifications.append("unauthenticated")
    consumers = {}
    for classification in classifications:
        rows = aggregator.get_top_consumers(classification=classification, limit=10)
        category = breakdown.get(classification, {"calls": 0, "points": 0})
        consumers[classification] = {
            "total_calls": category["calls"],
            "total_points": category["points"],
            "top_consumers": [
                (row["consumer_id"], row["total_points"], row["call_count"])
                for row in rows
            ],
        }

    def consumer_table(calls_in_category, label, header_bg=ATLASSIAN_BLUE):
        if not calls_in_category:
            return
        
        subset_pts = calls_in_category.get("total_points", 0)
        subset_calls = calls_in_category.get("total_calls", 0)
        subset_pct = round((subset_pts / total_points) * 100, 1) if total_points else 0
        top = calls_in_category.get("top_consumers", [])[:10]

        story.append(Paragraph(
            f"{label} — {subset_calls:,} calls · {subset_pts:,} points · {subset_pct}% of total",
            ParagraphStyle("consumer_label", fontSize=9, textColor=TEXT_DARK,
                            fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4)
        ))
        rows = [["User / IP", "API Calls", "Points Used", "% of Total"]]
        for consumer_id, points, calls_count in top:
            rows.append([consumer_id, f"{calls_count:,}", f"{points:,}",
                         f"{round((points/total_points)*100, 1)}%"])
        t = Table(rows, colWidths=[W*0.38, W*0.18, W*0.24, W*0.2])
        t.setStyle(base_table_style(header_bg=header_bg))
        story.append(t)

    consumer_table(consumers.get("authenticated_user", {}), "👤 Authenticated Users", ATLASSIAN_BLUE)
    consumer_table(consumers.get("service_account", {}), "🤖 Service Accounts", colors.HexColor("#403294"))
    consumer_table(consumers.get("unauthenticated", {}), "❓ Unauthenticated / System", colors.HexColor("#42526E"))
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

    # ── Methodology & Disclaimer Page ────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Appendix: Methodology & Disclaimer", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY_MID, spaceAfter=10))

    method_style = ParagraphStyle("method", fontSize=8.5, textColor=TEXT_DARK,
                                   fontName="Helvetica", spaceAfter=6, leading=13)
    heading_style = ParagraphStyle("mheading", fontSize=9.5, textColor=ATLASSIAN_BLUE,
                                    fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)

    story.append(Paragraph("How Points Are Calculated", heading_style))
    story.append(Paragraph(
        "Atlassian Cloud uses a points-based model to measure API usage. Rather than simply counting "
        "requests, each API call consumes points based on the work it performs — specifically the amount "
        "of data returned and the complexity of the operation. Every request starts with <b>1 base point</b>. "
        "Write operations (POST, PUT, PATCH, DELETE) always cost <b>1 point flat</b>, regardless of payload size. "
        "Read operations (GET) cost <b>1 base point + additional points per object returned</b>:",
        method_style
    ))

    points_data = [
        ["Object Type", "Cost Per Object", "Notes"],
        ["Jira Issues",            "1 point each",  "Returned by /issue and /search endpoints"],
        ["Comments / Worklogs",    "1 point each",  "Returned by /issue/{key}/comment etc."],
        ["Confluence Pages",       "1 point each",  "Returned by /rest/api/content"],
        ["Users / Group Members",  "2 points each", "Most expensive — large group lookups can cost thousands of points"],
    ]
    pt = Table(points_data, colWidths=[W*0.28, W*0.22, W*0.5])
    pt.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), ATLASSIAN_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.4, GREY_MID),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(pt)

    story.append(Paragraph("How Object Counts Are Estimated", heading_style))
    story.append(Paragraph(
        "Jira and Confluence Data Center access logs record the <b>response size in bytes</b> for each "
        "request, but do not record how many objects (issues, users, pages, etc.) were actually returned. "
        "Since the Atlassian Cloud points system charges per object returned, this analyzer estimates "
        "object counts from response size using endpoint-aware bytes-per-object values:",
        method_style
    ))

    est_data = [
        ["Object Type", "Bytes Per Object", "Rationale"],
        ["Jira Issue",         "~3,000 bytes (3 KB)",  "Typical issue JSON with key, summary, status, assignee, custom fields"],
        ["User / Group Member","~500 bytes",            "Compact user record; note these cost 2 points each on Cloud"],
        ["Comment",            "~1,500 bytes (1.5 KB)", "Comment body + metadata"],
        ["Confluence Page",    "~10,000 bytes (10 KB)", "Page title, body excerpt, metadata, version info"],
        ["Generic (fallback)", "~3,000 bytes (3 KB)",   "Used for endpoints not matching specific patterns above"],
    ]
    et = Table(est_data, colWidths=[W*0.25, W*0.28, W*0.47])
    et.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), ATLASSIAN_BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, GREY_LIGHT]),
        ("GRID",          (0, 0), (-1, -1), 0.4, GREY_MID),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(et)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Guardrails applied: minimum of 1 object per successful GET request; maximum of 1,000 objects "
        "per request to prevent runaway estimates from unusually large responses.",
        method_style
    ))

    story.append(Paragraph("Disclaimer & Limitations", heading_style))

    bullet_style = ParagraphStyle("bullet", fontSize=8.5, textColor=TEXT_DARK,
                                   fontName="Helvetica-Bold", spaceAfter=2, leading=13,
                                   leftIndent=12, bulletIndent=0)
    sub_bullet_style = ParagraphStyle("sub_bullet", fontSize=8, textColor=TEXT_MID,
                                       fontName="Helvetica", spaceAfter=6, leading=12,
                                       leftIndent=28, bulletIndent=16)

    disclaimers = [
        ("Object counts are estimated from response bytes, not actual API response data",
         "Point costs may be over or underestimated by 20–50% depending on data density."),
        ("Logs may not capture all API traffic (e.g. internal node-to-node calls)",
         "Actual Cloud usage may differ slightly from what is shown here."),
        ("DC access logs do not include OAuth app identity",
         "All traffic from a single IP is grouped together regardless of which app made the call."),
        ("Burst rate analysis uses per-second granularity from log timestamps",
         "Sub-second bursts within the same logged second are not detectable."),
        ("If traffic passes through a load balancer, per-client IP analysis may be inaccurate",
         "Configure your load balancer to forward the X-Forwarded-For header "
         "(e.g. 'proxy_set_header X-Forwarded-For $remote_addr;' in nginx, or equivalent in HAProxy/F5/AWS ALB). "
         "This preserves the original client IP in the access log, enabling accurate per-client breakdowns "
         "and avoiding the single-IP load balancer warning in this report."),
        ("Cloud rate limits may change over time",
         "Always verify current limits at developer.atlassian.com/cloud/jira/platform/rate-limiting/"),
    ]

    for limitation, impact in disclaimers:
        story.append(Paragraph(f"• {limitation}", bullet_style))
        story.append(Paragraph(f"◦ Impact: {impact}", sub_bullet_style))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "This report is intended as a planning tool to help administrators understand migration risk. "
        "Results should be used as directional guidance, not as precise rate limit predictions. "
        "For authoritative rate limit information, refer to the Atlassian Developer Documentation: "
        "https://developer.atlassian.com/cloud/jira/platform/rate-limiting/",
        ParagraphStyle("disc_footer", fontSize=8, textColor=TEXT_MID, fontName="Helvetica-Oblique",
                        leading=12, spaceAfter=6)
    ))

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"\n📄 PDF report saved to: {output_path}\n")

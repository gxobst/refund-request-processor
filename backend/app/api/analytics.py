"""Operational analytics and AI performance metrics API endpoints."""

import csv
from datetime import datetime, timezone
import io
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.refunds import get_repository
from app.db.repository import RefundRepository
from app.schemas.analytics import AnalyticsMetricsResponse, AnalyticsTrendsResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _escape_pdf_str(text: str) -> str:
    """Escape text for use inside PDF literal string parentheses (...) in standard ASCII."""
    ascii_text = text.encode("ascii", "replace").decode("ascii")
    return ascii_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _format_analytics_csv(
    metrics: AnalyticsMetricsResponse,
    category_breakdown: list[dict],
    trends: AnalyticsTrendsResponse,
) -> str:
    """Format operational metrics, node latencies, categories, and trends into CSV format."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # Section 1: OVERALL KPIS
    writer.writerow(["OVERALL KPIS"])
    writer.writerow([
        "Total Requests",
        "Approval Rate",
        "Override Rate",
        "Escalation Rate",
        "Denial Rate",
        "Average Confidence",
        "Average Latency (ms)",
    ])
    escalation_rate = (
        round(metrics.decision_breakdown.escalate / metrics.total_requests, 4)
        if metrics.total_requests > 0
        else 0.0
    )
    denial_rate = (
        round(metrics.decision_breakdown.deny / metrics.total_requests, 4)
        if metrics.total_requests > 0
        else 0.0
    )
    writer.writerow([
        metrics.total_requests,
        f"{metrics.auto_approval_rate:.4f}",
        f"{metrics.override_rate:.4f}",
        f"{escalation_rate:.4f}",
        f"{denial_rate:.4f}",
        f"{metrics.average_confidence:.4f}",
        f"{metrics.average_latency_ms:.2f}",
    ])
    writer.writerow([])

    # Section 2: AGENT NODE LATENCY BREAKDOWN
    writer.writerow(["AGENT NODE LATENCY BREAKDOWN"])
    writer.writerow(["Node", "Average Latency (ms)"])
    nl = metrics.node_latency_breakdown
    writer.writerow(["Classifier", f"{nl.get('classifier', 0.0):.2f}"])
    writer.writerow(["Policy Checker", f"{nl.get('policy_checker', 0.0):.2f}"])
    writer.writerow(["Decision Agent", f"{nl.get('decision_agent', 0.0):.2f}"])
    writer.writerow([])

    # Section 3: CATEGORY BREAKDOWN
    writer.writerow(["CATEGORY BREAKDOWN"])
    writer.writerow(["Category", "Count", "Auto Approved", "Escalated", "Denied"])
    for cat in category_breakdown:
        writer.writerow([
            cat.get("category", "unclassified"),
            cat.get("count", 0),
            cat.get("auto_approved", 0),
            cat.get("escalated", 0),
            cat.get("denied", 0),
        ])
    writer.writerow([])

    # Section 4: TIME-SERIES DAILY TRENDS
    writer.writerow(["TIME-SERIES DAILY TRENDS"])
    writer.writerow([
        "Period",
        "Total Requests",
        "Auto Approved",
        "Denied",
        "Escalated",
        "Average Confidence",
        "Average Latency (ms)",
    ])
    for pt in trends.points:
        writer.writerow([
            pt.period,
            pt.total_requests,
            pt.auto_approved,
            pt.denied,
            pt.escalated,
            f"{pt.average_confidence:.4f}",
            f"{pt.average_latency_ms:.2f}",
        ])

    return output.getvalue()


def _format_analytics_pdf(
    metrics: AnalyticsMetricsResponse,
    category_breakdown: list[dict],
    trends: AnalyticsTrendsResponse,
    start_date: str | None = None,
    end_date: str | None = None,
) -> bytes:
    """Generate a clean, valid PDF-1.4 binary report using pure Python standard library."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_range_str = f"{start_date or 'All time'} to {end_date or 'Present'}"

    commands: list[str] = []

    # Title & Metadata
    commands.append("BT")
    commands.append("/F2 16 Tf")
    commands.append("50 745 Td")
    commands.append(f"({_escape_pdf_str('OPERATIONAL ANALYTICS REPORT')}) Tj")
    commands.append("ET")

    commands.append("BT")
    commands.append("/F1 9 Tf")
    commands.append("50 728 Td")
    commands.append(f"({_escape_pdf_str(f'Date Range: {date_range_str}    |    Generated: {today_str}')}) Tj")
    commands.append("ET")

    # Separator line
    commands.append("0.7 0.7 0.7 RG")
    commands.append("1 w")
    commands.append("50 718 m 562 718 l S")

    current_y = 698

    def add_line(text: str, font: str = "/F1", size: int = 9, indent: int = 50, dy: int = 13):
        nonlocal current_y
        if current_y < 40:
            return
        commands.append("BT")
        commands.append(f"{font} {size} Tf")
        commands.append(f"{indent} {current_y} Td")
        commands.append(f"({_escape_pdf_str(text)}) Tj")
        commands.append("ET")
        current_y -= dy

    def add_section_header(title: str):
        nonlocal current_y
        current_y -= 6
        commands.append("0.9 0.9 0.9 rg")
        commands.append(f"50 {current_y - 2} 512 15 re f")
        commands.append("BT")
        commands.append("/F2 9 Tf")
        commands.append("0 0 0 rg")
        commands.append(f"55 {current_y} Td")
        commands.append(f"({_escape_pdf_str(title)}) Tj")
        commands.append("ET")
        current_y -= 16

    # 1. OVERALL KPIS
    add_section_header("1. OVERALL KPIS")
    approval_rate = metrics.auto_approval_rate
    override_rate = metrics.override_rate
    escalation_rate = (
        round(metrics.decision_breakdown.escalate / metrics.total_requests, 4)
        if metrics.total_requests > 0
        else 0.0
    )
    denial_rate = (
        round(metrics.decision_breakdown.deny / metrics.total_requests, 4)
        if metrics.total_requests > 0
        else 0.0
    )

    add_line(
        f"Total Requests: {metrics.total_requests}         Approval Rate: {approval_rate * 100:.1f}% ({approval_rate:.4f})         Override Rate: {override_rate * 100:.1f}% ({override_rate:.4f})",
        font="/F1",
        size=9,
        indent=55,
        dy=12,
    )
    add_line(
        f"Escalation Rate: {escalation_rate * 100:.1f}% ({escalation_rate:.4f})         Denial Rate: {denial_rate * 100:.1f}% ({denial_rate:.4f})",
        font="/F1",
        size=9,
        indent=55,
        dy=12,
    )
    add_line(
        f"Average Confidence: {metrics.average_confidence:.4f}         Average Latency: {metrics.average_latency_ms:.2f} ms",
        font="/F1",
        size=9,
        indent=55,
        dy=14,
    )

    # 2. AGENT NODE LATENCIES
    add_section_header("2. AGENT NODE LATENCY BREAKDOWN")
    nl = metrics.node_latency_breakdown
    clf_lat = nl.get("classifier", 0.0)
    pol_lat = nl.get("policy_checker", 0.0)
    dec_lat = nl.get("decision_agent", 0.0)
    add_line(
        f"Classifier: {clf_lat:.2f} ms    |    Policy Checker: {pol_lat:.2f} ms    |    Decision Agent: {dec_lat:.2f} ms",
        font="/F1",
        size=9,
        indent=55,
        dy=14,
    )

    # 3. CATEGORY BREAKDOWN
    add_section_header("3. CATEGORY BREAKDOWN")
    add_line(
        f"{'Category':<22} {'Count':<8} {'Auto Approved':<15} {'Escalated':<12} {'Denied':<10}",
        font="/F2",
        size=8,
        indent=55,
        dy=12,
    )
    if not category_breakdown:
        add_line("(No category records in selected range)", font="/F1", size=8, indent=55, dy=12)
    else:
        for cat in category_breakdown[:12]:
            cat_name = str(cat.get("category", "unclassified"))[:20]
            c_cnt = cat.get("count", 0)
            c_app = cat.get("auto_approved", 0)
            c_esc = cat.get("escalated", 0)
            c_den = cat.get("denied", 0)
            add_line(
                f"{cat_name:<22} {c_cnt:<8} {c_app:<15} {c_esc:<12} {c_den:<10}",
                font="/F1",
                size=8,
                indent=55,
                dy=11,
            )

    # 4. TIME-SERIES DAILY TRENDS
    add_section_header("4. TIME-SERIES DAILY TRENDS")
    add_line(
        f"{'Period':<12} {'Total':<8} {'Approved':<12} {'Denied':<10} {'Escalated':<12} {'Avg Conf':<12} {'Latency (ms)':<12}",
        font="/F2",
        size=8,
        indent=55,
        dy=12,
    )
    if not trends.points:
        add_line("(No trend records in selected range)", font="/F1", size=8, indent=55, dy=12)
    else:
        for pt in trends.points[:12]:
            p_period = str(pt.period)[:11]
            add_line(
                f"{p_period:<12} {pt.total_requests:<8} {pt.auto_approved:<12} {pt.denied:<10} {pt.escalated:<12} {pt.average_confidence:<12.2f} {pt.average_latency_ms:<12.1f}",
                font="/F1",
                size=8,
                indent=55,
                dy=11,
            )

    stream_content = "\n".join(commands).encode("latin1")
    stream_length = len(stream_content)

    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n",
        f"6 0 obj\n<< /Length {stream_length} >>\nstream\n".encode("latin1")
        + stream_content
        + b"\nendstream\nendobj\n",
    ]

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")

    offsets: list[int] = []
    for obj in objects:
        offsets.append(buf.tell())
        buf.write(obj)

    xref_offset = buf.tell()
    total_objects = len(objects)
    buf.write(f"xref\n0 {total_objects + 1}\n".encode("latin1"))
    buf.write(b"0000000000 65535 f \r\n")
    for offset in offsets:
        buf.write(f"{offset:010d} 00000 n \r\n".encode("latin1"))

    buf.write(
        f"trailer\n<< /Size {total_objects + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin1")
    )

    return buf.getvalue()


@router.get(
    "/metrics",
    response_model=AnalyticsMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregate operational analytics and AI metrics",
)
def get_analytics_metrics(
    start_date: str | None = Query(None, description="Start date filter (inclusive)."),
    end_date: str | None = Query(None, description="End date filter (inclusive)."),
    repository: RefundRepository = Depends(get_repository),
) -> AnalyticsMetricsResponse:
    """Retrieve operational visibility metrics including decision/status distributions and AI rates."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date",
        )
    return repository.get_analytics_metrics(start_date=start_date, end_date=end_date)


@router.get(
    "/trends",
    response_model=AnalyticsTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get historical trend analytics",
)
def get_analytics_trends(
    start_date: str | None = Query(None, description="Start date filter (inclusive)."),
    end_date: str | None = Query(None, description="End date filter (inclusive)."),
    interval: Literal["daily", "weekly"] = Query("daily", description="Time aggregation interval."),
    repository: RefundRepository = Depends(get_repository),
) -> AnalyticsTrendsResponse:
    """Retrieve historical time-series trends grouped by daily or weekly intervals."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date",
        )
    return repository.get_analytics_trends(
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export operational analytics reports as CSV or PDF",
)
def export_analytics_report(
    format: Literal["csv", "pdf"] = Query("csv", description="Export format ('csv' or 'pdf')."),
    start_date: str | None = Query(None, description="Start date filter (inclusive)."),
    end_date: str | None = Query(None, description="End date filter (inclusive)."),
    repository: RefundRepository = Depends(get_repository),
) -> Response:
    """Export operational analytics KPI summary and trends in CSV or PDF format."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date",
        )

    metrics = repository.get_analytics_metrics(start_date=start_date, end_date=end_date)
    trends = repository.get_analytics_trends(start_date=start_date, end_date=end_date, interval="daily")
    category_breakdown = repository.get_analytics_category_breakdown(start_date=start_date, end_date=end_date)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if format == "csv":
        csv_content = _format_analytics_csv(metrics, category_breakdown, trends)
        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="analytics-report-{today_str}.csv"'},
        )
    else:
        pdf_bytes = _format_analytics_pdf(
            metrics,
            category_breakdown,
            trends,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="analytics-report-{today_str}.pdf"'},
        )

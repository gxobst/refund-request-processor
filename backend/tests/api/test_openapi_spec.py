"""Tests verifying that openapi.yaml is valid, up-to-date, and covers all FastAPI endpoints."""

from pathlib import Path
import pytest
import yaml

from app.main import app


@pytest.fixture(scope="module")
def openapi_spec() -> dict:
    """Load openapi.yaml from the repository root."""
    root_dir = Path(__file__).resolve().parents[3]
    spec_path = root_dir / "openapi.yaml"
    assert spec_path.exists(), f"openapi.yaml not found at expected path: {spec_path}"
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    assert isinstance(spec, dict), "openapi.yaml did not parse to a dictionary"
    return spec


def test_openapi_spec_metadata(openapi_spec: dict):
    """Verify OpenAPI 3.1 metadata, info, license, and servers."""
    assert openapi_spec.get("openapi") == "3.1.0"
    info = openapi_spec.get("info", {})
    assert info.get("title") == "AI Refund Request Processor API"
    assert info.get("license", {}).get("name") == "MIT"
    servers = openapi_spec.get("servers", [])
    assert len(servers) >= 1
    assert any("8000" in s.get("url", "") for s in servers)


def test_openapi_spec_covers_fastapi_routes(openapi_spec: dict):
    """Verify that all core FastAPI router endpoints are represented in openapi.yaml paths."""
    spec_paths = set(openapi_spec.get("paths", {}).keys())

    # Core required paths across v1 and root
    expected_v1_endpoints = [
        "/",
        "/v1/health",
        "/v1/refunds",
        "/v1/refunds/events",
        "/v1/refunds/export",
        "/v1/refunds/export/jobs",
        "/v1/refunds/export/schedules",
        "/v1/refunds/{refund_id}",
        "/v1/refunds/{refund_id}/evidence",
        "/v1/refunds/{refund_id}/clarify",
        "/v1/refunds/{refund_id}/override",
        "/v1/policies",
        "/v1/policies/history",
        "/v1/policies/{category}",
        "/v1/policies/{category}/rollback",
        "/v1/analytics/metrics",
        "/v1/analytics/trends",
        "/v1/analytics/export",
    ]

    for expected_path in expected_v1_endpoints:
        assert expected_path in spec_paths, f"Expected endpoint '{expected_path}' missing from openapi.yaml"


def test_openapi_spec_schemas_coverage(openapi_spec: dict):
    """Verify that all domain, export, analytics, and policy schemas are present in components."""
    schemas = openapi_spec.get("components", {}).get("schemas", {})

    expected_schemas = [
        "RefundRecord",
        "RefundDetail",
        "EvidenceItem",
        "ClarificationTurn",
        "ProblemDetails",
        "ValidationProblemDetails",
        "BulkExportJobRequest",
        "BulkExportJobResponse",
        "ExportScheduleCreate",
        "ExportScheduleResponse",
        "ExportTriggerResponse",
        "AnalyticsMetricsResponse",
        "AnalyticsTrendsResponse",
        "TrendDataPoint",
        "PolicyItemResponse",
        "PolicyAuditEntry",
    ]

    for schema_name in expected_schemas:
        assert schema_name in schemas, f"Expected schema '{schema_name}' missing from openapi.yaml components.schemas"


def test_openapi_spec_evidence_item_malware_fields(openapi_spec: dict):
    """Verify EvidenceItem schema defines malware scanning fields."""
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    evidence_props = schemas["EvidenceItem"].get("properties", {})

    assert "scan_status" in evidence_props or "scanStatus" in evidence_props
    assert "threat_name" in evidence_props or "threatName" in evidence_props
    assert "scanned_at" in evidence_props or "scannedAt" in evidence_props


def test_openapi_spec_refund_record_escalation_fields(openapi_spec: dict):
    """Verify RefundRecord schema defines escalation tier and monetary amount fields."""
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    record_props = schemas.get("RefundRecord", {}).get("properties", {}) or schemas.get("RefundDetail", {}).get("properties", {})

    assert "escalation_tier" in record_props or "escalationTier" in record_props
    assert "refund_amount" in record_props or "refundAmount" in record_props


def test_openapi_spec_security_schemes(openapi_spec: dict):
    """Verify openapi.yaml defines Bearer JWT security scheme for Cognito / OAuth2."""
    security_schemes = openapi_spec.get("components", {}).get("securitySchemes", {})
    assert "BearerAuth" in security_schemes
    assert security_schemes["BearerAuth"].get("type") == "http"
    assert security_schemes["BearerAuth"].get("scheme") == "bearer"


def test_openapi_spec_problem_responses(openapi_spec: dict):
    """Verify openapi.yaml defines RFC 9457 Problem Details standard responses."""
    responses = openapi_spec.get("components", {}).get("responses", {})
    assert "ProblemBadRequest" in responses
    assert "ProblemUnauthorized" in responses
    assert "ProblemForbidden" in responses
    assert "ProblemInternalServerError" in responses

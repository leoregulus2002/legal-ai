from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_liveness_does_not_touch_dependencies(client: TestClient) -> None:
    with (
        patch("app.core.database.Database.ping", new_callable=AsyncMock) as database,
        patch("app.core.redis.RedisClient.ping", new_callable=AsyncMock) as redis,
    ):
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
    database.assert_not_awaited()
    redis.assert_not_awaited()


def test_readiness_checks_dependencies(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_readiness_reports_failure(client: TestClient) -> None:
    with patch(
        "app.core.database.Database.ping",
        new_callable=AsyncMock,
        side_effect=RuntimeError("secret connection details"),
    ):
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable", "redis": "ok"}
    assert "secret" not in response.text


def test_cors_preflight(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

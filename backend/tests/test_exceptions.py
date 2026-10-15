from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.common.exceptions import AppError


def test_app_error(application: FastAPI, client: TestClient) -> None:
    @application.get("/test/error")
    async def failing_route() -> None:
        raise AppError("conflict", "资源冲突", 409)

    response = client.get("/test/error")
    assert response.status_code == 409
    assert response.json()["error"] == {"code": "conflict", "message": "资源冲突"}
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_validation_error(application: FastAPI, client: TestClient) -> None:
    @application.get("/test/validation")
    async def validated_route(count: int) -> dict[str, int]:
        return {"count": count}

    response = client.get("/test/validation?count=secret-input")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "secret-input" not in response.text


def test_unexpected_error(application: FastAPI, client: TestClient) -> None:
    @application.get("/test/unexpected")
    async def crashing_route() -> None:
        raise RuntimeError("private-api-key")

    response = client.get("/test/unexpected")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private-api-key" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_http_error_preserves_headers(application: FastAPI, client: TestClient) -> None:
    @application.get("/test/http-error")
    async def throttled_route() -> None:
        raise HTTPException(status_code=429, detail="请求过于频繁", headers={"Retry-After": "10"})

    response = client.get("/test/http-error")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "10"
    assert response.json()["error"]["code"] == "http_error"


def test_unknown_route(client: TestClient) -> None:
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"

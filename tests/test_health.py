from app.api.health import get_health_checker
from app.config import Settings
from app.main import create_app
from app.schemas import HealthComponent, HealthResponse
from fastapi.testclient import TestClient


def test_health_endpoint() -> None:
    settings = Settings(app_database_url="postgresql+asyncpg://rag:rag@localhost:5432/rag")
    application = create_app(settings)

    class FakeHealthChecker:
        async def check(self) -> HealthResponse:
            return HealthResponse(
                status="ok",
                service="knowledge-alakazam",
                environment="test",
                components={
                    "db": HealthComponent(status="reachable"),
                    "s3": HealthComponent(status="skipped", details={"reason": "disabled"}),
                    "rag_runtime": HealthComponent(status="disabled"),
                },
            )

    application.dependency_overrides[get_health_checker] = lambda: FakeHealthChecker()

    with TestClient(application) as client:
        response = client.get("/health", headers={"X-Request-ID": "request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    assert response.json() == {
        "status": "ok",
        "service": "knowledge-alakazam",
        "environment": "test",
        "components": {
            "db": {"status": "reachable", "details": {}},
            "s3": {"status": "skipped", "details": {"reason": "disabled"}},
            "rag_runtime": {"status": "disabled", "details": {}},
        },
    }

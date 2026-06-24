"""
Phase 1 backend hardening tests.
"""

import asyncio
import os
import subprocess
from uuid import UUID
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _reload_modules():
    pass


def _restore_default_test_modules():
    pass


def _run_coro_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def phase1_env(tmp_path, monkeypatch):
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "phase1.sqlite3"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    env_values = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "JWT_SECRET": "phase1-test-secret-0123456789abcdef",
        "DEBUG": "false",
        "ENABLE_DEMO_AUTH": "true",
        "USE_NEO4J": "false",
        "UPLOAD_DIR": str(upload_dir),
        "CELERY_TASK_ALWAYS_EAGER": "false",
    }
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)

    # Patch settings singleton attributes
    import app.core.config
    settings = app.core.config.get_settings()
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setattr(settings, "upload_dir", upload_dir)
    monkeypatch.setattr(settings, "jwt_secret", "phase1-test-secret-0123456789abcdef")
    monkeypatch.setattr(settings, "enable_demo_auth", True)

    # Patch database engine and session factory
    import app.core.database
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import NullPool

    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
        echo=False
    )
    new_session_factory = async_sessionmaker(
        new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    monkeypatch.setattr(app.core.database, "engine", new_engine)
    monkeypatch.setattr(app.core.database, "async_session_factory", new_session_factory)

    import app.core.auth
    monkeypatch.setattr(app.core.auth, "async_session_factory", new_session_factory)

    import app.api.graph
    monkeypatch.setattr(app.api.graph, "async_session_factory", new_session_factory)

    import app.services.agent
    monkeypatch.setattr(app.services.agent, "async_session_factory", new_session_factory)

    import app.worker
    monkeypatch.setattr(app.worker, "async_session_factory", new_session_factory)

    import app.services.image_processing
    monkeypatch.setattr(app.services.image_processing, "async_session_factory", new_session_factory)

    import app.services.model_registry
    monkeypatch.setattr(app.services.model_registry, "async_session_factory", new_session_factory)

    import app.core.audit
    monkeypatch.setattr(app.core.audit, "async_session_factory", new_session_factory)

    import app.services.document_processing
    monkeypatch.setattr(app.services.document_processing, "async_session_factory", new_session_factory)

    import app.services.evaluation_runner
    monkeypatch.setattr(app.services.evaluation_runner, "async_session_factory", new_session_factory)

    import app.services.audio_processing
    monkeypatch.setattr(app.services.audio_processing, "async_session_factory", new_session_factory)

    import app.services.data_retention
    monkeypatch.setattr(app.services.data_retention, "async_session_factory", new_session_factory)

    import app.services.datasets
    monkeypatch.setattr(app.services.datasets, "async_session_factory", new_session_factory)



    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir)
    subprocess.run(
        [str(backend_dir / ".venv" / "bin" / "alembic"), "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        check=True,
    )

    from app.core.auth import auth_service
    from app.core.database import async_session_factory

    async def _seed_users():
        async with async_session_factory() as session:
            await auth_service.bootstrap_admin_async(
                session,
                email="admin@clinicalgraph.ai",
                password="admin123",
                name="Dr. Admin",
            )
            await auth_service.create_user_async(
                session,
                email="nurse@clinicalgraph.ai",
                name="Nurse Reviewer",
                role="nurse",
                password="nurse123",
                is_active=True,
                created_by_user_id="demo-admin-001",
            )
            await auth_service.create_user_async(
                session,
                email="physician@clinicalgraph.ai",
                name="Dr. Physician",
                role="physician",
                password="physician123",
                is_active=True,
                created_by_user_id="demo-admin-001",
            )
            await session.commit()

    _run_coro_sync(_seed_users())

    try:
        yield {"backend_dir": backend_dir, "db_path": db_path, "upload_dir": upload_dir}
    finally:
        _run_coro_sync(new_engine.dispose())


@pytest.fixture
async def phase1_client(phase1_env):
    from app.api import admin, documents, images
    from app.core.audit import AuditLogMiddleware

    app = FastAPI()
    app.add_middleware(AuditLogMiddleware)
    app.include_router(admin.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(images.router, prefix="/api")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def auth_tokens(phase1_env):
    from app.core.auth import auth_service

    admin_result = auth_service.authenticate("admin@clinicalgraph.ai", "admin123")
    nurse_result = auth_service.authenticate("nurse@clinicalgraph.ai", "nurse123")
    physician_result = auth_service.authenticate("physician@clinicalgraph.ai", "physician123")
    assert admin_result and nurse_result and physician_result
    return {
        "admin": admin_result[1],
        "nurse": nurse_result[1],
        "physician": physician_result[1],
    }


def test_phase1_entity_normalization_fallback():
    from app.services.entity_normalization import entity_normalization_service

    normalized = entity_normalization_service.normalize_with_fallback(
        "Patient has MI and HTN with history of T2DM."
    )
    labels = {item.canonical_label for item in normalized}
    assert "Myocardial Infarction" in labels
    assert "Hypertension" in labels
    assert "Type 2 Diabetes Mellitus" in labels


@pytest.mark.anyio
async def test_phase1_worker_eager_dispatch_bypasses_celery_apply_async(monkeypatch):
    from app import worker

    called = {"runner": False, "apply_async": False}

    class FakeTask:
        def apply_async(self, *args, **kwargs):
            called["apply_async"] = True
            raise AssertionError("Celery apply_async should not be used in eager mode")

    def fake_runner(document_id: str):
        called["runner"] = True
        return {"document_id": document_id, "status": "ready"}

    monkeypatch.setattr(worker.settings, "celery_task_always_eager", True)

    result = await worker._dispatch_task(
        FakeTask(),
        default_job_type="document_processing",
        runner=fake_runner,
        runner_args=("doc-123",),
        task_args=("doc-123",),
        job_id=None,
    )

    assert result["transport"] == "local-eager"
    assert result["result"]["status"] == "ready"
    assert called["runner"] is True
    assert called["apply_async"] is False


@pytest.mark.anyio
async def test_phase1_admin_audit_log_requires_admin(phase1_client, auth_tokens):
    response = await phase1_client.get(
        "/api/admin/audit-log",
        headers={"Authorization": f"Bearer {auth_tokens['nurse']}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


@pytest.mark.anyio
async def test_phase1_audit_log_records_requests(phase1_client, auth_tokens):
    login_response = await phase1_client.post(
        "/api/auth/login",
        json={"email": "admin@clinicalgraph.ai", "password": "admin123"},
    )
    assert login_response.status_code == 200

    response = await phase1_client.get(
        "/api/admin/audit-log",
        headers={"Authorization": f"Bearer {auth_tokens['admin']}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    actions = {item["action"] for item in data["items"]}
    assert "AUTH_LOGIN" in actions or "GET_ADMIN" in actions


@pytest.mark.anyio
async def test_phase1_document_upload_is_queued_and_status_updates(
    phase1_client,
    auth_tokens,
    monkeypatch,
):
    from app.api import documents
    from app.core.auth import auth_service
    from app.schemas.entity_normalization import NormalizedEntity
    from app.services.bm25_index import bm25_index
    from app.services.document_processing import process_document_async
    from app.services.entity_normalization import entity_normalization_service
    from app.services.graph import temporal_graph_service
    from app.services.vector_store import vector_store_service

    monkeypatch.setattr(vector_store_service, "add_document", lambda **kwargs: 3)
    monkeypatch.setattr(
        vector_store_service,
        "get_chunks_for_document",
        lambda document_id: [
            {
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "chunk_text": "Patient has MI and HTN.",
                "document_id": document_id,
                "document_name": "test.txt",
            }
        ],
    )
    monkeypatch.setattr(bm25_index, "add_document", lambda **kwargs: len(kwargs["chunks"]))
    monkeypatch.setattr(bm25_index, "mark_document_deleted", lambda document_id: 0)

    async def delete_document_artifacts(document_id: str):
        return 0

    async def ingest_document_entities(**kwargs):
        return {"nodes": 2, "edges": 1}

    async def export_for_visualization(*, limit: int = 25, tenant_id: str | None = None):
        return {
            "nodes": [
                {"id": "doc-1", "label": "Document"},
                {"id": "cond-1", "label": "Condition"},
            ],
            "links": [
                {"source": "cond-1", "target": "doc-1", "type": "MENTIONED_IN"},
            ],
        }

    monkeypatch.setattr(temporal_graph_service, "delete_document_artifacts", delete_document_artifacts)
    monkeypatch.setattr(temporal_graph_service, "ingest_document_entities", ingest_document_entities)
    monkeypatch.setattr(temporal_graph_service, "export_for_visualization", export_for_visualization)
    monkeypatch.setattr(
        entity_normalization_service,
        "normalize_with_fallback",
        lambda text: [
            NormalizedEntity(
                surface_form="MI",
                canonical_label="Myocardial Infarction",
                ontology="SNOMED CT",
                concept_id="SCTID:22298006",
                semantic_type="Disease",
                confidence="High",
                is_ungrounded=False,
            )
        ],
    )

    async def dispatch(document_id: str, job_id: str | None = None):
        asyncio.get_running_loop().create_task(process_document_async(document_id))
        return {"id": document_id}

    monkeypatch.setattr(documents, "dispatch_document_processing", dispatch)

    response = await phase1_client.post(
        "/api/documents/upload",
        files={"file": ("test.txt", b"Patient has MI and HTN.", "text/plain")},
        headers={"Authorization": f"Bearer {auth_tokens['physician']}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"

    document_id = data["id"]
    final_status = None
    for _ in range(20):
        await asyncio.sleep(0.05)
        status_response = await phase1_client.get(
            f"/api/documents/{document_id}/status",
            headers={"Authorization": f"Bearer {auth_tokens['physician']}"},
        )
        assert status_response.status_code == 200
        final_status = status_response.json()
        if final_status["status"] == "ready":
            break

    assert final_status is not None
    assert final_status["status"] == "ready"
    assert final_status["progress"] == 100
    assert final_status["stage"] == "ready"
    assert final_status["chunk_count"] == 3

    physician_id = auth_service.verify_token(auth_tokens["physician"])["sub"]
    visualization = await temporal_graph_service.export_for_visualization(
        limit=25,
        tenant_id=physician_id,
    )
    node_labels = {node["label"] for node in visualization["nodes"]}
    relation_types = {link["type"] for link in visualization["links"]}
    assert "Document" in node_labels
    assert "Condition" in node_labels
    assert "MENTIONED_IN" in relation_types


@pytest.mark.anyio
async def test_phase1_image_upload_reports_unavailable_analysis_when_no_provider(
    phase1_client,
    auth_tokens,
    monkeypatch,
):
    from app.api import images as images_api

    monkeypatch.setattr(
        images_api.vision_service,
        "get_analysis_capability",
        lambda: {
            "available": False,
            "provider": "gemini",
            "reason": "Image analysis is not configured on this deployment. Set GOOGLE_API_KEY to enable vision analysis.",
        },
    )

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
        b"\x00\x00\x00\x0bIDATx\x9cc`\x00\x02\x00\x00\x05\x00\x01"
        b"\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    response = await phase1_client.post(
        "/api/images/upload",
        headers={"Authorization": f"Bearer {auth_tokens['physician']}"},
        files={"file": ("study.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["analysis_status"] == "uploaded"
    assert data["analysis_available"] is False
    assert "not configured" in data["analysis_unavailable_reason"].lower()


@pytest.mark.anyio
async def test_phase1_image_analyze_returns_clear_provider_error_without_marking_queued(
    phase1_client,
    auth_tokens,
    monkeypatch,
):
    from app.api import images as images_api

    monkeypatch.setattr(
        images_api.vision_service,
        "get_analysis_capability",
        lambda: {
            "available": False,
            "provider": "gemini",
            "reason": "Image analysis is not configured on this deployment. Set GOOGLE_API_KEY to enable vision analysis.",
        },
    )

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
        b"\x00\x00\x00\x0bIDATx\x9cc`\x00\x02\x00\x00\x05\x00\x01"
        b"\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    upload = await phase1_client.post(
        "/api/images/upload",
        headers={"Authorization": f"Bearer {auth_tokens['physician']}"},
        files={"file": ("study.png", png_bytes, "image/png")},
    )
    assert upload.status_code == 200
    image_id = upload.json()["id"]

    analyze = await phase1_client.post(
        f"/api/images/{image_id}/analyze",
        headers={"Authorization": f"Bearer {auth_tokens['physician']}"},
        json={"additional_context": ""},
    )
    assert analyze.status_code == 503
    assert "not configured" in analyze.json()["detail"].lower()

    image = await phase1_client.get(
        f"/api/images/{image_id}",
        headers={"Authorization": f"Bearer {auth_tokens['physician']}"},
    )
    assert image.status_code == 200
    payload = image.json()
    assert payload["analysis_status"] == "uploaded"
    assert "not configured" in payload["last_error"].lower()


@pytest.mark.anyio
async def test_phase1_duplicate_upload_reuses_identical_latest_version(
    phase1_client,
    auth_tokens,
    monkeypatch,
):
    from app.api import documents
    from app.services import document_processing as document_processing_module
    from app.services.document_processing import process_document_async
    from app.services.vector_store import vector_store_service
    from app.services.bm25_index import bm25_index

    monkeypatch.setattr(vector_store_service, "add_document", lambda **kwargs: len(kwargs.get("chunks", [])) or 1)
    monkeypatch.setattr(bm25_index, "add_document", lambda **kwargs: len(kwargs.get("chunks", [])) or 1)
    monkeypatch.setattr(
        document_processing_module.entity_normalization_service,
        "normalize_with_fallback",
        lambda _text: [],
    )

    async def dispatch(document_id: str, job_id: str | None = None):
        asyncio.get_running_loop().create_task(process_document_async(document_id))
        return {"id": document_id}

    monkeypatch.setattr(documents, "dispatch_document_processing", dispatch)

    headers = {"Authorization": f"Bearer {auth_tokens['physician']}"}
    first = await phase1_client.post(
        "/api/documents/upload",
        files={"file": ("repeat.txt", b"same content", "text/plain")},
        headers=headers,
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    second = await phase1_client.post(
        "/api/documents/upload",
        files={"file": ("repeat.txt", b"same content", "text/plain")},
        headers=headers,
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["id"] == first_id
    assert "reused" in payload["message"].lower()


@pytest.mark.anyio
async def test_phase1_document_retry_resets_failed_stage_to_uploaded(
    phase1_client,
    auth_tokens,
    monkeypatch,
):
    from app.api import documents
    from app.core.database import async_session_factory
    from app.models.document import Document
    from app.services.document_pipeline import record_pipeline_stage

    queued_ids: list[str] = []

    async def dispatch(document_id: str, job_id: str | None = None):
        queued_ids.append(document_id)
        return {"id": job_id or document_id}

    monkeypatch.setattr(documents, "dispatch_document_processing", dispatch)

    headers = {"Authorization": f"Bearer {auth_tokens['physician']}"}
    upload = await phase1_client.post(
        "/api/documents/upload",
        files={"file": ("retry.txt", b"retry me", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 200
    document_id = upload.json()["id"]
    queued_ids.clear()

    async with async_session_factory() as session:
        document = await session.get(Document, UUID(document_id))
        assert document is not None
        document.status = "error"
        document.processing_stage = "failed"
        document.processing_progress = 100
        document.error_message = "boom"
        document.metadata_ = record_pipeline_stage(
            document.metadata_,
            "failed",
            state="failed",
            details={"failed_stage": "chunked"},
            error="boom",
        )
        await session.commit()

    retry = await phase1_client.post(
        f"/api/documents/{document_id}/retry",
        headers=headers,
    )
    assert retry.status_code == 200
    payload = retry.json()
    assert payload["status"] == "queued"
    assert payload["stage"] == "uploaded"
    assert payload["progress"] == 5
    assert payload["error_message"] is None
    assert queued_ids == [document_id]


@pytest.mark.anyio
async def test_phase1_document_delete_forbidden_for_nurse(
    phase1_client,
    auth_tokens,
):
    response = await phase1_client.delete(
        "/api/documents/123",
        headers={"Authorization": f"Bearer {auth_tokens['nurse']}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient permissions"


@pytest.mark.anyio
async def test_phase1_drug_interaction_merges_openfda_and_rxnorm(monkeypatch):
    from app.services.tool_registry import tool_drug_interaction

    class DummyResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("HTTP error")

    async def fake_get(self, url, params=None):
        if "rxcui.json" in url:
            return DummyResponse(200, {"idGroup": {"rxnormId": ["29046"]}})
        if "interaction/interaction.json" in url:
            return DummyResponse(
                200,
                {
                    "fullInteractionTypeGroup": [
                        {
                            "sourceName": "RxNorm",
                            "fullInteractionType": [
                                {
                                    "interactionPair": [
                                        {
                                            "description": "Interacts with ibuprofen",
                                            "severity": "moderate",
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            )
        return DummyResponse(
            200,
            {
                "results": [
                    {
                        "patient": {
                            "reaction": [
                                {"reactionmeddrapt": "Hypotension"},
                                {"reactionmeddrapt": "Dizziness"},
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get, raising=False)

    result = await tool_drug_interaction("lisinopril")
    sources = {item["source"] for item in result["interactions"]}
    assert "openfda" in sources
    assert "rxnorm" in sources

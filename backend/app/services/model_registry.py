"""
Model Registry.
Uses durable DB-backed records in application mode and an in-memory fallback for isolated tests.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import desc, select

from app.core.database import async_session_factory
from app.models.persistence import AdapterModelRecord

logger = logging.getLogger(__name__)


@dataclass
class AdapterModel:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    base_model: str = ""
    dataset_name: str = ""
    lora_rank: int = 16
    lora_alpha: int = 32
    training_loss: float | None = None
    eval_scores: dict = field(default_factory=dict)
    adapter_path: str = ""
    is_active: bool = False
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""


class ModelRegistry:
    def __init__(self, *, use_database: bool = False):
        self._use_database = use_database
        self._models: dict[str, AdapterModel] = {}
        self._active_model_id: str | None = None

    @staticmethod
    def _run_sync(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        raise RuntimeError("Use the async model registry methods inside an active event loop.")

    @staticmethod
    def _record_to_model(record: AdapterModelRecord) -> AdapterModel:
        return AdapterModel(
            id=record.id,
            name=record.name,
            base_model=record.base_model,
            dataset_name=record.dataset_name,
            lora_rank=record.lora_rank,
            lora_alpha=record.lora_alpha,
            training_loss=record.training_loss,
            eval_scores=dict(record.eval_scores or {}),
            adapter_path=record.adapter_path,
            is_active=record.is_active,
            version=record.version,
            created_at=record.created_at.isoformat(),
            notes=record.notes,
        )

    # ── In-memory sync API ──────────────────────────────

    def register(
        self,
        name: str,
        base_model: str,
        dataset_name: str = "",
        lora_rank: int = 16,
        lora_alpha: int = 32,
        training_loss: float | None = None,
        eval_scores: dict | None = None,
        adapter_path: str = "",
        notes: str = "",
    ) -> AdapterModel:
        existing = [model for model in self._models.values() if model.name == name]
        version = max((model.version for model in existing), default=0) + 1
        model = AdapterModel(
            name=name,
            base_model=base_model,
            dataset_name=dataset_name,
            lora_rank=lora_rank,
            lora_alpha=lora_alpha,
            training_loss=training_loss,
            eval_scores=eval_scores or {},
            adapter_path=adapter_path,
            version=version,
            notes=notes,
        )
        self._models[model.id] = model
        return model

    def get_model(self, model_id: str) -> AdapterModel | None:
        return self._models.get(model_id)

    def list_models(self) -> list[dict]:
        return [
            {
                "id": model.id,
                "name": model.name,
                "base_model": model.base_model,
                "dataset_name": model.dataset_name,
                "lora_rank": model.lora_rank,
                "training_loss": model.training_loss,
                "eval_scores": model.eval_scores,
                "is_active": model.is_active,
                "version": model.version,
                "created_at": model.created_at,
                "notes": model.notes,
            }
            for model in sorted(self._models.values(), key=lambda item: item.created_at, reverse=True)
        ]

    def delete_model(self, model_id: str) -> bool:
        if model_id in self._models:
            if self._active_model_id == model_id:
                self._active_model_id = None
            del self._models[model_id]
            return True
        return False

    def compare_models(self, model_ids: list[str]) -> list[dict]:
        results = []
        for model_id in model_ids:
            model = self._models.get(model_id)
            if model:
                results.append(
                    {
                        "id": model.id,
                        "name": f"{model.name} v{model.version}",
                        "base_model": model.base_model,
                        "lora_rank": model.lora_rank,
                        "training_loss": model.training_loss,
                        "eval_scores": model.eval_scores,
                        "is_active": model.is_active,
                    }
                )
        return results

    def deploy(self, model_id: str) -> bool:
        model = self._models.get(model_id)
        if not model:
            return False
        if not self._is_deployable(model.adapter_path, model.eval_scores):
            return False
        if self._active_model_id and self._active_model_id in self._models:
            self._models[self._active_model_id].is_active = False
        model.is_active = True
        self._active_model_id = model_id
        return True

    def undeploy(self, model_id: str) -> bool:
        model = self._models.get(model_id)
        if not model:
            return False
        model.is_active = False
        if self._active_model_id == model_id:
            self._active_model_id = None
        return True

    def get_active_model(self) -> AdapterModel | None:
        if self._active_model_id:
            return self._models.get(self._active_model_id)
        return None

    def update_eval_scores(self, model_id: str, scores: dict) -> bool:
        model = self._models.get(model_id)
        if not model:
            return False
        model.eval_scores.update(scores)
        return True

    # ── Async persistent API ────────────────────────────

    async def register_async(
        self,
        name: str,
        base_model: str,
        dataset_name: str = "",
        lora_rank: int = 16,
        lora_alpha: int = 32,
        training_loss: float | None = None,
        eval_scores: dict | None = None,
        adapter_path: str = "",
        notes: str = "",
    ) -> AdapterModel:
        async with async_session_factory() as session:
            version_result = await session.execute(
                select(AdapterModelRecord.version)
                .where(AdapterModelRecord.name == name)
                .order_by(desc(AdapterModelRecord.version))
                .limit(1)
            )
            current_version = version_result.scalar_one_or_none() or 0
            record = AdapterModelRecord(
                name=name,
                base_model=base_model,
                dataset_name=dataset_name,
                lora_rank=lora_rank,
                lora_alpha=lora_alpha,
                training_loss=training_loss,
                eval_scores=eval_scores or {},
                adapter_path=adapter_path,
                notes=notes,
                version=current_version + 1,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return self._record_to_model(record)

    async def get_model_async(self, model_id: str) -> AdapterModel | None:
        async with async_session_factory() as session:
            result = await session.execute(select(AdapterModelRecord).where(AdapterModelRecord.id == model_id))
            record = result.scalar_one_or_none()
            return self._record_to_model(record) if record else None

    async def list_models_async(self) -> list[dict]:
        async with async_session_factory() as session:
            result = await session.execute(select(AdapterModelRecord).order_by(AdapterModelRecord.created_at.desc()))
            records = result.scalars().all()
            return [
                {
                    "id": record.id,
                    "name": record.name,
                    "base_model": record.base_model,
                    "dataset_name": record.dataset_name,
                    "lora_rank": record.lora_rank,
                    "training_loss": record.training_loss,
                    "eval_scores": record.eval_scores or {},
                    "is_active": record.is_active,
                    "version": record.version,
                    "created_at": record.created_at.isoformat(),
                    "notes": record.notes,
                }
                for record in records
            ]

    async def delete_model_async(self, model_id: str) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(AdapterModelRecord).where(AdapterModelRecord.id == model_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True

    async def compare_models_async(self, model_ids: list[str]) -> list[dict]:
        async with async_session_factory() as session:
            result = await session.execute(select(AdapterModelRecord).where(AdapterModelRecord.id.in_(model_ids)))
            records = result.scalars().all()
            return [
                {
                    "id": record.id,
                    "name": f"{record.name} v{record.version}",
                    "base_model": record.base_model,
                    "lora_rank": record.lora_rank,
                    "training_loss": record.training_loss,
                    "eval_scores": record.eval_scores or {},
                    "is_active": record.is_active,
                }
                for record in records
            ]

    async def deploy_async(self, model_id: str) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(AdapterModelRecord).where(AdapterModelRecord.id == model_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            if not self._is_deployable(record.adapter_path, record.eval_scores or {}):
                return False
            active_result = await session.execute(select(AdapterModelRecord).where(AdapterModelRecord.is_active.is_(True)))
            for active in active_result.scalars():
                active.is_active = False
            record.is_active = True
            await session.commit()
            return True

    @staticmethod
    def _is_deployable(adapter_path: str, eval_scores: dict | None) -> bool:
        scores = eval_scores or {}
        return (
            bool(adapter_path)
            and Path(adapter_path).exists()
            and scores.get("deployability_status") == "deployable"
            and scores.get("inference_integration_verified") is True
        )

    async def undeploy_async(self, model_id: str) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(AdapterModelRecord).where(AdapterModelRecord.id == model_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            record.is_active = False
            await session.commit()
            return True

    async def get_active_model_async(self) -> AdapterModel | None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(AdapterModelRecord).where(AdapterModelRecord.is_active.is_(True)).limit(1)
            )
            record = result.scalar_one_or_none()
            return self._record_to_model(record) if record else None

    async def update_eval_scores_async(self, model_id: str, scores: dict) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(AdapterModelRecord).where(AdapterModelRecord.id == model_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            merged = dict(record.eval_scores or {})
            merged.update(scores)
            record.eval_scores = merged
            await session.commit()
            return True


model_registry = ModelRegistry(use_database=True)

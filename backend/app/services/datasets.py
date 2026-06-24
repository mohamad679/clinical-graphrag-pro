"""
Dataset Management Service for fine-tuning.
Uses durable database storage in application mode and an in-memory fallback for isolated tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.database import async_session_factory
from app.models.persistence import DocumentChunk, FineTuneDataset, FineTuneDatasetSample
from app.services.llm import llm_service

logger = logging.getLogger(__name__)


@dataclass
class TrainingSample:
    instruction: str
    input: str
    output: str
    source_doc: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Dataset:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    template: str = "alpaca"
    samples: list[TrainingSample] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    @property
    def sample_count(self) -> int:
        return len(self.samples)


class DatasetService:
    """Manage instruction-tuning datasets."""

    def __init__(self, *, use_database: bool = False):
        self._use_database = use_database
        self._datasets: dict[str, Dataset] = {}

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
        raise RuntimeError("Use the async dataset service methods inside an active event loop.")

    @staticmethod
    def _sample_to_record(sample: TrainingSample, dataset_id: str) -> FineTuneDatasetSample:
        return FineTuneDatasetSample(
            id=sample.id,
            dataset_id=dataset_id,
            instruction=sample.instruction,
            input_text=sample.input,
            output_text=sample.output,
            source_doc=sample.source_doc,
        )

    @staticmethod
    def _record_to_sample(sample: FineTuneDatasetSample) -> TrainingSample:
        return TrainingSample(
            id=sample.id,
            instruction=sample.instruction,
            input=sample.input_text,
            output=sample.output_text,
            source_doc=sample.source_doc,
        )

    @classmethod
    def _record_to_dataset(cls, record: FineTuneDataset) -> Dataset:
        created_at = record.created_at.isoformat()
        updated_at = record.updated_at.isoformat()
        samples = [cls._record_to_sample(sample) for sample in getattr(record, "samples", [])]
        return Dataset(
            id=record.id,
            name=record.name,
            description=record.description,
            template=record.template,
            samples=samples,
            created_at=created_at,
            updated_at=updated_at,
        )

    # ── Sync in-memory API for unit tests ───────────────

    def create_dataset(self, name: str, description: str = "", template: str = "alpaca") -> Dataset:
        ds = Dataset(name=name, description=description, template=template)
        self._datasets[ds.id] = ds
        return ds

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)

    def list_datasets(self) -> list[dict]:
        return [
            {
                "id": ds.id,
                "name": ds.name,
                "description": ds.description,
                "template": ds.template,
                "sample_count": ds.sample_count,
                "created_at": ds.created_at,
            }
            for ds in self._datasets.values()
        ]

    def delete_dataset(self, dataset_id: str) -> bool:
        if dataset_id in self._datasets:
            del self._datasets[dataset_id]
            return True
        return False

    def add_sample(self, dataset_id: str, sample: TrainingSample) -> bool:
        ds = self._datasets.get(dataset_id)
        if not ds:
            return False
        ds.samples.append(sample)
        ds.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def export_jsonl(self, dataset_id: str, output_path: Path | None = None) -> str:
        ds = self._datasets.get(dataset_id)
        if not ds:
            raise ValueError(f"Dataset {dataset_id} not found")
        content = self._render_jsonl(ds)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
        return content

    def validate(self, dataset_id: str) -> dict:
        ds = self._datasets.get(dataset_id)
        if not ds:
            return {"valid": False, "error": "Dataset not found"}
        return self._validate_dataset_payload(ds)

    # ── Async persistent API for application mode ───────

    async def create_dataset_async(self, name: str, description: str = "", template: str = "alpaca") -> Dataset:
        async with async_session_factory() as session:
            record = FineTuneDataset(name=name, description=description, template=template)
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return self._record_to_dataset(record)

    async def get_dataset_async(self, dataset_id: str) -> Dataset | None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(FineTuneDataset)
                .options(selectinload(FineTuneDataset.samples))
                .where(FineTuneDataset.id == dataset_id)
            )
            record = result.scalar_one_or_none()
            return self._record_to_dataset(record) if record else None

    async def list_datasets_async(self) -> list[dict]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(FineTuneDataset, func.count(FineTuneDatasetSample.id))
                .outerjoin(FineTuneDatasetSample, FineTuneDatasetSample.dataset_id == FineTuneDataset.id)
                .group_by(FineTuneDataset.id)
                .order_by(FineTuneDataset.created_at.desc())
            )
            rows = result.all()
            return [
                {
                    "id": dataset.id,
                    "name": dataset.name,
                    "description": dataset.description,
                    "template": dataset.template,
                    "sample_count": int(sample_count or 0),
                    "created_at": dataset.created_at.isoformat(),
                }
                for dataset, sample_count in rows
            ]

    async def delete_dataset_async(self, dataset_id: str) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(FineTuneDataset).where(FineTuneDataset.id == dataset_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            await session.delete(record)
            await session.commit()
            return True

    async def add_sample_async(self, dataset_id: str, sample: TrainingSample) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(select(FineTuneDataset).where(FineTuneDataset.id == dataset_id))
            record = result.scalar_one_or_none()
            if record is None:
                return False
            session.add(self._sample_to_record(sample, dataset_id))
            await session.commit()
            return True

    async def generate_from_documents_async(self, dataset_id: str, num_pairs: int = 20) -> int:
        dataset = await self.get_dataset_async(dataset_id)
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        async with async_session_factory() as session:
            result = await session.execute(select(DocumentChunk).order_by(DocumentChunk.created_at.desc()))
            all_chunks = result.scalars().all()
        if not all_chunks:
            return 0

        sample_size = min(len(all_chunks), num_pairs * 2)
        selected = random.sample(all_chunks, sample_size)

        generated = 0
        for chunk in selected[:num_pairs]:
            chunk_text = chunk.chunk_text
            doc_name = (chunk.metadata_ or {}).get("document_name", "unknown")
            if len(chunk_text) < 50:
                continue
            try:
                prompt = (
                    "Generate ONE clinical question-answer pair from this medical text.\n\n"
                    f"TEXT:\n{chunk_text[:800]}\n\n"
                    "Respond ONLY with JSON:\n"
                    '{"question": "...", "answer": "..."}\n\n'
                    "The question should be specific and clinical. "
                    "The answer should be detailed and grounded in the text."
                )
                response = await llm_service.generate(user_message=prompt, context="")
                pair = self._parse_qa_pair(response)
                if pair:
                    created = await self.add_sample_async(
                        dataset_id,
                        TrainingSample(
                            instruction=pair["question"],
                            input=chunk_text[:500],
                            output=pair["answer"],
                            source_doc=doc_name,
                        ),
                    )
                    if created:
                        generated += 1
            except Exception as exc:
                logger.warning("Failed to generate dataset pair: %s", exc)
        return generated

    async def export_jsonl_async(self, dataset_id: str, output_path: Path | None = None) -> str:
        dataset = await self.get_dataset_async(dataset_id)
        if dataset is None:
            raise ValueError(f"Dataset {dataset_id} not found")
        content = self._render_jsonl(dataset)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
        return content

    async def validate_async(self, dataset_id: str) -> dict:
        dataset = await self.get_dataset_async(dataset_id)
        if dataset is None:
            return {"valid": False, "error": "Dataset not found"}
        return self._validate_dataset_payload(dataset)

    # ── Shared helpers ──────────────────────────────────

    @staticmethod
    def _render_jsonl(dataset: Dataset) -> str:
        lines = []
        for sample in dataset.samples:
            if dataset.template == "sharegpt":
                record = {
                    "conversations": [
                        {"from": "human", "value": f"{sample.instruction}\n\nContext: {sample.input}"},
                        {"from": "gpt", "value": sample.output},
                    ]
                }
            else:
                record = {
                    "instruction": sample.instruction,
                    "input": sample.input,
                    "output": sample.output,
                }
            lines.append(json.dumps(record))
        return "\n".join(lines)

    @staticmethod
    def _validate_dataset_payload(dataset: Dataset) -> dict:
        issues = []
        if dataset.sample_count < 10:
            issues.append(f"Too few samples ({dataset.sample_count}). Minimum recommended: 10")
        empty_outputs = sum(1 for sample in dataset.samples if len(sample.output.strip()) < 10)
        if empty_outputs > 0:
            issues.append(f"{empty_outputs} samples have very short outputs")
        avg_output_len = sum(len(sample.output) for sample in dataset.samples) / max(dataset.sample_count, 1)
        return {
            "valid": len(issues) == 0,
            "sample_count": dataset.sample_count,
            "avg_output_length": round(avg_output_len, 1),
            "issues": issues,
        }

    @staticmethod
    def _parse_qa_pair(response: str) -> dict | None:
        import re

        match = re.search(r"\{[^}]+\}", response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if "question" in data and "answer" in data:
                    return data
            except json.JSONDecodeError:
                return None
        return None


dataset_service = DatasetService(use_database=True)

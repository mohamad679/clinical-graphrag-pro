"""
Honest fine-tuning control plane.

This module owns durable fine-tuning job state and real training orchestration.
It intentionally does not simulate loss curves or create fake adapters. When the
runtime cannot train, jobs are marked with an explicit unavailable status.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import platform
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol

from sqlalchemy import desc, select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.persistence import JobRun
from app.services.datasets import Dataset, TrainingSample, dataset_service

logger = logging.getLogger(__name__)

JOB_TYPE = "fine_tune_training"
ENTITY_TYPE = "fine_tune_dataset"


class FineTuneMode(str, Enum):
    DISABLED = "DISABLED"
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE_MISSING_GPU = "UNAVAILABLE_MISSING_GPU"
    UNAVAILABLE_MISSING_DEPENDENCY = "UNAVAILABLE_MISSING_DEPENDENCY"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    EVALUATED = "EVALUATED"
    EVALUATED_NOT_DEPLOYABLE = "EVALUATED_NOT_DEPLOYABLE"
    DEPLOYABLE = "DEPLOYABLE"
    DEPLOYED = "DEPLOYED"
    CANCELLED = "CANCELLED"


JobStatus = FineTuneMode


@dataclass
class TrainingConfig:
    """LoRA/PEFT training hyperparameters and execution controls."""

    base_model: str = ""
    dataset_id: str = ""
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"])
    learning_rate: float = 2e-4
    scheduler: str = "cosine"
    warmup_steps: int = 10
    batch_size: int = 4
    gradient_accumulation_steps: int = 4
    max_seq_length: int = 2048
    num_epochs: int = 3
    random_seed: int = 20260605
    checkpoint_strategy: str = "epoch"
    evaluation_strategy: str = "epoch"
    gradient_clipping: float = 1.0
    weight_decay: float = 0.01

    def __post_init__(self):
        if not self.base_model:
            self.base_model = get_settings().fine_tune_base_model


@dataclass
class TrainingJob:
    """Durable fine-tuning job view."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    requesting_admin_user_id: str = ""
    config: TrainingConfig = field(default_factory=TrainingConfig)
    status: FineTuneMode = FineTuneMode.AVAILABLE
    adapter_name: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    failure_reason: str | None = None
    output_artifact_path: str | None = None
    evaluation_metrics: dict = field(default_factory=dict)
    deployability_status: str = "not_evaluated"
    worker_task_id: str | None = None
    dispatch_transport: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (
                datetime.fromisoformat(self.completed_at) - datetime.fromisoformat(self.started_at)
            ).total_seconds()
        return None

    @property
    def final_loss(self) -> float | None:
        value = self.evaluation_metrics.get("training_loss")
        return float(value) if isinstance(value, int | float) else None

    @property
    def error_message(self) -> str | None:
        return self.failure_reason

    @property
    def metrics_history(self) -> list:
        return []


@dataclass
class TrainingDatasetSplit:
    train: list[TrainingSample]
    validation: list[TrainingSample]
    fingerprint: str


class TrainingBackend(Protocol):
    def train(
        self,
        *,
        config: TrainingConfig,
        train_samples: list[TrainingSample],
        validation_samples: list[TrainingSample],
        output_dir: Path,
        dataset_fingerprint: str,
    ) -> dict: ...

    def verify_adapter(self, artifact_path: Path, *, base_model: str) -> bool: ...


class PeftTrainingBackend:
    """Real LoRA/PEFT training backend.

    This backend imports training dependencies only when called and invokes the
    real trainer loop. Local tests can inject a lightweight backend that exposes
    the same protocol.
    """

    def train(
        self,
        *,
        config: TrainingConfig,
        train_samples: list[TrainingSample],
        validation_samples: list[TrainingSample],
        output_dir: Path,
        dataset_fingerprint: str,
    ) -> dict:
        from datasets import Dataset as HFDataset
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
        from trl import SFTTrainer

        output_dir.mkdir(parents=True, exist_ok=True)
        tokenizer = AutoTokenizer.from_pretrained(config.base_model)
        model = AutoModelForCausalLM.from_pretrained(config.base_model)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        peft_config = LoraConfig(
            r=config.lora_rank,
            lora_alpha=config.lora_alpha,
            lora_dropout=config.lora_dropout,
            target_modules=config.target_modules,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, peft_config)

        def _format(sample: TrainingSample) -> str:
            return (
                f"Instruction: {sample.instruction}\n"
                f"Input: {sample.input}\n"
                f"Answer: {sample.output}"
            )

        train_dataset = HFDataset.from_dict({"text": [_format(sample) for sample in train_samples]})
        eval_dataset = HFDataset.from_dict({"text": [_format(sample) for sample in validation_samples]})
        args = TrainingArguments(
            output_dir=str(output_dir),
            learning_rate=config.learning_rate,
            lr_scheduler_type=config.scheduler,
            warmup_steps=config.warmup_steps,
            per_device_train_batch_size=config.batch_size,
            per_device_eval_batch_size=config.batch_size,
            gradient_accumulation_steps=config.gradient_accumulation_steps,
            num_train_epochs=config.num_epochs,
            max_grad_norm=config.gradient_clipping,
            weight_decay=config.weight_decay,
            save_strategy=config.checkpoint_strategy,
            eval_strategy=config.evaluation_strategy,
            seed=config.random_seed,
            report_to=[],
        )
        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            dataset_text_field="text",
            max_seq_length=config.max_seq_length,
            args=args,
        )
        train_output = trainer.train()
        eval_metrics = trainer.evaluate()
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(output_dir)

        metadata = {
            "base_model": config.base_model,
            "dataset_fingerprint": dataset_fingerprint,
            "config": asdict(config),
            "training_metrics": getattr(train_output, "metrics", {}),
            "validation_metrics": eval_metrics,
            "environment": runtime_metadata(),
        }
        (output_dir / "adapter_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return metadata

    def verify_adapter(self, artifact_path: Path, *, base_model: str) -> bool:
        from peft import PeftConfig

        if not artifact_path.exists():
            return False
        PeftConfig.from_pretrained(str(artifact_path))
        metadata_path = artifact_path / "adapter_metadata.json"
        if not metadata_path.exists():
            return False
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return metadata.get("base_model") == base_model


def runtime_metadata() -> dict:
    status_short = ""
    try:
        repo_root = Path(__file__).resolve().parents[3]
        status_short = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        commit = None
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "git_commit": commit,
        "working_tree_status_sha256_16": hashlib.sha256(status_short.encode("utf-8")).hexdigest()[:16],
    }


def _has_dependency(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _gpu_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


class FineTuneService:
    """Durable fine-tuning service without fake telemetry."""

    required_dependencies = ("torch", "transformers", "peft", "trl", "datasets")

    def __init__(
        self,
        *,
        use_database: bool = False,
        training_backend: TrainingBackend | None = None,
        dependency_checker=_has_dependency,
        gpu_checker=_gpu_available,
        dataset_backend=dataset_service,
    ):
        self._use_database = use_database
        self._jobs: dict[str, TrainingJob] = {}
        self._training_backend = training_backend or PeftTrainingBackend()
        self._dependency_checker = dependency_checker
        self._gpu_checker = gpu_checker
        self._dataset_backend = dataset_backend

    @property
    def _gpu_available(self) -> bool:
        return self._gpu_checker()

    def runtime_mode(self) -> FineTuneMode:
        settings = get_settings()
        if not settings.enable_fine_tune:
            return FineTuneMode.DISABLED
        missing = [dep for dep in self.required_dependencies if not self._dependency_checker(dep)]
        if missing:
            return FineTuneMode.UNAVAILABLE_MISSING_DEPENDENCY
        if not self._gpu_checker():
            return FineTuneMode.UNAVAILABLE_MISSING_GPU
        return FineTuneMode.AVAILABLE

    @staticmethod
    def validate_dataset(dataset: Dataset) -> dict:
        issues: list[str] = []
        for index, sample in enumerate(dataset.samples):
            if not sample.instruction or not sample.instruction.strip():
                issues.append(f"sample[{index}].instruction is required")
            if not sample.output or len(sample.output.strip()) < 3:
                issues.append(f"sample[{index}].output is required")
        if len(dataset.samples) < 2:
            issues.append("At least two samples are required for deterministic train/validation split")
        return {"valid": not issues, "sample_count": len(dataset.samples), "issues": issues}

    @staticmethod
    def dataset_fingerprint(samples: list[TrainingSample]) -> str:
        rows = [
            {
                "id": sample.id,
                "instruction": sample.instruction,
                "input": sample.input,
                "output": sample.output,
                "source_doc": sample.source_doc,
            }
            for sample in sorted(samples, key=lambda item: item.id)
        ]
        return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()

    @classmethod
    def split_dataset(cls, dataset: Dataset, *, seed: int, validation_fraction: float = 0.2) -> TrainingDatasetSplit:
        samples = sorted(dataset.samples, key=lambda item: hashlib.sha256(f"{seed}:{item.id}".encode()).hexdigest())
        validation_count = max(1, min(len(samples) - 1, round(len(samples) * validation_fraction)))
        validation = samples[:validation_count]
        train = samples[validation_count:]
        return TrainingDatasetSplit(
            train=train,
            validation=validation,
            fingerprint=cls.dataset_fingerprint(dataset.samples),
        )

    @staticmethod
    def _job_from_record(record: JobRun) -> TrainingJob:
        payload = dict(record.payload or {})
        result = dict(record.result or {})
        metadata = dict(record.metadata_ or {})
        config_payload = payload.get("config", {})
        status = FineTuneService._normalize_job_status(record.status)
        return TrainingJob(
            id=str(record.id),
            tenant_id=metadata.get("tenant_id", ""),
            requesting_admin_user_id=record.created_by_user_id or metadata.get("requesting_admin_user_id", ""),
            config=TrainingConfig(**config_payload),
            status=status,
            adapter_name=payload.get("adapter_name", ""),
            created_at=record.queued_at.isoformat(),
            started_at=record.started_at.isoformat() if record.started_at else None,
            completed_at=record.completed_at.isoformat() if record.completed_at else None,
            failure_reason=record.error_message,
            output_artifact_path=result.get("output_artifact_path"),
            evaluation_metrics=result.get("evaluation_metrics") or {},
            deployability_status=result.get("deployability_status", "not_evaluated"),
            worker_task_id=record.worker_task_id,
            dispatch_transport=metadata.get("dispatch_transport"),
        )

    @staticmethod
    def _normalize_job_status(status: str) -> FineTuneMode:
        try:
            return FineTuneMode(status)
        except ValueError:
            transitional = {
                "pending": FineTuneMode.AVAILABLE,
                "queued": FineTuneMode.AVAILABLE,
                "dispatched": FineTuneMode.AVAILABLE,
                "running": FineTuneMode.RUNNING,
                "completed": FineTuneMode.COMPLETED,
                "failed": FineTuneMode.FAILED,
                "cancelled": FineTuneMode.CANCELLED,
            }
            return transitional.get(status, FineTuneMode.FAILED)

    @staticmethod
    def _job_dict(job: TrainingJob) -> dict:
        return {
            "id": job.id,
            "tenant_id": job.tenant_id,
            "requesting_admin_user_id": job.requesting_admin_user_id,
            "adapter_name": job.adapter_name,
            "status": job.status.value,
            "base_model": job.config.base_model,
            "dataset_id": job.config.dataset_id,
            "lora_rank": job.config.lora_rank,
            "lora_alpha": job.config.lora_alpha,
            "num_epochs": job.config.num_epochs,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
            "duration": job.duration_seconds,
            "failure_reason": job.failure_reason,
            "output_artifact_path": job.output_artifact_path,
            "evaluation_metrics": job.evaluation_metrics,
            "deployability_status": job.deployability_status,
            "worker_task_id": job.worker_task_id,
            "dispatch_transport": job.dispatch_transport,
        }

    def create_job(
        self,
        config: TrainingConfig,
        adapter_name: str = "",
        *,
        tenant_id: str = "",
        requesting_admin_user_id: str = "",
    ) -> TrainingJob:
        adapter_name = adapter_name or f"clinical-lora-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
        job = TrainingJob(
            config=config,
            adapter_name=adapter_name,
            tenant_id=tenant_id,
            requesting_admin_user_id=requesting_admin_user_id,
            status=FineTuneMode.AVAILABLE,
        )
        self._jobs[job.id] = job
        return job

    async def create_job_async(
        self,
        config: TrainingConfig,
        adapter_name: str = "",
        *,
        tenant_id: str = "",
        requesting_admin_user_id: str = "",
    ) -> TrainingJob:
        adapter_name = adapter_name or f"clinical-lora-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
        async with async_session_factory() as session:
            record = JobRun(
                job_type=JOB_TYPE,
                entity_type=ENTITY_TYPE,
                entity_id=config.dataset_id,
                status=FineTuneMode.AVAILABLE.value,
                max_retries=1,
                created_by_user_id=requesting_admin_user_id or None,
                payload={
                    "config": asdict(config),
                    "adapter_name": adapter_name,
                    "base_model": config.base_model,
                    "dataset_id": config.dataset_id,
                },
                result={
                    "evaluation_metrics": {},
                    "deployability_status": "not_evaluated",
                    "output_artifact_path": None,
                },
                metadata_={
                    "tenant_id": tenant_id,
                    "requesting_admin_user_id": requesting_admin_user_id,
                    "logs": [{"event": "job_created", "timestamp": datetime.now(timezone.utc).isoformat()}],
                },
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return self._job_from_record(record)

    def get_job(self, job_id: str) -> TrainingJob | None:
        return self._jobs.get(job_id)

    async def get_job_async(self, job_id: str, *, tenant_id: str | None = None) -> TrainingJob | None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(JobRun).where(JobRun.id == uuid.UUID(str(job_id)), JobRun.job_type == JOB_TYPE)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            if tenant_id is not None and (record.metadata_ or {}).get("tenant_id") != tenant_id:
                return None
            return self._job_from_record(record)

    def list_jobs(self) -> list[dict]:
        return [self._job_dict(job) for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)]

    async def list_jobs_async(self, *, tenant_id: str | None = None) -> list[dict]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(JobRun).where(JobRun.job_type == JOB_TYPE).order_by(desc(JobRun.queued_at))
            )
            records = result.scalars().all()
        jobs = []
        for record in records:
            if tenant_id is not None and (record.metadata_ or {}).get("tenant_id") != tenant_id:
                continue
            jobs.append(self._job_dict(self._job_from_record(record)))
        return jobs

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in {FineTuneMode.AVAILABLE, FineTuneMode.RUNNING}:
            return False
        job.status = FineTuneMode.CANCELLED
        job.completed_at = datetime.now(timezone.utc).isoformat()
        return True

    async def cancel_job_async(self, job_id: str, *, tenant_id: str | None = None) -> bool:
        async with async_session_factory() as session:
            result = await session.execute(
                select(JobRun).where(JobRun.id == uuid.UUID(str(job_id)), JobRun.job_type == JOB_TYPE)
            )
            record = result.scalar_one_or_none()
            if record is None or record.status not in {FineTuneMode.AVAILABLE.value, FineTuneMode.RUNNING.value}:
                return False
            if tenant_id is not None and (record.metadata_ or {}).get("tenant_id") != tenant_id:
                return False
            record.status = FineTuneMode.CANCELLED.value
            record.cancel_requested_at = datetime.now(timezone.utc)
            record.completed_at = record.cancel_requested_at
            metadata = dict(record.metadata_ or {})
            metadata.setdefault("logs", []).append(
                {"event": "cancel_requested", "timestamp": record.cancel_requested_at.isoformat()}
            )
            record.metadata_ = metadata
            await session.commit()
            return True

    async def mark_dispatched_async(self, job_id: str, *, worker_task_id: str, transport: str) -> None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(JobRun).where(JobRun.id == uuid.UUID(str(job_id)), JobRun.job_type == JOB_TYPE)
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError(f"Job {job_id} not found")
            record.worker_task_id = worker_task_id
            record.dispatched_at = datetime.now(timezone.utc)
            metadata = dict(record.metadata_ or {})
            metadata["dispatch_transport"] = transport
            metadata.setdefault("logs", []).append(
                {"event": "job_dispatched", "transport": transport, "timestamp": record.dispatched_at.isoformat()}
            )
            record.metadata_ = metadata
            await session.commit()

    async def run_training_job_async(self, job_id: str) -> TrainingJob:
        async with async_session_factory() as session:
            result = await session.execute(
                select(JobRun).where(JobRun.id == uuid.UUID(str(job_id)), JobRun.job_type == JOB_TYPE)
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError(f"Job {job_id} not found")
            if record.cancel_requested_at is not None:
                record.status = FineTuneMode.CANCELLED.value
                record.completed_at = datetime.now(timezone.utc)
                await session.commit()
                return self._job_from_record(record)
            record.status = FineTuneMode.RUNNING.value
            record.started_at = datetime.now(timezone.utc)
            await session.commit()

        try:
            mode = self.runtime_mode()
            if mode != FineTuneMode.AVAILABLE:
                await self._finish_unavailable(job_id, mode)
                job = await self.get_job_async(job_id)
                if job is None:
                    raise ValueError(f"Job {job_id} not found after unavailable update")
                return job

            job = await self.get_job_async(job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            dataset = await self._dataset_backend.get_dataset_async(job.config.dataset_id)
            if dataset is None:
                raise ValueError("Dataset not found")
            validation = self.validate_dataset(dataset)
            if not validation["valid"]:
                raise ValueError(f"Dataset validation failed: {validation['issues']}")
            split = self.split_dataset(dataset, seed=job.config.random_seed)
            artifact_path = get_settings().adapters_dir / job.id / job.adapter_name
            metadata = self._training_backend.train(
                config=job.config,
                train_samples=split.train,
                validation_samples=split.validation,
                output_dir=artifact_path,
                dataset_fingerprint=split.fingerprint,
            )
            if not self._training_backend.verify_adapter(artifact_path, base_model=job.config.base_model):
                raise RuntimeError("Adapter reload verification failed")
            await self._finish_completed(job_id, artifact_path=artifact_path, metadata=metadata)
            completed = await self.get_job_async(job_id)
            if completed is None:
                raise ValueError(f"Job {job_id} not found after completion")
            return completed
        except Exception as exc:
            await self._finish_failed(job_id, str(exc))
            failed = await self.get_job_async(job_id)
            if failed is None:
                raise
            return failed

    def run_training_job_sync(self, job_id: str) -> dict:
        import asyncio

        job = asyncio.run(self.run_training_job_async(job_id))
        return self._job_dict(job)

    async def _finish_unavailable(self, job_id: str, mode: FineTuneMode) -> None:
        async with async_session_factory() as session:
            record = await session.get(JobRun, uuid.UUID(str(job_id)))
            if record is None:
                return
            record.status = mode.value
            record.error_message = f"Fine-tuning unavailable: {mode.value}"
            record.completed_at = datetime.now(timezone.utc)
            result = dict(record.result or {})
            result["deployability_status"] = "not_deployable"
            record.result = result
            await session.commit()

    async def _finish_failed(self, job_id: str, reason: str) -> None:
        async with async_session_factory() as session:
            record = await session.get(JobRun, uuid.UUID(str(job_id)))
            if record is None:
                return
            record.status = FineTuneMode.FAILED.value
            record.error_message = reason
            record.completed_at = datetime.now(timezone.utc)
            result = dict(record.result or {})
            result["deployability_status"] = "not_deployable"
            record.result = result
            await session.commit()

    async def _finish_completed(self, job_id: str, *, artifact_path: Path, metadata: dict) -> None:
        async with async_session_factory() as session:
            record = await session.get(JobRun, uuid.UUID(str(job_id)))
            if record is None:
                return
            record.status = FineTuneMode.COMPLETED.value
            record.completed_at = datetime.now(timezone.utc)
            result = dict(record.result or {})
            result.update(
                {
                    "output_artifact_path": str(artifact_path),
                    "training_metrics": metadata.get("training_metrics", {}),
                    "validation_metrics": metadata.get("validation_metrics", {}),
                    "dataset_fingerprint": metadata.get("dataset_fingerprint"),
                    "environment": metadata.get("environment", {}),
                    "deployability_status": "requires_evaluation",
                }
            )
            record.result = result
            await session.commit()

    async def evaluate_job_async(self, job_id: str, *, metrics: dict, tenant_id: str | None = None) -> TrainingJob:
        async with async_session_factory() as session:
            result = await session.execute(
                select(JobRun).where(JobRun.id == uuid.UUID(str(job_id)), JobRun.job_type == JOB_TYPE)
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError("Job not found")
            if tenant_id is not None and (record.metadata_ or {}).get("tenant_id") != tenant_id:
                raise PermissionError("Cross-tenant fine-tune job access blocked")
            if record.status != FineTuneMode.COMPLETED.value:
                raise ValueError("Only completed adapters can be evaluated")
            min_validation_loss = getattr(get_settings(), "fine_tune_max_validation_loss", 2.0)
            passed = bool(metrics.get("safety_regression_passed")) and float(metrics.get("validation_loss", 9999.0)) <= min_validation_loss
            record.status = FineTuneMode.EVALUATED.value if passed else FineTuneMode.EVALUATED_NOT_DEPLOYABLE.value
            result_payload = dict(record.result or {})
            result_payload["evaluation_metrics"] = {
                **metrics,
                "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
            }
            result_payload["deployability_status"] = "deployable" if passed else "not_deployable"
            record.result = result_payload
            await session.commit()
            return self._job_from_record(record)

    async def deploy_job_async(self, job_id: str, *, tenant_id: str, inference_loader=None) -> TrainingJob:
        async with async_session_factory() as session:
            record = await session.get(JobRun, uuid.UUID(str(job_id)))
            if record is None or record.job_type != JOB_TYPE:
                raise ValueError("Job not found")
            if (record.metadata_ or {}).get("tenant_id") != tenant_id:
                raise PermissionError("Cross-tenant fine-tune job access blocked")
            result_payload = dict(record.result or {})
            if result_payload.get("deployability_status") != "deployable":
                raise ValueError("Adapter is not deployable")
            artifact_path = result_payload.get("output_artifact_path")
            if not artifact_path:
                raise ValueError("Adapter artifact missing")
            if inference_loader is None or not inference_loader(artifact_path):
                raise RuntimeError("Inference adapter integration is not verified")
            previous_result = await session.execute(
                select(JobRun).where(
                    JobRun.job_type == JOB_TYPE,
                    JobRun.status == FineTuneMode.DEPLOYED.value,
                )
            )
            for previous in previous_result.scalars():
                if (previous.metadata_ or {}).get("tenant_id") == tenant_id:
                    previous.status = FineTuneMode.DEPLOYABLE.value
            record.status = FineTuneMode.DEPLOYED.value
            result_payload["deployability_status"] = "deployed"
            result_payload["deployed_at"] = datetime.now(timezone.utc).isoformat()
            record.result = result_payload
            await session.commit()
            return self._job_from_record(record)

    async def rollback_deployment_async(self, *, tenant_id: str) -> TrainingJob | None:
        async with async_session_factory() as session:
            active_result = await session.execute(
                select(JobRun).where(JobRun.job_type == JOB_TYPE, JobRun.status == FineTuneMode.DEPLOYED.value)
            )
            active = None
            for record in active_result.scalars():
                if (record.metadata_ or {}).get("tenant_id") == tenant_id:
                    active = record
                    break
            if active is None:
                return None
            active.status = FineTuneMode.DEPLOYABLE.value
            result_payload = dict(active.result or {})
            result_payload["deployability_status"] = "deployable"
            result_payload["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
            active.result = result_payload
            await session.commit()
            return self._job_from_record(active)

    async def start_training_async(self, job_id: str, num_samples: int = 100) -> TrainingJob:
        """Backward-compatible entry point. This performs real worker-side execution only."""
        return await self.run_training_job_async(job_id)

    async def start_training(self, job_id: str, num_samples: int = 100) -> TrainingJob:
        return await self.run_training_job_async(job_id)

    def get_job_metrics(self, job_id: str) -> list[dict]:
        return []

    async def get_job_metrics_async(self, job_id: str) -> list[dict]:
        job = await self.get_job_async(job_id)
        return [job.evaluation_metrics] if job and job.evaluation_metrics else []


fine_tune_service = FineTuneService(use_database=True)

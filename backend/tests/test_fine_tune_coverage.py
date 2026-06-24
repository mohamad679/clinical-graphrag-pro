from pathlib import Path
from uuid import uuid4

import pytest

from app.services.datasets import Dataset, TrainingSample
from app.services.fine_tune import FineTuneMode, FineTuneService, TrainingConfig, TrainingJob
from app.core.database import async_session_factory
from app.models.persistence import FineTuneDataset, FineTuneDatasetSample


@pytest.fixture
def phase1_env():
    return None


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeTrainingBackend:
    def __init__(self, *, verify: bool = True):
        self.train_called = False
        self.verify_called = False
        self.verify = verify

    def train(self, *, config, train_samples, validation_samples, output_dir, dataset_fingerprint):
        self.train_called = True
        assert train_samples
        assert validation_samples
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "adapter_model.safetensors").write_text("test adapter", encoding="utf-8")
        (output_dir / "adapter_metadata.json").write_text("{}", encoding="utf-8")
        return {
            "dataset_fingerprint": dataset_fingerprint,
            "training_metrics": {"train_runtime": 1.0, "training_loss": 0.5},
            "validation_metrics": {"validation_loss": 0.8},
            "environment": {"test": True},
        }

    def verify_adapter(self, artifact_path: Path, *, base_model: str) -> bool:
        self.verify_called = True
        return self.verify and (artifact_path / "adapter_model.safetensors").exists()


def _valid_dataset(sample_count: int = 5) -> Dataset:
    dataset = Dataset(id="ds-valid", name="Valid")
    for index in range(sample_count):
        dataset.samples.append(
            TrainingSample(
                id=f"sample-{index}",
                instruction=f"Question {index}",
                input="Clinical context",
                output=f"Grounded answer {index}",
            )
        )
    return dataset


async def _persist_dataset(dataset: Dataset) -> str:
    dataset_id = f"{dataset.id}-{uuid4()}"
    async with async_session_factory() as session:
        session.add(FineTuneDataset(id=dataset_id, name=dataset.name, description=dataset.description, template=dataset.template))
        for sample in dataset.samples:
            session.add(
                FineTuneDatasetSample(
                    id=f"{sample.id}-{uuid4()}",
                    dataset_id=dataset_id,
                    instruction=sample.instruction,
                    input_text=sample.input,
                    output_text=sample.output,
                    source_doc=sample.source_doc,
                )
            )
        await session.commit()
    return dataset_id


def test_training_config_defaults():
    cfg = TrainingConfig()
    assert cfg.lora_rank == 16
    assert cfg.lora_alpha == 32
    assert cfg.learning_rate == 2e-4
    assert cfg.num_epochs == 3
    assert cfg.batch_size == 4
    assert cfg.max_seq_length == 2048
    assert cfg.warmup_steps == 10
    assert cfg.weight_decay == 0.01
    assert cfg.gradient_accumulation_steps == 4
    assert cfg.gradient_clipping == 1.0


def test_duration_seconds():
    job = TrainingJob()
    assert job.duration_seconds is None
    job.started_at = "2026-05-24T21:00:00.000000+00:00"
    job.completed_at = "2026-05-24T21:00:10.000000+00:00"
    assert job.duration_seconds == 10.0


def test_dataset_validation_rejects_malformed_records(phase1_env):
    malformed = Dataset(id="bad")
    malformed.samples.append(TrainingSample(instruction="", input="", output=""))
    result = FineTuneService.validate_dataset(malformed)
    assert result["valid"] is False
    assert any("instruction" in issue for issue in result["issues"])
    assert any("output" in issue for issue in result["issues"])


def test_train_validation_split_is_deterministic(phase1_env):
    dataset = _valid_dataset(6)
    first = FineTuneService.split_dataset(dataset, seed=123)
    second = FineTuneService.split_dataset(dataset, seed=123)
    assert [sample.id for sample in first.train] == [sample.id for sample in second.train]
    assert [sample.id for sample in first.validation] == [sample.id for sample in second.validation]
    assert first.fingerprint == second.fingerprint


def test_transitional_worker_statuses_are_readable(phase1_env):
    assert FineTuneService._normalize_job_status("dispatched") == FineTuneMode.AVAILABLE
    assert FineTuneService._normalize_job_status("running") == FineTuneMode.RUNNING


@pytest.mark.anyio
async def test_missing_gpu_returns_unavailable_status(monkeypatch, phase1_env):
    dataset_id = await _persist_dataset(_valid_dataset())
    service = FineTuneService(
        use_database=True,
        dependency_checker=lambda _dep: True,
        gpu_checker=lambda: False,
    )
    monkeypatch.setattr("app.services.fine_tune.get_settings", lambda: type("S", (), {
        "enable_fine_tune": True,
        "fine_tune_base_model": "base",
        "adapters_dir": Path("/tmp/fine-tune-test"),
        "fine_tune_max_validation_loss": 2.0,
    })())
    job = await service.create_job_async(TrainingConfig(dataset_id=dataset_id), tenant_id="tenant-a", requesting_admin_user_id="admin-a")
    result = await service.run_training_job_async(job.id)
    assert result.status == FineTuneMode.UNAVAILABLE_MISSING_GPU
    assert result.final_loss is None


@pytest.mark.anyio
async def test_missing_dependency_returns_unavailable_status(monkeypatch, phase1_env):
    dataset_id = await _persist_dataset(_valid_dataset())
    service = FineTuneService(
        use_database=True,
        dependency_checker=lambda dep: dep != "peft",
        gpu_checker=lambda: True,
    )
    monkeypatch.setattr("app.services.fine_tune.get_settings", lambda: type("S", (), {
        "enable_fine_tune": True,
        "fine_tune_base_model": "base",
        "adapters_dir": Path("/tmp/fine-tune-test"),
        "fine_tune_max_validation_loss": 2.0,
    })())
    job = await service.create_job_async(TrainingConfig(dataset_id=dataset_id), tenant_id="tenant-a", requesting_admin_user_id="admin-a")
    result = await service.run_training_job_async(job.id)
    assert result.status == FineTuneMode.UNAVAILABLE_MISSING_DEPENDENCY
    assert await service.get_job_metrics_async(job.id) == []


@pytest.mark.anyio
async def test_trainer_train_invoked_and_reload_verified_before_completion(monkeypatch, tmp_path, phase1_env):
    dataset_id = await _persist_dataset(_valid_dataset())
    backend = FakeTrainingBackend(verify=True)
    service = FineTuneService(
        use_database=True,
        training_backend=backend,
        dependency_checker=lambda _dep: True,
        gpu_checker=lambda: True,
    )
    monkeypatch.setattr("app.services.fine_tune.get_settings", lambda: type("S", (), {
        "enable_fine_tune": True,
        "fine_tune_base_model": "base",
        "adapters_dir": tmp_path,
        "fine_tune_max_validation_loss": 2.0,
    })())

    job = await service.create_job_async(TrainingConfig(dataset_id=dataset_id), adapter_name="adapter", tenant_id="tenant-a", requesting_admin_user_id="admin-a")
    result = await service.run_training_job_async(job.id)

    assert backend.train_called is True
    assert backend.verify_called is True
    assert result.status == FineTuneMode.COMPLETED
    assert result.output_artifact_path


@pytest.mark.anyio
async def test_failed_adapter_reload_marks_job_failed(monkeypatch, tmp_path, phase1_env):
    dataset_id = await _persist_dataset(_valid_dataset())
    backend = FakeTrainingBackend(verify=False)
    service = FineTuneService(
        use_database=True,
        training_backend=backend,
        dependency_checker=lambda _dep: True,
        gpu_checker=lambda: True,
    )
    monkeypatch.setattr("app.services.fine_tune.get_settings", lambda: type("S", (), {
        "enable_fine_tune": True,
        "fine_tune_base_model": "base",
        "adapters_dir": tmp_path,
        "fine_tune_max_validation_loss": 2.0,
    })())

    job = await service.create_job_async(TrainingConfig(dataset_id=dataset_id), adapter_name="adapter", tenant_id="tenant-a", requesting_admin_user_id="admin-a")
    result = await service.run_training_job_async(job.id)

    assert result.status == FineTuneMode.FAILED
    assert "reload verification" in (result.failure_reason or "")


@pytest.mark.anyio
async def test_evaluation_gate_blocks_weak_adapters(monkeypatch, tmp_path, phase1_env):
    dataset_id = await _persist_dataset(_valid_dataset())
    service = FineTuneService(use_database=True, training_backend=FakeTrainingBackend(), dependency_checker=lambda _dep: True, gpu_checker=lambda: True)
    monkeypatch.setattr("app.services.fine_tune.get_settings", lambda: type("S", (), {
        "enable_fine_tune": True,
        "fine_tune_base_model": "base",
        "adapters_dir": tmp_path,
        "fine_tune_max_validation_loss": 1.0,
    })())
    job = await service.create_job_async(TrainingConfig(dataset_id=dataset_id), adapter_name="adapter", tenant_id="tenant-a", requesting_admin_user_id="admin-a")
    completed = await service.run_training_job_async(job.id)

    evaluated = await service.evaluate_job_async(
        completed.id,
        metrics={"validation_loss": 3.0, "safety_regression_passed": True},
        tenant_id="tenant-a",
    )

    assert evaluated.status == FineTuneMode.EVALUATED_NOT_DEPLOYABLE
    assert evaluated.deployability_status == "not_deployable"


@pytest.mark.anyio
async def test_deployed_state_requires_inference_integration_and_rollback(monkeypatch, tmp_path, phase1_env):
    dataset_id = await _persist_dataset(_valid_dataset())
    service = FineTuneService(use_database=True, training_backend=FakeTrainingBackend(), dependency_checker=lambda _dep: True, gpu_checker=lambda: True)
    monkeypatch.setattr("app.services.fine_tune.get_settings", lambda: type("S", (), {
        "enable_fine_tune": True,
        "fine_tune_base_model": "base",
        "adapters_dir": tmp_path,
        "fine_tune_max_validation_loss": 2.0,
    })())
    job = await service.create_job_async(TrainingConfig(dataset_id=dataset_id), adapter_name="adapter", tenant_id="tenant-a", requesting_admin_user_id="admin-a")
    completed = await service.run_training_job_async(job.id)
    deployable = await service.evaluate_job_async(
        completed.id,
        metrics={"validation_loss": 0.5, "safety_regression_passed": True},
        tenant_id="tenant-a",
    )

    with pytest.raises(RuntimeError):
        await service.deploy_job_async(deployable.id, tenant_id="tenant-a")

    deployed = await service.deploy_job_async(deployable.id, tenant_id="tenant-a", inference_loader=lambda _path: True)
    assert deployed.status == FineTuneMode.DEPLOYED

    rolled_back = await service.rollback_deployment_async(tenant_id="tenant-a")
    assert rolled_back is not None
    assert rolled_back.status == FineTuneMode.DEPLOYABLE


@pytest.mark.anyio
async def test_cross_tenant_access_is_blocked(phase1_env):
    service = FineTuneService(use_database=True)
    job = await service.create_job_async(TrainingConfig(dataset_id="ds"), tenant_id="tenant-a", requesting_admin_user_id="admin-a")
    assert await service.get_job_async(job.id, tenant_id="tenant-b") is None
    assert await service.cancel_job_async(job.id, tenant_id="tenant-b") is False


@pytest.mark.anyio
async def test_worker_dispatch_uses_durable_fine_tune_task(monkeypatch, phase1_env):
    from app import worker

    captured = {}

    async def fake_dispatch(task, **kwargs):
        captured["task"] = task
        captured.update(kwargs)
        return {"id": "worker-job", "transport": "celery"}

    monkeypatch.setattr(worker, "_dispatch_task", fake_dispatch)
    result = await worker.dispatch_fine_tune_training("job-123")

    assert result["transport"] == "celery"
    assert captured["default_job_type"] == "fine_tune_training"
    assert captured["runner_args"] == ("job-123",)
    assert captured["task_args"] == ("job-123",)

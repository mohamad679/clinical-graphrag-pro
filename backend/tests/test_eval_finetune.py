"""
Tests for Evaluation & Fine-Tuning services (Phases 4-5).
Eval metrics, dataset CRUD, training jobs, model registry.
"""

import pytest
from app.services.evaluation import EvaluationService
from app.services.datasets import DatasetService
from app.services.fine_tune import FineTuneService, TrainingConfig
from app.services.model_registry import ModelRegistry


# ── Evaluation Service ──────────────────────────────────

class TestEvaluationService:
    """Test evaluation metric calculations."""

    def setup_method(self):
        self.eval_svc = EvaluationService()

    @pytest.mark.asyncio
    async def test_evaluate_returns_scores(self):
        result = await self.eval_svc.evaluate(
            query="What is diabetes?",
            answer="Diabetes is a metabolic disease.",
            context_chunks=[{"chunk_text": "Diabetes mellitus is a chronic metabolic disease.", "document_name": "test.pdf"}],
        )
        assert result.faithfulness >= 0.0
        assert result.relevance >= 0.0

    @pytest.mark.asyncio
    async def test_evaluate_scores_in_range(self):
        result = await self.eval_svc.evaluate(
            query="What is hypertension?",
            answer="Hypertension is high blood pressure.",
            context_chunks=[{"chunk_text": "Hypertension, also known as high blood pressure.", "document_name": "test.pdf"}],
        )
        for attr in ["faithfulness", "relevance", "citation_accuracy", "context_precision"]:
            score = getattr(result, attr)
            assert 0.0 <= score <= 1.0, f"{attr} score out of range: {score}"

    @pytest.mark.asyncio
    async def test_evaluate_empty_contexts(self):
        result = await self.eval_svc.evaluate(
            query="test",
            answer="test answer",
            context_chunks=[],
        )
        assert result.overall_score >= 0.0

    def test_service_instantiates(self):
        svc = EvaluationService()
        assert svc is not None


# ── Dataset Service ─────────────────────────────────────

class TestDatasetService:
    """Test dataset CRUD operations."""

    def setup_method(self):
        self.ds = DatasetService()

    def test_create_dataset(self):
        dataset = self.ds.create_dataset("Test Dataset", "For testing", "alpaca")
        assert dataset.name == "Test Dataset"
        assert dataset.id is not None
        fetched = self.ds.get_dataset(dataset.id)
        assert fetched is not None
        assert fetched.name == "Test Dataset"

    def test_list_datasets(self):
        self.ds.create_dataset("List Test", "desc", "alpaca")
        datasets = self.ds.list_datasets()
        assert len(datasets) >= 1

    def test_get_nonexistent(self):
        dataset = self.ds.get_dataset("fake-id")
        assert dataset is None

    def test_delete_dataset(self):
        dataset = self.ds.create_dataset("Delete Me", "del", "alpaca")
        assert self.ds.delete_dataset(dataset.id) is True
        assert self.ds.get_dataset(dataset.id) is None

    def test_delete_nonexistent(self):
        assert self.ds.delete_dataset("no-such-id") is False

    def test_export_jsonl(self):
        dataset = self.ds.create_dataset("Export Test", "export", "alpaca")
        content = self.ds.export_jsonl(dataset.id)
        assert content is not None

    def test_validate_dataset(self):
        dataset = self.ds.create_dataset("Validate Test", "validate", "alpaca")
        result = self.ds.validate(dataset.id)
        assert "valid" in result
        assert "issues" in result


# ── Fine-Tune Service ───────────────────────────────────

class TestFineTuneService:
    """Test training job lifecycle."""

    def setup_method(self):
        self.ft = FineTuneService()

    def test_create_job(self):
        config = TrainingConfig(dataset_id="test-ds")
        job = self.ft.create_job(config, adapter_name="test-adapter")
        assert job.status.value == "pending"
        assert job.adapter_name == "test-adapter"

    def test_list_jobs(self):
        config = TrainingConfig(dataset_id="list-test")
        self.ft.create_job(config, adapter_name="list-test")
        jobs = self.ft.list_jobs()
        assert len(jobs) >= 1

    def test_get_job(self):
        config = TrainingConfig(dataset_id="get-test")
        job = self.ft.create_job(config, adapter_name="get-test")
        fetched = self.ft.get_job(job.id)
        assert fetched is not None
        assert fetched.id == job.id

    def test_get_nonexistent_job(self):
        assert self.ft.get_job("no-such-job") is None

    @pytest.mark.asyncio
    async def test_simulated_training(self):
        config = TrainingConfig(dataset_id="sim-test", num_epochs=1)
        job = self.ft.create_job(config, adapter_name="sim-adapter")
        completed = await self.ft.start_training(job.id, num_samples=10)
        assert completed.status.value == "completed"
        assert len(completed.metrics_history) > 0
        assert completed.metrics_history[-1].loss < completed.metrics_history[0].loss

    def test_cancel_pending_job_returns_false(self):
        """cancel_job only cancels RUNNING jobs; pending returns False."""
        config = TrainingConfig(dataset_id="cancel-test")
        job = self.ft.create_job(config, adapter_name="cancel-adapter")
        # Can't cancel a pending job (only running ones)
        result = self.ft.cancel_job(job.id)
        assert result is False


# ── Model Registry ──────────────────────────────────────

class TestModelRegistry:
    """Test adapter registry operations."""

    def setup_method(self):
        self.reg = ModelRegistry()

    def test_register_model(self):
        model = self.reg.register(
            name="test-model",
            base_model="llama-3.1-8b",
            dataset_name="ds-001",
            training_loss=0.5,
            adapter_path="/tmp/adapters/test",
        )
        assert model.id is not None
        assert model.name == "test-model"

    def test_list_models(self):
        self.reg.register(
            name="list-model",
            base_model="llama-3.1-8b",
            dataset_name="ds-002",
        )
        models = self.reg.list_models()
        assert len(models) >= 1

    def test_deploy_undeploy(self):
        model = self.reg.register(
            name="deploy-model",
            base_model="llama",
            dataset_name="ds-003",
        )
        assert self.reg.deploy(model.id) is True
        active = self.reg.get_active_model()
        assert active is not None
        assert self.reg.undeploy(model.id) is True

    def test_compare_models(self):
        m1 = self.reg.register(name="m1", base_model="b", dataset_name="d", training_loss=0.5)
        m2 = self.reg.register(name="m2", base_model="b", dataset_name="d", training_loss=0.3)
        comparison = self.reg.compare_models([m1.id, m2.id])
        assert len(comparison) == 2

    def test_delete_model(self):
        model = self.reg.register(name="delete-me", base_model="b", dataset_name="d")
        assert self.reg.delete_model(model.id) is True

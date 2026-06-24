"""
Fine-Tuning API endpoints.
Dataset management, training jobs, and model registry.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import User, require_admin
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def require_fine_tune_enabled():
    settings = get_settings()
    if not settings.enable_fine_tune:
        raise HTTPException(
            status_code=503,
            detail="Fine-tuning is disabled in this deployment",
        )


router = APIRouter(
    prefix="/fine-tune",
    tags=["Fine-Tuning"],
    dependencies=[Depends(require_admin), Depends(require_fine_tune_enabled)],
)


def _get_dataset_dependencies():
    from app.services.datasets import TrainingSample, dataset_service

    return dataset_service, TrainingSample


def _get_fine_tune_dependencies():
    from app.services.fine_tune import TrainingConfig, fine_tune_service

    return fine_tune_service, TrainingConfig


def _get_model_registry():
    from app.services.model_registry import model_registry

    return model_registry


def _tenant_id(user: User) -> str:
    return user.tenant_id or user.id


# ── Schemas ──────────────────────────────────────────────

class CreateDatasetRequest(BaseModel):
    name: str
    description: str = ""
    template: str = "alpaca"


class AddSampleRequest(BaseModel):
    instruction: str
    input: str = ""
    output: str
    source_doc: str = ""


class GenerateRequest(BaseModel):
    num_pairs: int = 20


class StartTrainingRequest(BaseModel):
    dataset_id: str
    adapter_name: str = ""
    base_model: str = ""
    lora_rank: int = 16
    lora_alpha: int = 32
    learning_rate: float = 2e-4
    num_epochs: int = 3
    batch_size: int = 4
    max_seq_length: int = 2048


class RegisterModelRequest(BaseModel):
    name: str
    base_model: str
    dataset_name: str = ""
    lora_rank: int = 16
    lora_alpha: int = 32
    training_loss: float | None = None
    eval_scores: dict = {}
    notes: str = ""


# ── Dataset Endpoints ────────────────────────────────────

@router.post("/datasets")
async def create_dataset(request: CreateDatasetRequest):
    dataset_service, _ = _get_dataset_dependencies()
    ds = await dataset_service.create_dataset_async(
        name=request.name,
        description=request.description,
        template=request.template,
    )
    return {"id": ds.id, "name": ds.name, "created_at": ds.created_at}


@router.get("/datasets")
async def list_datasets():
    dataset_service, _ = _get_dataset_dependencies()
    return {"datasets": await dataset_service.list_datasets_async()}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    dataset_service, _ = _get_dataset_dependencies()
    ds = await dataset_service.get_dataset_async(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {
        "id": ds.id,
        "name": ds.name,
        "description": ds.description,
        "template": ds.template,
        "sample_count": ds.sample_count,
        "created_at": ds.created_at,
        "samples": [
            {
                "id": s.id,
                "instruction": s.instruction,
                "input": s.input[:200],
                "output": s.output[:200],
                "source_doc": s.source_doc,
            }
            for s in ds.samples[:50]
        ],
    }


@router.post("/datasets/{dataset_id}/samples")
async def add_sample(dataset_id: str, request: AddSampleRequest):
    dataset_service, TrainingSample = _get_dataset_dependencies()
    sample = TrainingSample(
        instruction=request.instruction,
        input=request.input,
        output=request.output,
        source_doc=request.source_doc,
    )
    if not await dataset_service.add_sample_async(dataset_id, sample):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"id": sample.id, "added": True}


@router.post("/datasets/{dataset_id}/generate")
async def generate_samples(dataset_id: str, request: GenerateRequest):
    dataset_service, _ = _get_dataset_dependencies()
    try:
        count = await dataset_service.generate_from_documents_async(
            dataset_id=dataset_id,
            num_pairs=request.num_pairs,
        )
        return {"generated": count}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets/{dataset_id}/validate")
async def validate_dataset(dataset_id: str):
    dataset_service, _ = _get_dataset_dependencies()
    return await dataset_service.validate_async(dataset_id)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    dataset_service, _ = _get_dataset_dependencies()
    if not await dataset_service.delete_dataset_async(dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"deleted": True}


# ── Training Job Endpoints ───────────────────────────────

@router.post("/train")
@router.post("/start")
async def start_training(request: StartTrainingRequest, current_admin: User = Depends(require_admin)):
    dataset_service, _ = _get_dataset_dependencies()
    fine_tune_service, TrainingConfig = _get_fine_tune_dependencies()
    ds = await dataset_service.get_dataset_async(request.dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    validation = fine_tune_service.validate_dataset(ds)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail={"message": "Dataset validation failed", "issues": validation["issues"]})

    config = TrainingConfig(
        base_model=request.base_model or "",
        dataset_id=request.dataset_id,
        lora_rank=request.lora_rank,
        lora_alpha=request.lora_alpha,
        learning_rate=request.learning_rate,
        num_epochs=request.num_epochs,
        batch_size=request.batch_size,
        max_seq_length=request.max_seq_length,
    )

    job = await fine_tune_service.create_job_async(
        config,
        adapter_name=request.adapter_name,
        tenant_id=_tenant_id(current_admin),
        requesting_admin_user_id=current_admin.id,
    )

    from app.worker import dispatch_fine_tune_training

    dispatch = await dispatch_fine_tune_training(job.id)
    await fine_tune_service.mark_dispatched_async(
        job.id,
        worker_task_id=str(dispatch.get("id", "")),
        transport=str(dispatch.get("transport", "")),
    )

    return {
        "job_id": job.id,
        "adapter_name": job.adapter_name,
        "status": job.status.value,
        "dispatch": {"id": dispatch.get("id"), "transport": dispatch.get("transport")},
        "demo_simulation_only": False,
    }


@router.get("/jobs")
async def list_jobs(current_admin: User = Depends(require_admin)):
    fine_tune_service, _ = _get_fine_tune_dependencies()
    return {"jobs": await fine_tune_service.list_jobs_async(tenant_id=_tenant_id(current_admin))}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, current_admin: User = Depends(require_admin)):
    fine_tune_service, _ = _get_fine_tune_dependencies()
    job = await fine_tune_service.get_job_async(job_id, tenant_id=_tenant_id(current_admin))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "adapter_name": job.adapter_name,
        "status": job.status.value,
        "config": {
            "base_model": job.config.base_model,
            "lora_rank": job.config.lora_rank,
            "lora_alpha": job.config.lora_alpha,
            "learning_rate": job.config.learning_rate,
            "num_epochs": job.config.num_epochs,
            "batch_size": job.config.batch_size,
        },
        "final_loss": job.final_loss,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "duration": job.duration_seconds,
        "failure_reason": job.failure_reason,
        "output_artifact_path": job.output_artifact_path,
        "deployability_status": job.deployability_status,
        "metrics": await fine_tune_service.get_job_metrics_async(job_id),
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, current_admin: User = Depends(require_admin)):
    fine_tune_service, _ = _get_fine_tune_dependencies()
    if not await fine_tune_service.cancel_job_async(job_id, tenant_id=_tenant_id(current_admin)):
        raise HTTPException(status_code=400, detail="Cannot cancel this job")
    return {"cancelled": True}


@router.post("/jobs/{job_id}/evaluate")
async def evaluate_job(job_id: str, metrics: dict, current_admin: User = Depends(require_admin)):
    fine_tune_service, _ = _get_fine_tune_dependencies()
    try:
        job = await fine_tune_service.evaluate_job_async(job_id, metrics=metrics, tenant_id=_tenant_id(current_admin))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "job_id": job.id,
        "status": job.status.value,
        "deployability_status": job.deployability_status,
        "evaluation_metrics": job.evaluation_metrics,
    }


@router.post("/jobs/{job_id}/deploy")
async def deploy_job(job_id: str, current_admin: User = Depends(require_admin)):
    fine_tune_service, _ = _get_fine_tune_dependencies()
    try:
        job = await fine_tune_service.deploy_job_async(job_id, tenant_id=_tenant_id(current_admin))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job_id": job.id, "status": job.status.value}


@router.post("/rollback")
async def rollback_deployment(current_admin: User = Depends(require_admin)):
    fine_tune_service, _ = _get_fine_tune_dependencies()
    job = await fine_tune_service.rollback_deployment_async(tenant_id=_tenant_id(current_admin))
    if job is None:
        raise HTTPException(status_code=404, detail="No deployed adapter found")
    return {"job_id": job.id, "status": job.status.value}


# ── Model Registry Endpoints ────────────────────────────

@router.get("/models")
async def list_models():
    model_registry = _get_model_registry()
    return {"models": await model_registry.list_models_async()}


@router.post("/models")
async def register_model(request: RegisterModelRequest):
    model_registry = _get_model_registry()
    model = await model_registry.register_async(
        name=request.name,
        base_model=request.base_model,
        dataset_name=request.dataset_name,
        lora_rank=request.lora_rank,
        lora_alpha=request.lora_alpha,
        training_loss=request.training_loss,
        eval_scores=request.eval_scores,
        notes=request.notes,
    )
    return {"id": model.id, "name": model.name, "version": model.version}


@router.post("/models/{model_id}/deploy")
async def deploy_model(model_id: str):
    model_registry = _get_model_registry()
    if not await model_registry.deploy_async(model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"deployed": True}


@router.post("/models/{model_id}/undeploy")
async def undeploy_model(model_id: str):
    model_registry = _get_model_registry()
    if not await model_registry.undeploy_async(model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"undeployed": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    model_registry = _get_model_registry()
    if not await model_registry.delete_model_async(model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"deleted": True}

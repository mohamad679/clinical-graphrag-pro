"""
Fine-Tuning API endpoints.
Dataset management, training jobs, and model registry.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.datasets import dataset_service, TrainingSample
from app.services.fine_tune import fine_tune_service, TrainingConfig
from app.services.model_registry import model_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/fine-tune", tags=["Fine-Tuning"])


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
    ds = dataset_service.create_dataset(
        name=request.name,
        description=request.description,
        template=request.template,
    )
    return {"id": ds.id, "name": ds.name, "created_at": ds.created_at}


@router.get("/datasets")
async def list_datasets():
    return {"datasets": dataset_service.list_datasets()}


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    ds = dataset_service.get_dataset(dataset_id)
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
    sample = TrainingSample(
        instruction=request.instruction,
        input=request.input,
        output=request.output,
        source_doc=request.source_doc,
    )
    if not dataset_service.add_sample(dataset_id, sample):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"id": sample.id, "added": True}


@router.post("/datasets/{dataset_id}/generate")
async def generate_samples(dataset_id: str, request: GenerateRequest):
    try:
        count = await dataset_service.generate_from_documents(
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
    return dataset_service.validate(dataset_id)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str):
    if not dataset_service.delete_dataset(dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"deleted": True}


# ── Training Job Endpoints ───────────────────────────────

@router.post("/train")
async def start_training(request: StartTrainingRequest):
    ds = dataset_service.get_dataset(request.dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

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

    job = fine_tune_service.create_job(config, adapter_name=request.adapter_name)

    # Start training in background
    import asyncio
    asyncio.create_task(
        fine_tune_service.start_training(job.id, num_samples=ds.sample_count or 100)
    )

    return {
        "job_id": job.id,
        "adapter_name": job.adapter_name,
        "status": job.status.value,
    }


@router.get("/jobs")
async def list_jobs():
    return {"jobs": fine_tune_service.list_jobs()}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = fine_tune_service.get_job(job_id)
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
        "error_message": job.error_message,
        "metrics": fine_tune_service.get_job_metrics(job_id),
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    if not fine_tune_service.cancel_job(job_id):
        raise HTTPException(status_code=400, detail="Cannot cancel this job")
    return {"cancelled": True}


# ── Model Registry Endpoints ────────────────────────────

@router.get("/models")
async def list_models():
    return {"models": model_registry.list_models()}


@router.post("/models")
async def register_model(request: RegisterModelRequest):
    model = model_registry.register(
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
    if not model_registry.deploy(model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"deployed": True}


@router.post("/models/{model_id}/undeploy")
async def undeploy_model(model_id: str):
    if not model_registry.undeploy(model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"undeployed": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    if not model_registry.delete_model(model_id):
        raise HTTPException(status_code=404, detail="Model not found")
    return {"deleted": True}

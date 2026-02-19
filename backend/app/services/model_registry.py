"""
Model Registry.
Tracks fine-tuned adapters with metadata, comparison, and deployment.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class AdapterModel:
    """A registered fine-tuned adapter."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    base_model: str = ""
    dataset_name: str = ""
    lora_rank: int = 16
    lora_alpha: int = 32
    training_loss: float | None = None
    eval_scores: dict = field(default_factory=dict)  # metric_name → score
    adapter_path: str = ""
    is_active: bool = False
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""


class ModelRegistry:
    """
    Registry for fine-tuned LoRA adapters.
    Supports registration, comparison, versioning, and deployment.
    """

    def __init__(self):
        self._models: dict[str, AdapterModel] = {}
        self._active_model_id: str | None = None

    # ── Registration ─────────────────────────────────────

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
        """Register a new adapter model."""
        # Auto-increment version for same-name adapters
        existing = [m for m in self._models.values() if m.name == name]
        version = max((m.version for m in existing), default=0) + 1

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
        logger.info(f"Registered adapter '{name}' v{version} ({model.id})")
        return model

    # ── Queries ──────────────────────────────────────────

    def get_model(self, model_id: str) -> AdapterModel | None:
        return self._models.get(model_id)

    def list_models(self) -> list[dict]:
        return [
            {
                "id": m.id,
                "name": m.name,
                "base_model": m.base_model,
                "dataset_name": m.dataset_name,
                "lora_rank": m.lora_rank,
                "training_loss": m.training_loss,
                "eval_scores": m.eval_scores,
                "is_active": m.is_active,
                "version": m.version,
                "created_at": m.created_at,
                "notes": m.notes,
            }
            for m in sorted(
                self._models.values(), key=lambda x: x.created_at, reverse=True
            )
        ]

    def delete_model(self, model_id: str) -> bool:
        if model_id in self._models:
            if self._active_model_id == model_id:
                self._active_model_id = None
            del self._models[model_id]
            return True
        return False

    # ── Comparison ───────────────────────────────────────

    def compare_models(self, model_ids: list[str]) -> list[dict]:
        """Compare selected models side-by-side."""
        results = []
        for mid in model_ids:
            m = self._models.get(mid)
            if m:
                results.append({
                    "id": m.id,
                    "name": f"{m.name} v{m.version}",
                    "base_model": m.base_model,
                    "lora_rank": m.lora_rank,
                    "training_loss": m.training_loss,
                    "eval_scores": m.eval_scores,
                    "is_active": m.is_active,
                })
        return results

    # ── Deployment ───────────────────────────────────────

    def deploy(self, model_id: str) -> bool:
        """Set an adapter as the active model for inference."""
        model = self._models.get(model_id)
        if not model:
            return False

        # Deactivate current
        if self._active_model_id and self._active_model_id in self._models:
            self._models[self._active_model_id].is_active = False

        model.is_active = True
        self._active_model_id = model_id
        logger.info(f"Deployed adapter '{model.name}' v{model.version}")
        return True

    def undeploy(self, model_id: str) -> bool:
        """Remove an adapter from active inference."""
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

    # ── Update Eval Scores ───────────────────────────────

    def update_eval_scores(self, model_id: str, scores: dict) -> bool:
        model = self._models.get(model_id)
        if not model:
            return False
        model.eval_scores.update(scores)
        return True


# Module-level singleton
model_registry = ModelRegistry()

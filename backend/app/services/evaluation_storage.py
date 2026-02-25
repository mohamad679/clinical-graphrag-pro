"""
Service for storing evaluation metrics.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationRun

logger = logging.getLogger(__name__)


class EvaluationStorageService:
    def __init__(self, fallback_path: str = "data/eval_results_fallback.jsonl"):
        self.fallback_path = Path(fallback_path)
        # Ensure fallback directory exists
        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)

    async def save_evaluation(
        self,
        db: AsyncSession,
        evaluation_type: str,
        metrics: Dict[str, Any],
        dataset_size: int,
        metadata: Dict[str, Any] = None,
    ) -> bool:
        """
        Attempt to save evaluation metrics to PostgreSQL.
        If it fails, write to the fallback .jsonl file.
        """
        metadata = metadata or {}
        
        try:
            # Create a new record
            eval_run = EvaluationRun(
                evaluation_type=evaluation_type,
                metrics=metrics,
                dataset_size=dataset_size,
                metadata_=metadata,
            )
            
            db.add(eval_run)
            await db.commit()
            await db.refresh(eval_run)
            logger.info(f"Successfully saved evaluation run {eval_run.id} to DB.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save evaluation to DB. Error: {e}")
            await db.rollback()
            
            # Fallback
            self._save_to_fallback({
                "evaluation_type": evaluation_type,
                "metrics": metrics,
                "dataset_size": dataset_size,
                "metadata": metadata,
            })
            return False

    def _save_to_fallback(self, run_data: Dict[str, Any]):
        """Save a single evaluation result as JSON object on a new line."""
        try:
            with self.fallback_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(run_data) + "\n")
            logger.info(f"Successfully saved evaluation run to fallback {self.fallback_path}")
        except Exception as ex:
            logger.error(f"Failed to save evaluation to fallback file: {ex}")

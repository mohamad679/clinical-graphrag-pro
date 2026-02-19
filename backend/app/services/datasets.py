"""
Dataset Management Service for fine-tuning.
Handles creation, storage, and export of instruction-tuning datasets.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from app.services.vector_store import vector_store_service
from app.services.llm import llm_service

logger = logging.getLogger(__name__)


@dataclass
class TrainingSample:
    """Single instruction-tuning sample."""
    instruction: str
    input: str  # context / supporting info
    output: str
    source_doc: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Dataset:
    """Collection of training samples."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    template: str = "alpaca"  # alpaca | sharegpt
    samples: list[TrainingSample] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    @property
    def sample_count(self) -> int:
        return len(self.samples)


class DatasetService:
    """Manage instruction-tuning datasets."""

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}

    # ── CRUD ─────────────────────────────────────────────

    def create_dataset(self, name: str, description: str = "", template: str = "alpaca") -> Dataset:
        ds = Dataset(name=name, description=description, template=template)
        self._datasets[ds.id] = ds
        logger.info(f"Created dataset '{name}' ({ds.id})")
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

    # ── Auto-Generate from Documents ─────────────────────

    async def generate_from_documents(
        self,
        dataset_id: str,
        num_pairs: int = 20,
    ) -> int:
        """
        Auto-generate training pairs from indexed documents.
        Uses the LLM to create question-answer pairs from chunks.
        """
        ds = self._datasets.get(dataset_id)
        if not ds:
            raise ValueError(f"Dataset {dataset_id} not found")

        # Get chunks from vector store
        all_chunks = vector_store_service.get_all_chunks()
        if not all_chunks:
            logger.warning("No chunks available for generation")
            return 0

        # Sample chunks (spread across documents)
        import random
        sample_size = min(len(all_chunks), num_pairs * 2)
        selected = random.sample(all_chunks, sample_size)

        generated = 0
        for chunk in selected[:num_pairs]:
            chunk_text = chunk.get("chunk_text", chunk.get("text", ""))
            doc_name = chunk.get("document_name", "unknown")

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
                    sample = TrainingSample(
                        instruction=pair["question"],
                        input=chunk_text[:500],
                        output=pair["answer"],
                        source_doc=doc_name,
                    )
                    ds.samples.append(sample)
                    generated += 1

            except Exception as e:
                logger.warning(f"Failed to generate pair: {e}")
                continue

        ds.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"Generated {generated} training pairs for dataset '{ds.name}'")
        return generated

    # ── Export ────────────────────────────────────────────

    def export_jsonl(self, dataset_id: str, output_path: Path | None = None) -> str:
        """Export dataset as JSONL in the configured template format."""
        ds = self._datasets.get(dataset_id)
        if not ds:
            raise ValueError(f"Dataset {dataset_id} not found")

        lines = []
        for sample in ds.samples:
            if ds.template == "sharegpt":
                record = {
                    "conversations": [
                        {"from": "human", "value": f"{sample.instruction}\n\nContext: {sample.input}"},
                        {"from": "gpt", "value": sample.output},
                    ]
                }
            else:  # alpaca
                record = {
                    "instruction": sample.instruction,
                    "input": sample.input,
                    "output": sample.output,
                }
            lines.append(json.dumps(record))

        content = "\n".join(lines)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content)
            logger.info(f"Exported {len(lines)} samples to {output_path}")

        return content

    def validate(self, dataset_id: str) -> dict:
        """Validate dataset quality."""
        ds = self._datasets.get(dataset_id)
        if not ds:
            return {"valid": False, "error": "Dataset not found"}

        issues = []
        if ds.sample_count < 10:
            issues.append(f"Too few samples ({ds.sample_count}). Minimum recommended: 10")

        empty_outputs = sum(1 for s in ds.samples if len(s.output.strip()) < 10)
        if empty_outputs > 0:
            issues.append(f"{empty_outputs} samples have very short outputs")

        avg_output_len = sum(len(s.output) for s in ds.samples) / max(ds.sample_count, 1)

        return {
            "valid": len(issues) == 0,
            "sample_count": ds.sample_count,
            "avg_output_length": round(avg_output_len, 1),
            "issues": issues,
        }

    @staticmethod
    def _parse_qa_pair(response: str) -> dict | None:
        """Extract question-answer pair from LLM response."""
        import re
        match = re.search(r'\{[^}]+\}', response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if "question" in data and "answer" in data:
                    return data
            except json.JSONDecodeError:
                pass
        return None


# Module-level singleton
dataset_service = DatasetService()

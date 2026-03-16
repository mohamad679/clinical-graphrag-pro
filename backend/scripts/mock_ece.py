"""
# DEV UTILITY — Mock Calibration Data Seeder
#
# This script injects hardcoded calibration metrics into the database
# for UI development and dashboard testing purposes ONLY.
#
# For real calibration evaluation, use: scripts/evaluate_calibration.py
"""

import asyncio
from app.core.database import async_session_factory
from app.services.evaluation_storage import EvaluationStorageService

async def mock_ece():
    storage = EvaluationStorageService()
    
    metrics = {
        "ece": 0.082,  # Example great calibration error
        "reliability_curve": [
            {"bin": "0%-10%", "accuracy": 5.0, "confidence": 8.0, "count": 2},
            {"bin": "10%-20%", "accuracy": 15.0, "confidence": 15.0, "count": 5},
            {"bin": "20%-30%", "accuracy": 28.0, "confidence": 25.0, "count": 3},
            {"bin": "30%-40%", "accuracy": 35.0, "confidence": 35.0, "count": 8},
            {"bin": "40%-50%", "accuracy": 45.0, "confidence": 45.0, "count": 12},
            {"bin": "50%-60%", "accuracy": 62.0, "confidence": 55.0, "count": 15},
            {"bin": "60%-70%", "accuracy": 68.0, "confidence": 65.0, "count": 20},
            {"bin": "70%-80%", "accuracy": 72.0, "confidence": 75.0, "count": 25},
            {"bin": "80%-90%", "accuracy": 88.0, "confidence": 85.0, "count": 40},
            {"bin": "90%-100%", "accuracy": 96.0, "confidence": 95.0, "count": 50}
        ]
    }
    
    async with async_session_factory() as db:
        await storage.save_evaluation(
            db=db,
            evaluation_type="calibration",
            metrics=metrics,
            dataset_size=180,
            metadata={"test_run": "mock_for_dashboard"}
        )
        print("Mocked ECE injected successfully.")

if __name__ == "__main__":
    asyncio.run(mock_ece())

import pytest
from app.services.tool_registry import tool_medical_calculator

@pytest.mark.asyncio
async def test_calculator_egfr_correctness():
    """Verify eGFR calculations against manual calculations using the 2021 CKD-EPI race-free equation."""
    # Case 1: Female, Age 50, Creatinine 0.6 mg/dL (SCr <= 0.7)
    res1 = await tool_medical_calculator("egfr", {"creatinine": 0.6, "age": 50, "gender": "female"})
    assert "error" not in res1
    assert res1["unit"] == "mL/min/1.73m²"
    # Manual computation: 142 * (0.6/0.7)**-0.241 * 1.0**-1.2 * 0.9938**50 * 1.012 ≈ 109.3
    assert abs(res1["value"] - 109.3) < 0.2
    
    # Case 2: Female, Age 50, Creatinine 1.0 mg/dL (SCr > 0.7)
    res2 = await tool_medical_calculator("egfr", {"creatinine": 1.0, "age": 50, "gender": "female"})
    assert "error" not in res2
    # Manual computation: 142 * 1.0**-0.241 * (1.0/0.7)**-1.2 * 0.9938**50 * 1.012 ≈ 68.7
    assert abs(res2["value"] - 68.7) < 0.2

    # Case 3: Male, Age 60, Creatinine 1.2 mg/dL (SCr > 0.9)
    res3 = await tool_medical_calculator("egfr", {"creatinine": 1.2, "age": 60, "gender": "male"})
    assert "error" not in res3
    # Manual computation: 142 * 1.0**-0.302 * (1.2/0.9)**-1.2 * 0.9938**60 * 1.0 ≈ 69.1
    assert abs(res3["value"] - 69.1) < 0.2

@pytest.mark.asyncio
async def test_calculator_egfr_validation():
    """Verify that eGFR rejects child age, non-positive inputs, and clinical outliers."""
    # Reject age < 18
    res1 = await tool_medical_calculator("egfr", {"creatinine": 0.9, "age": 17, "gender": "male"})
    assert "error" in res1
    assert "aged 18 or older" in res1["error"]

    # Reject non-positive creatinine
    res2 = await tool_medical_calculator("egfr", {"creatinine": -0.5, "age": 40, "gender": "female"})
    assert "error" in res2
    
    # Reject invalid gender
    res3 = await tool_medical_calculator("egfr", {"creatinine": 1.0, "age": 40, "gender": "other"})
    assert "error" in res3

@pytest.mark.asyncio
async def test_calculator_bmi_validation():
    """Verify BMI validation rules (positive bounds and categories)."""
    # Valid BMI
    res = await tool_medical_calculator("bmi", {"weight_kg": 70, "height_m": 1.75})
    assert "error" not in res
    assert res["value"] == 22.9
    assert res["category"] == "Normal"
    
    # Out of physiological bounds height (too high)
    res_high = await tool_medical_calculator("bmi", {"weight_kg": 70, "height_m": 3.5})
    assert "error" in res_high
    
    # Out of physiological bounds height (too low)
    res_low = await tool_medical_calculator("bmi", {"weight_kg": 70, "height_m": 0.1})
    assert "error" in res_low

@pytest.mark.asyncio
async def test_calculator_cha2ds2_vasc_validation():
    """Verify CHA2DS2-VASc scoring and input validation."""
    # Male, Age 75, Stroke History (+2), Hypertension (+1), CHF (+1)
    res = await tool_medical_calculator("cha2ds2_vasc", {
        "gender": "male",
        "age": 75,
        "stroke_history": True,
        "hypertension": True,
        "congestive_heart_failure": True
    })
    # Points: Age >= 75: 2 points, Stroke: 2 points, Hypertension: 1 point, CHF: 1 point. Total: 6
    assert "error" not in res
    assert res["score"] == 6
    assert "disclaimer" in res

import pytest
import numpy as np
from unittest.mock import MagicMock, patch

# Ensure app modules are importable
from app.services.dicom_scrubber import (
    DicomScrubResult,
    _utc_now_isoformat,
    _normalize_pixel_array,
    _pixel_array_to_png_bytes,
    _remove_phi_tags,
    _scrub_dicom_impl,
    scrub_dicom,
    scrub_dicom_sync,
)

def test_utc_now_isoformat():
    val = _utc_now_isoformat()
    assert isinstance(val, str)
    assert val.endswith("Z")

def test_normalize_pixel_array():
    dataset = MagicMock()
    # 2D array
    dataset.pixel_array = np.array([[0, 128], [255, 64]], dtype=np.uint8)
    dataset.PhotometricInterpretation = "MONOCHROME2"
    res = _normalize_pixel_array(dataset)
    assert res.shape == (2, 2)
    assert res[0, 0] == 0
    assert res[1, 0] == 255

    # monochrome 1 inversion
    dataset.PhotometricInterpretation = "MONOCHROME1"
    res_inv = _normalize_pixel_array(dataset)
    assert res_inv[0, 0] == 255
    assert res_inv[1, 0] == 0

    # 3D array with channels first (e.g. MONAI style 3, H, W)
    dataset.pixel_array = np.zeros((3, 4, 5), dtype=np.uint8)
    dataset.PhotometricInterpretation = "RGB"
    res_3d = _normalize_pixel_array(dataset)
    assert res_3d.shape == (4, 5, 3)

def test_pixel_array_to_png_bytes():
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((5, 5), dtype=np.uint8)
    dataset.PhotometricInterpretation = "MONOCHROME2"
    png_bytes, w, h = _pixel_array_to_png_bytes(dataset)
    assert isinstance(png_bytes, bytes)
    assert w == 5
    assert h == 5

    # 3D RGB
    dataset.pixel_array = np.zeros((5, 5, 3), dtype=np.uint8)
    dataset.PhotometricInterpretation = "RGB"
    png_bytes, w, h = _pixel_array_to_png_bytes(dataset)
    assert w == 5

    # Invalid dimensions
    dataset.pixel_array = np.zeros((5, 5, 5, 5), dtype=np.uint8)
    with pytest.raises(ValueError, match="Not a valid DICOM file"):
        _pixel_array_to_png_bytes(dataset)

def test_remove_phi_tags():
    dataset = {}
    # tag_for_keyword returns a tag if keyword is valid
    with patch("pydicom.datadict.tag_for_keyword", side_effect=lambda kw: kw):
        # mock dataset having some PHI keywords
        dataset["PatientName"] = "John Doe"
        dataset["PatientID"] = "12345"
        dataset["OtherTag"] = "KeepMe"
        
        removed = _remove_phi_tags(dataset)
        assert "PatientName" in removed
        assert "PatientID" in removed
        assert "PatientName" not in dataset
        assert "PatientID" not in dataset
        assert "OtherTag" in dataset

def test_scrub_dicom_impl():
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((4, 4), dtype=np.uint8)
    dataset.Modality = "CT"
    dataset.BodyPartExamined = "CHEST"
    
    # Mock pydicom.dcmread
    with patch("pydicom.dcmread", return_value=dataset), \
         patch("app.services.dicom_scrubber._remove_phi_tags", return_value=["PatientName"]):
        
        res = _scrub_dicom_impl(b"fake dicom bytes")
        assert isinstance(res, DicomScrubResult)
        assert res.modality == "CT"
        assert res.body_part == "CHEST"
        assert res.tags_removed == ["PatientName"]
        assert res.width == 4
        assert res.height == 4

def test_scrub_dicom_impl_invalid():
    from pydicom.errors import InvalidDicomError
    with patch("pydicom.dcmread", side_effect=InvalidDicomError("Invalid")):
        with pytest.raises(ValueError, match="Not a valid DICOM file"):
            _scrub_dicom_impl(b"invalid bytes")

@pytest.mark.anyio
async def test_scrub_dicom_async():
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((4, 4), dtype=np.uint8)
    dataset.Modality = "MR"
    dataset.BodyPartExamined = "BRAIN"
    
    with patch("pydicom.dcmread", return_value=dataset), \
         patch("app.services.dicom_scrubber._remove_phi_tags", return_value=[]):
        res = await scrub_dicom(b"fake bytes")
        assert res.modality == "MR"

def test_scrub_dicom_sync_no_loop():
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((4, 4), dtype=np.uint8)
    dataset.Modality = "CT"
    dataset.BodyPartExamined = "CHEST"

    with patch("asyncio.get_event_loop", side_effect=RuntimeError("no loop")), \
         patch("pydicom.dcmread", return_value=dataset), \
         patch("app.services.dicom_scrubber._remove_phi_tags", return_value=[]):
        res = scrub_dicom_sync(b"fake bytes")
        assert res.modality == "CT"

def test_scrub_dicom_sync_with_loop():
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((4, 4), dtype=np.uint8)
    dataset.Modality = "CT"
    dataset.BodyPartExamined = "CHEST"
    
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = False
    mock_loop.run_until_complete.side_effect = lambda coro: _scrub_dicom_impl(b"fake bytes")
    
    with patch("asyncio.get_event_loop", return_value=mock_loop), \
         patch("pydicom.dcmread", return_value=dataset), \
         patch("app.services.dicom_scrubber._remove_phi_tags", return_value=[]):
        res = scrub_dicom_sync(b"fake bytes")
        assert res.modality == "CT"

def test_normalize_pixel_array_3d_single_channel():
    """Test 3D array with single channel (H, W, 1) -> moves channel first, then discards channel dim."""
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((2, 5, 1), dtype=np.uint8)
    dataset.PhotometricInterpretation = "MONOCHROME2"
    res = _normalize_pixel_array(dataset)
    assert res.shape == (2, 5)

def test_pixel_array_to_png_bytes_rgba():
    """Test RGBA pixel array (H, W, 4) converts to PNG bytes."""
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((4, 5, 4), dtype=np.uint8)
    dataset.PhotometricInterpretation = "RGB"
    png_bytes, w, h = _pixel_array_to_png_bytes(dataset)
    assert isinstance(png_bytes, bytes)
    assert w == 5
    assert h == 4

def test_scrub_dicom_impl_pydicom_general_exception():
    """Test general exceptions originating from pydicom packages are handled as value errors."""
    class MockPydicomError(Exception):
        pass
    MockPydicomError.__module__ = "pydicom.custom"
    
    with patch("pydicom.dcmread", side_effect=MockPydicomError("Pydicom error")):
        with pytest.raises(ValueError, match="Not a valid DICOM file"):
            _scrub_dicom_impl(b"some bytes")

def test_scrub_dicom_impl_other_general_exception():
    """Test exceptions not from pydicom package are reraised."""
    with patch("pydicom.dcmread", side_effect=KeyError("Generic key error")):
        with pytest.raises(KeyError):
            _scrub_dicom_impl(b"some bytes")

def test_scrub_dicom_sync_loop_running():
    """Test scrub_dicom_sync when loop is running behaves correctly."""
    dataset = MagicMock()
    dataset.pixel_array = np.zeros((4, 4), dtype=np.uint8)
    dataset.Modality = "MR"
    dataset.BodyPartExamined = "BRAIN"
    
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    
    with patch("asyncio.get_event_loop", return_value=mock_loop), \
         patch("pydicom.dcmread", return_value=dataset), \
         patch("app.services.dicom_scrubber._remove_phi_tags", return_value=[]):
        res = scrub_dicom_sync(b"fake bytes")
        assert res.modality == "MR"


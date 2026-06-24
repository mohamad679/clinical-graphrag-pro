import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.audio_processing import AudioProcessingService, ValidatedAudioUpload

@pytest.fixture
def phase1_env():
    return None

@pytest.fixture
def anyio_backend():
    return "asyncio"

def create_mock_wav(duration_secs=1.0, sample_rate=44100, bits_per_sample=16, num_channels=1):
    # Construct a minimal valid WAV header
    # byte_rate = sample_rate * num_channels * bits_per_sample / 8
    byte_rate = int(sample_rate * num_channels * bits_per_sample / 8)
    data_size = int(duration_secs * byte_rate)
    
    header = bytearray(44)
    header[0:4] = b"RIFF"
    # overall size: data_size + 36
    header[4:8] = (data_size + 36).to_bytes(4, "little")
    header[8:12] = b"WAVE"
    header[12:16] = b"fmt "
    header[16:20] = (16).to_bytes(4, "little") # format chunk size
    header[20:22] = (1).to_bytes(2, "little") # PCM
    header[22:24] = num_channels.to_bytes(2, "little")
    header[24:28] = sample_rate.to_bytes(4, "little")
    header[28:32] = byte_rate.to_bytes(4, "little")
    header[32:34] = (num_channels * bits_per_sample // 8).to_bytes(2, "little")
    header[34:36] = bits_per_sample.to_bytes(2, "little")
    header[36:40] = b"data"
    header[40:44] = data_size.to_bytes(4, "little")
    
    # Append data payload
    return bytes(header) + b"\x00" * data_size

def test_validate_audio_upload_valid_wav():
    service = AudioProcessingService()
    content = create_mock_wav(duration_secs=5.0)
    
    res = service.validate_audio_upload(
        filename="test.wav",
        claimed_content_type="audio/wav",
        content=content
    )
    assert res.normalized_filename == "test.wav"
    assert res.detected_kind == "wav"
    assert res.extension == ".wav"
    assert res.mime_type == "audio/wav"
    assert res.duration_seconds == 5.0
    assert res.validation_metadata["magic_bytes_checked"] is True

def test_validate_audio_upload_unsupported_extension():
    service = AudioProcessingService()
    with pytest.raises(ValueError) as exc:
        service.validate_audio_upload("test.exe", "audio/wav", b"riff")
    assert "Unsupported audio type" in str(exc.value)

def test_validate_audio_upload_too_large():
    service = AudioProcessingService()
    # Mock settings.audio_max_upload_size_mb to 1MB
    with patch("app.services.audio_processing.settings") as mock_settings:
        mock_settings.audio_max_upload_size_mb = 1
        with pytest.raises(ValueError) as exc:
            service.validate_audio_upload("test.wav", "audio/wav", b"\x00" * (2 * 1024 * 1024))
        assert "Audio file too large" in str(exc.value)

def test_validate_audio_upload_magic_signature_mismatch():
    service = AudioProcessingService()
    # Extension .wav but magic signature is invalid
    with pytest.raises(ValueError) as exc:
        service.validate_audio_upload("test.wav", "audio/wav", b"not-a-wav-signature")
    assert "magic bytes" in str(exc.value)

def test_validate_audio_upload_extension_signature_mismatch():
    service = AudioProcessingService()
    # Webm signature but extension .wav
    webm_sig = b"\x1A\x45\xDF\xA3\x00\x00"
    with pytest.raises(ValueError) as exc:
        service.validate_audio_upload("test.wav", "audio/wav", webm_sig)
    assert "does not match detected audio type" in str(exc.value)

def test_validate_audio_upload_exceeds_duration():
    service = AudioProcessingService()
    content = create_mock_wav(duration_secs=100.0)
    with patch("app.services.audio_processing.settings") as mock_settings:
        mock_settings.audio_max_duration_seconds = 60
        mock_settings.audio_max_upload_size_mb = 50
        with pytest.raises(ValueError) as exc:
            service.validate_audio_upload("test.wav", "audio/wav", content)
        assert "exceeds the limit" in str(exc.value)

def test_detect_kinds():
    service = AudioProcessingService()
    
    # Webm
    assert service._detect_kind(b"\x1A\x45\xDF\xA3") == "webm"
    # Ogg
    assert service._detect_kind(b"OggS") == "ogg"
    # Mp3
    assert service._detect_kind(b"ID3") == "mp3"
    assert service._detect_kind(bytes([0xFF, 0xE5])) == "mp3"
    # M4a
    assert service._detect_kind(b"\x00\x00\x00\x0cftypM4A ") == "m4a"
    # None
    assert service._detect_kind(b"random") is None

@pytest.mark.anyio
async def test_transcribe_bytes_no_key():
    service = AudioProcessingService()
    with patch("app.services.audio_processing.settings") as mock_settings:
        mock_settings.groq_api_key = ""
        with pytest.raises(RuntimeError):
            await service.transcribe_bytes(filename="test.wav", content=b"fake", mime_type="audio/wav")

@pytest.mark.anyio
async def test_transcribe_bytes_success():
    service = AudioProcessingService()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "text": "Transcribed clinical note.",
        "language": "english"
    }
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    
    with (
        patch("app.services.audio_processing.settings") as mock_settings,
        patch.object(service, "_get_client", return_value=mock_client)
    ):
        mock_settings.groq_api_key = "fake-key"
        mock_settings.audio_allow_auto_language_detection = False
        mock_settings.audio_default_language = "en"
        
        res = await service.transcribe_bytes(filename="test.wav", content=b"fake", mime_type="audio/wav")
        assert res["text"] == "Transcribed clinical note."
        assert res["language"] == "english"
        assert res["provider"] == "groq"

@pytest.mark.anyio
async def test_store_audio_upload():
    service = AudioProcessingService()
    mock_storage = AsyncMock()
    
    validated = ValidatedAudioUpload(
        normalized_filename="test.wav",
        detected_kind="wav",
        extension=".wav",
        mime_type="audio/wav",
        duration_seconds=5.0,
        validation_metadata={}
    )
    
    with patch("app.services.audio_processing.storage_service", mock_storage):
        await service.store_audio_upload(content=b"data", validated=validated)
        mock_storage.store_bytes.assert_called_once_with(
            category="audio",
            filename="test.wav",
            content=b"data",
            content_type="audio/wav"
        )

@pytest.mark.anyio
async def test_close_client():
    service = AudioProcessingService()
    mock_client = AsyncMock()
    service._client = mock_client
    await service.close()
    mock_client.aclose.assert_called_once()

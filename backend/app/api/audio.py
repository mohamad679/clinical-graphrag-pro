"""
Audio processing API endpoints.
Handles audio uploads, transcription, and translation via Groq's Whisper API.
"""

import logging
import os
import tempfile

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audio", tags=["Audio"])
settings = get_settings()

@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
):
    """
    Accepts an audio file (mp3, wav, mp4, etc.),
    Sends it to Groq's translation endpoint (whisper-large-v3) 
    which automatically detects language, translates to English, and transcribes.
    """
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=500, detail="GROQ_API_KEY is not configured for audio services."
        )

    # Save incoming upload temporarily to disk since httpx needs a file pointer to read
    temp_path = ""
    try:
        suffix = os.path.splitext(file.filename)[1] if file.filename else ".m4a"
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        
        # Read the file content into memory
        content = await file.read()
        
        # Write it to the temp file synchronously since mkstemp returns an fd
        with os.fdopen(fd, 'wb') as temp_audio:
            temp_audio.write(content)

    except Exception as e:
        logger.error(f"Failed to process incoming audio upload: {e}")
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail="Could not buffer uploaded audio file.")

    try:
        # Send to Groq API
        url = "https://api.groq.com/openai/v1/audio/translations"
        headers = {
            "Authorization": f"Bearer {settings.groq_api_key}"
            # Let httpx set multipart/form-data boundary automatically
        }
        
        with open(temp_path, "rb") as f:
            files = {"file": (file.filename or "audio.m4a", f, file.content_type or "audio/m4a")}
            data = {"model": "whisper-large-v3"}

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, files=files, data=data)
                response.raise_for_status()
                
                result = response.json()
                transcribed_text = result.get("text", "").strip()
                
                return {"text": transcribed_text}

    except httpx.HTTPStatusError as e:
        error_detail = e.response.text
        logger.error(f"Groq Whisper API error: {error_detail}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Transcription failed: {error_detail}")
    except Exception as e:
        logger.error(f"Internal transcription proxy error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error acting as audio proxy.")
    finally:
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)

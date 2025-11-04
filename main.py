from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import time
import asyncio
import httpx
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# OpenAI API configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = "https://api.openai.com/v1"

# Video storage configuration
VIDEOS_DIR = Path("videos")
VIDEOS_DIR.mkdir(exist_ok=True)  # Create directory if it doesn't exist

class VideoRequest(BaseModel):
    prompt: str
    model: str = "sora-2"
    size: str = "720x1280"  # Vertical by default - Supported: 720x1280, 1280x720, 1024x1792, 1792x1024
    duration: int = 8  # Only 4, 8, or 12 seconds supported

class VideoResponse(BaseModel):
    video_url: str
    status: str
    message: str

@app.get("/")
async def read_root():
    return FileResponse("index.html")

async def wait_for_video_completion(video_id: str, max_wait: int = 600) -> dict:
    """
    Poll video status until completion or timeout

    Args:
        video_id: The ID of the video to check
        max_wait: Maximum wait time in seconds (default: 10 minutes)

    Returns:
        Video data with URL when completed
    """
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }

    start_time = time.time()
    # Set longer timeout for video operations (5 min total, 2 min for any single operation)
    timeout = httpx.Timeout(120.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.time() - start_time < max_wait:
            # Check video status
            response = await client.get(
                f"{OPENAI_API_BASE}/videos/{video_id}",
                headers=headers
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to check video status: {response.text}"
                )

            video_data = response.json()
            status = video_data.get("status")

            if status == "completed":
                # Video is ready, now download the actual video content
                print(f"DEBUG - Video completed, downloading content for {video_id}")

                video_filename = f"{video_id}.mp4"
                video_path = VIDEOS_DIR / video_filename

                # Stream download the video content (prevents timeout on large files)
                async with client.stream(
                    "GET",
                    f"{OPENAI_API_BASE}/videos/{video_id}/content",
                    headers=headers,
                    follow_redirects=True
                ) as content_response:

                    if content_response.status_code == 200:
                        # Download and save video in chunks
                        total_bytes = 0
                        with open(video_path, "wb") as f:
                            async for chunk in content_response.aiter_bytes(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                                    total_bytes += len(chunk)

                        print(f"DEBUG - Video saved to {video_path} ({total_bytes} bytes)")

                        # Store the local file path in video_data
                        video_data["local_path"] = str(video_path)
                        video_data["video_filename"] = video_filename
                        return video_data
                    else:
                        error_text = await content_response.aread()
                        raise HTTPException(
                            status_code=content_response.status_code,
                            detail=f"Failed to download video content: {error_text.decode()}"
                        )

            elif status == "failed":
                error = video_data.get("error", {}).get("message", "Unknown error")
                raise HTTPException(status_code=500, detail=f"Video generation failed: {error}")

            # Wait before next poll (exponential backoff)
            await asyncio.sleep(min(5, 1 + (time.time() - start_time) / 30))

    raise HTTPException(status_code=408, detail="Video generation timeout")


@app.post("/api/generate-video", response_model=VideoResponse)
async def generate_video(request: VideoRequest):
    """
    Generate video using OpenAI's Video API (Sora)
    """
    try:
        # Check if API key is set
        if not OPENAI_API_KEY:
            raise HTTPException(
                status_code=500,
                detail="OPENAI_API_KEY not configured. Please set it in .env file"
            )

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        # Prepare JSON payload for video generation
        payload = {
            "model": request.model,
            "prompt": request.prompt,
            "size": request.size,
        }

        # Add optional duration if provided
        if request.duration:
            payload["seconds"] = str(request.duration)

        # Create video generation request
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{OPENAI_API_BASE}/videos",
                headers=headers,
                json=payload
            )

            if response.status_code not in [200, 201]:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("error", {}).get("message", error_detail)
                except:
                    pass
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create video: {error_detail}"
                )

            video_data = response.json()
            video_id = video_data.get("id")

            if not video_id:
                raise HTTPException(status_code=500, detail="No video ID returned")

        # Wait for video to complete and download it
        completed_video = await wait_for_video_completion(video_id)

        # Debug: Print the response to understand structure
        print(f"DEBUG - Completed video response keys: {completed_video.keys()}")

        # Get video filename (should be added by wait_for_video_completion)
        video_filename = completed_video.get("video_filename")

        if not video_filename:
            # If still not found, return the whole response for debugging
            raise HTTPException(
                status_code=500,
                detail=f"No video file found. Response: {str(completed_video)[:500]}"
            )

        # Return local URL that points to our server
        local_video_url = f"/videos/{video_filename}"

        return VideoResponse(
            video_url=local_video_url,
            status="success",
            message="Video generated successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        error_message = str(e)
        raise HTTPException(status_code=500, detail=f"Error generating video: {error_message}")

@app.get("/api/health")
async def health_check():
    """
    Check if the API is running and OpenAI API key is configured
    """
    api_key_configured = bool(OPENAI_API_KEY)
    return {
        "status": "ok",
        "api_key_configured": api_key_configured
    }

@app.get("/videos/{video_filename}")
async def serve_video(video_filename: str):
    """
    Serve downloaded video files
    """
    video_path = VIDEOS_DIR / video_filename

    # Check if file exists
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    # Serve the video file
    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=video_filename
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

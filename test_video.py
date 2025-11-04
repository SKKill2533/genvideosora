#!/usr/bin/env python3
"""
Test script to generate a video using the SoraGen API
"""
import requests
import time

# API endpoint
API_URL = "http://127.0.0.1:8000/api/generate-video"

# Test prompt - simple and short
prompt = "A cute cat sitting on a table, looking at the camera, realistic home video"

# Request payload
payload = {
    "prompt": prompt,
    "model": "sora-2",
    "size": "720x1280",  # Vertical
    "duration": 8
}

print("🎬 Testing SoraGen video generation...")
print(f"📝 Prompt: {prompt}")
print(f"📐 Size: {payload['size']} (Vertical)")
print(f"⏱️  Duration: {payload['duration']} seconds")
print(f"🤖 Model: {payload['model']}")
print("\n⏳ Sending request to API (this may take 1-3 minutes)...\n")

start_time = time.time()

try:
    response = requests.post(API_URL, json=payload, timeout=600)

    elapsed = time.time() - start_time

    if response.status_code == 200:
        data = response.json()
        print(f"✅ Success! Video generated in {elapsed:.1f} seconds")
        print(f"🎥 Video URL: http://127.0.0.1:8000{data['video_url']}")
        print(f"💾 You can view the video at: http://127.0.0.1:8000")
        print(f"📂 Local file: videos/{data['video_url'].split('/')[-1]}")
    else:
        print(f"❌ Error {response.status_code}")
        print(f"📄 Response: {response.text}")

except requests.exceptions.Timeout:
    print("⏱️  Request timeout - video generation took too long")
except Exception as e:
    print(f"❌ Error: {str(e)}")

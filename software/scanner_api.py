"""
Document Scanner API — FastAPI + OpenCV
========================================
Pipeline:
  1. Receive image upload
  2. Detect A4 page — colour-based (default) or corner/edge-based
  3. Apply 4-point perspective transform  (imutils)
  4. Resize to A4 at 300 DPI  (2480 × 3508 px)
  5. Enhance contrast for a clean "scanned" look
  6. Return the processed image as PNG
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import router

app = FastAPI(title="DocScanner API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

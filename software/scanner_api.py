"""
Document Scanner API — FastAPI + OpenCV
========================================
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import db
from auth import AuthMiddleware, auth_router, init_auth
from routes import router

app = FastAPI(title="DocScanner API", version="2.0.0")

app.add_middleware(AuthMiddleware)

frontend_origins = [
    origin.strip()
    for origin in os.environ.get(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

app.include_router(auth_router)
app.include_router(router)


@app.on_event("startup")
def _init_db() -> None:
    db.init_db()
    init_auth()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

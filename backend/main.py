from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Apollo Stock Trading System")

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = REPO_ROOT / "frontend-prototype" / "mock"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}


def _read_mock_json(filename: str) -> dict:
    path = MOCK_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Mock file missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in mock file: {filename}") from exc


@app.get("/api/portfolio")
def get_portfolio():
    return _read_mock_json("portfolio.sample.json")


@app.get("/api/recommendations")
def get_recommendations():
    return _read_mock_json("recommendations.sample.json")


@app.get("/api/watchlist")
def get_watchlist():
    return _read_mock_json("watchlist.sample.json")


@app.get("/api/version")
def get_version():
    return {"service": "apollo-backend", "mock": True}

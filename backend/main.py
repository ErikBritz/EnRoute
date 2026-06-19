from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import MIN_VELOCITY, FLIGHT_VELOCITY_THRESHOLD
from .database import AvonetDatabase
from .energetics_engine import AvianEnergeticsEngine

TRACK_COLUMNS = {
    "latitude": "location-lat",
    "longitude": "location-long",
    "timestamp": "timestamp"
}

app = FastAPI(title="LBS Universal Translator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

BASE_DIR = Path(__file__).resolve().parents[1]
AVONET_PATH = BASE_DIR / "data" / "avonet_birds.csv"
AVONET_DB: AvonetDatabase | None = None

FRONTEND_DIR = BASE_DIR / "frontend"

# API routes are registered below.
# Static frontend is mounted LAST so /api/* routes take priority.


def _get_avonet_db() -> AvonetDatabase:
    global AVONET_DB
    if not AVONET_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"AVONET dataset not found at {AVONET_PATH}. Add the CSV and retry."
        )
    if AVONET_DB is None:
        AVONET_DB = AvonetDatabase(str(AVONET_PATH))
    return AVONET_DB


def haversine_meters(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)

    d_lat = lat2_rad - lat1_rad
    d_lon = lon2_rad - lon1_rad

    a = np.sin(d_lat / 2.0) ** 2 + np.cos(lat1_rad) * \
        np.cos(lat2_rad) * np.sin(d_lon / 2.0) ** 2
    c = 2.0 * np.arcsin(np.sqrt(a))
    return 6371000.0 * c


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [value for value in TRACK_COLUMNS.values()
               if value not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"Missing columns: {', '.join(missing)}")


def _clean_track(df: pd.DataFrame) -> pd.DataFrame:
    lat = TRACK_COLUMNS["latitude"]
    lon = TRACK_COLUMNS["longitude"]
    time = TRACK_COLUMNS["timestamp"]

    df = df.copy()
    df[time] = pd.to_datetime(df[time], errors="coerce", utc=True)

    df = df.dropna(subset=[lat, lon, time])
    df = df[(df[lat] >= -90) & (df[lat] <= 90) &
            (df[lon] >= -180) & (df[lon] <= 180)]
    df = df.drop_duplicates(subset=[time])
    df = df.sort_values(time).reset_index(drop=True)

    if df.shape[0] < 2:
        raise HTTPException(
            status_code=400, detail="Not enough valid track points after cleaning.")

    return df


def _compute_segments(df: pd.DataFrame, engine: AvianEnergeticsEngine) -> dict[str, Any]:
    lat = TRACK_COLUMNS["latitude"]
    lon = TRACK_COLUMNS["longitude"]
    time = TRACK_COLUMNS["timestamp"]

    df["prev_lat"] = df[lat].shift(1)
    df["prev_lon"] = df[lon].shift(1)
    df["prev_time"] = df[time].shift(1)

    df = df.dropna(subset=["prev_lat", "prev_lon",
                   "prev_time"]).reset_index(drop=True)

    distances = haversine_meters(df["prev_lat"].to_numpy(), df["prev_lon"].to_numpy(),
                                 df[lat].to_numpy(), df[lon].to_numpy())
    dt_seconds = (df[time] - df["prev_time"]).dt.total_seconds().to_numpy()

    valid = (dt_seconds > 0) & np.isfinite(distances)
    distances = distances[valid]
    dt_seconds = dt_seconds[valid]
    velocities = distances / dt_seconds

    flight_distances: list[float] = []
    flight_energies:  list[float] = []
    rest_energies:    list[float] = []
    all_distances:    list[float] = []

    for distance, dt, velocity in zip(distances, dt_seconds, velocities):
        if distance < 0 or dt <= 0:
            continue
        all_distances.append(float(distance))

        if velocity >= FLIGHT_VELOCITY_THRESHOLD:
            # Active flight segment — use aerodynamic model
            power = engine.total_power(max(float(velocity), MIN_VELOCITY))
            energy = power * dt
            flight_distances.append(float(distance))
            flight_energies.append(energy)
        else:
            # Perching / resting — track resting energy but exclude from CoT
            rest_power = engine._active_metabolic_power()
            rest_energies.append(rest_power * dt)

    if not flight_energies:
        raise HTTPException(
            status_code=400,
            detail="No flight segments detected. Check that the track contains moving fixes "
                   "(velocity ≥ 3 m/s). If the file only contains stationary fixes or "
                   "GPS noise, the energetics model cannot be applied.")

    total_flight_dist = float(np.sum(flight_distances))
    total_flight_energy = float(np.sum(flight_energies))
    total_rest_energy = float(np.sum(rest_energies))
    mean_cot = total_flight_energy / total_flight_dist if total_flight_dist > 0 else 0.0

    return {
        "segments":            int(len(flight_energies)),
        "total_distance_m":    total_flight_dist,
        "total_energy_j":      total_flight_energy,
        "resting_energy_j":    total_rest_energy,
        "mean_cot_j_m":        float(mean_cot),
    }


@app.post("/api/upload-track")
async def upload_track(
    file: UploadFile = File(...),
    species_scientific_name: str = Form(...)
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    content = await file.read()
    df = pd.read_csv(BytesIO(content), low_memory=False)
    _validate_columns(df)
    cleaned = _clean_track(df)

    db = _get_avonet_db()

    try:
        traits = db.get_traits(species_scientific_name)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    engine = AvianEnergeticsEngine(
        mass_kg=traits.mass_kg,
        wing_span_m=traits.wing_span_m,
        aspect_ratio=traits.aspect_ratio,
        frontal_area_m2=traits.frontal_area_m2
    )

    metrics = _compute_segments(cleaned, engine)

    # Include GPS points in response so the frontend never needs to re-parse
    # the uploaded file (which can be hundreds of MB).
    lat_col = TRACK_COLUMNS["latitude"]
    lon_col = TRACK_COLUMNS["longitude"]
    time_col = TRACK_COLUMNS["timestamp"]
    speed_col = "ground-speed"

    # Downsample to at most 2000 points so the JSON fits in sessionStorage.
    # 5 decimal places gives ~1 m accuracy — more than enough for visualisation.
    MAX_POINTS = 2000
    step = max(1, len(cleaned) // MAX_POINTS)
    sampled = cleaned.iloc[::step].reset_index(drop=True)

    gps_rows = [
        {
            "lat":   round(float(r[lat_col]),   5),
            "lon":   round(float(r[lon_col]),   5),
            "time":  r[time_col].isoformat() if hasattr(r[time_col], "isoformat") else str(r[time_col]),
            "speed": round(float(r[speed_col]), 3) if speed_col in sampled.columns and pd.notna(r.get(speed_col)) else None,
        }
        for _, r in sampled.iterrows()
    ]

    return {
        "species": species_scientific_name,
        "points_cleaned": int(cleaned.shape[0]),
        **metrics,
        "gpsRows": gps_rows,
    }


# Mount frontend AFTER all /api routes so static files don't shadow the API.
# Served at /static/ — HTML pages have explicit routes below.
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/", response_class=FileResponse)
def index() -> str:
    return str(FRONTEND_DIR / "index.html")


@app.get("/index.html", response_class=FileResponse)
def index_html() -> str:
    return str(FRONTEND_DIR / "index.html")


@app.get("/visualize.html", response_class=FileResponse)
def visualize() -> str:
    return str(FRONTEND_DIR / "visualize.html")

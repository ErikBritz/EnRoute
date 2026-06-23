# LBS Universal Translator

A web tool that translates raw animal tracking data into **energetic cost-of-transport** estimates by combining GPS movement tracks with morphological trait databases.

## Overview

When a user uploads a Movebank tracking file, the app automatically:

1. Matches the species to the **AVONET** trait database (mass, wing span, hand-wing index, aspect ratio).
2. Runs an **avian flight-energetics model** (Pennycuick 2008) on each movement segment, calculating:
   - Induced, parasitic, and profile power
   - Total metabolic power
   - Cost of Transport (J/m) at observed or maximum-range speed
3. Returns a per-segment energy layer alongside the geographic track.

## Methods

### Trait Lookup — AVONET
Species morphology (body mass, wing length, hand-wing index) is sourced from the AVONET trait database. Missing secondary traits (aspect ratio, frontal area) are estimated from allometric scaling equations:

$$A_R = 2.04 \ln(\text{HWI}) + 2.58 \qquad S_f = 0.00813 \cdot m^{0.666}$$

### Flight Energetics
Power is decomposed into three components:

$$P_{ind} = \frac{k \cdot (mg)^2}{2 \rho v \pi b^2} \qquad P_{par} = \frac{1}{2} \rho v^3 S_f C_{D,b} \qquad P_{pro} = \frac{1}{2} \rho v^3 S_w C_{D,pro}$$

Total metabolic power includes basal/active metabolism scaled by muscle efficiency:

$$P_{total} = \frac{P_{ind} + P_{par} + P_{pro}}{\eta} + 10.5 \cdot m^{0.725}$$

Cost of Transport is then:

$$CoT = \frac{P_{total}}{v} \quad \text{(J/m)}$$

Maximum-range speed is found by minimising $P_{total}/v$ numerically.

## Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python) |
| Energetics | NumPy / SciPy |
| Trait database | AVONET CSV (pandas) |
| Frontend | Vanilla JS + Leaflet / Mapbox |

## Running Locally

```powershell
# activate virtual environment, then:
uvicorn backend.main:app --reload
```

Open `http://localhost:8000` in your browser.

## Data Sources

- AVONET trait database: <https://figshare.com/s/b990722d72a26b5bfead>
- Movebank tracking data: <https://www.movebank.org>
- Pennycuick, C.J. (2008). *Modelling the Flying Bird*. Academic Press.

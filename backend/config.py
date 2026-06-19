from __future__ import annotations

AIR_DENSITY = 1.225
GRAVITY = 9.81
MUSCLE_EFFICIENCY = 0.23
INDUCED_POWER_FACTOR = 1.2
BODY_DRAG_COEFFICIENT = 0.10

# Wing profile drag coefficient (Pennycuick 2008, ~0.02 for soaring birds)
CD_PROFILE = 0.02

# Allometric wingspan scaling: wingspan_m = WINGSPAN_K * mass_kg^WINGSPAN_EXP
# Greenewalt (1975) across all flying birds; avoids AVONET chord-vs-span ambiguity.
WINGSPAN_K = 1.17
WINGSPAN_EXP = 0.393

MIN_VELOCITY = 0.1

# Segments slower than this are treated as perching/resting, not active flight.
# CoT and flight distance/energy exclude these segments.
# 3 m/s ≈ 10 km/h — well below any bird's minimum aerodynamic speed.
FLIGHT_VELOCITY_THRESHOLD = 3.0

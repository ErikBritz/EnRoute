from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
from scipy.optimize import minimize_scalar

from .config import (AIR_DENSITY, BODY_DRAG_COEFFICIENT, CD_PROFILE, GRAVITY,
                     INDUCED_POWER_FACTOR, MUSCLE_EFFICIENCY, MIN_VELOCITY)


@dataclass(frozen=True)
class SegmentResult:
    velocity_mps: float
    power_total_w: float
    cost_of_transport_j_m: float


class AvianEnergeticsEngine:
    def __init__(self, mass_kg: float, wing_span_m: float, aspect_ratio: float,
                 frontal_area_m2: float) -> None:
        self.mass_kg = mass_kg
        self.wing_span_m = wing_span_m
        self.aspect_ratio = aspect_ratio
        self.frontal_area_m2 = frontal_area_m2

    def _minimum_power_speed(self) -> float:
        numerator = 4.0 * (self.mass_kg * GRAVITY) ** 2
        denominator = 3.0 * (AIR_DENSITY ** 2) * np.pi * (self.wing_span_m **
                                                          2) * self.frontal_area_m2 * BODY_DRAG_COEFFICIENT
        v_mp = (numerator / denominator) ** 0.25
        return float(v_mp)

    def _power_components(self, velocity_mps: float) -> tuple[float, float, float]:
        """Return (induced, parasitic, profile) mechanical power in watts."""
        induced = (INDUCED_POWER_FACTOR * (self.mass_kg * GRAVITY) ** 2) / (
            2.0 * AIR_DENSITY * velocity_mps *
            np.pi * (self.wing_span_m / 2.0) ** 2
        )
        parasitic = 0.5 * AIR_DENSITY * \
            (velocity_mps ** 3) * self.frontal_area_m2 * BODY_DRAG_COEFFICIENT
        # Profile drag on the wings — Pennycuick (2008) standard formula:
        # P_pro = 0.5 * rho * v^3 * S_wing * CD_pro  (mechanical watts)
        wing_area_m2 = self.wing_span_m ** 2 / self.aspect_ratio
        profile = 0.5 * AIR_DENSITY * \
            (velocity_mps ** 3) * wing_area_m2 * CD_PROFILE
        return induced, parasitic, profile

    def _active_metabolic_power(self) -> float:
        return 10.5 * (self.mass_kg ** 0.725)

    def total_power(self, velocity_mps: float) -> float:
        if velocity_mps <= 0:
            raise ValueError("Velocity must be positive.")
        induced, parasitic, profile = self._power_components(velocity_mps)
        mechanical = (induced + parasitic + profile) / MUSCLE_EFFICIENCY
        return self._active_metabolic_power() + mechanical

    def cost_of_transport(self, velocity_mps: float) -> SegmentResult:
        velocity = max(velocity_mps, MIN_VELOCITY)
        power_total = self.total_power(velocity)
        cot = power_total / velocity
        return SegmentResult(velocity_mps=velocity, power_total_w=power_total, cost_of_transport_j_m=cot)

    def maximum_range_speed(self) -> float:
        def objective(v: float) -> float:
            return self.total_power(v) / v

        bounds = (MIN_VELOCITY, 60.0)
        result = minimize_scalar(objective, bounds=bounds, method="bounded")
        if not result.success:
            raise RuntimeError("Failed to optimize maximum range speed.")
        return float(result.x)

    def route_a(self, velocities_mps: Iterable[float]) -> list[SegmentResult]:
        results: list[SegmentResult] = []
        for velocity in velocities_mps:
            if velocity <= 0:
                continue
            results.append(self.cost_of_transport(velocity))
        return results

    def route_b(self, segment_count: int) -> list[SegmentResult]:
        v_mr = self.maximum_range_speed()
        return [self.cost_of_transport(v_mr) for _ in range(segment_count)]

    def select_route(self, velocities_mps: Iterable[Optional[float]]) -> list[SegmentResult]:
        cleaned = [v for v in velocities_mps if v is not None and v > 0]
        if cleaned:
            return self.route_a(cleaned)
        return self.route_b(len(list(velocities_mps)))

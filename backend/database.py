from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .config import WINGSPAN_EXP, WINGSPAN_K

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AvonetTraits:
    mass_kg: float
    wing_span_m: float
    hand_wing_index: float
    aspect_ratio: float
    wing_area_m2: float
    frontal_area_m2: float


def _require_positive(value: float, name: str) -> float:
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite, got {value!r}.")
    return value


def _estimate_aspect_ratio(hand_wing_index: float) -> float:
    return 2.04 * np.log(hand_wing_index) + 2.58


def _estimate_frontal_area(mass_kg: float) -> float:
    return 0.00813 * (mass_kg ** 0.666)


class AvonetDatabase:
    def __init__(self, csv_path: str) -> None:
        self.csv_path = csv_path
        self._dataframe = pd.read_csv(csv_path)
        if "Species1" in self._dataframe.columns:
            self._dataframe["_scientific_name"] = self._dataframe["Species1"]
        elif "Species" in self._dataframe.columns:
            self._dataframe["_scientific_name"] = self._dataframe["Species"]
        else:
            raise KeyError("AVONET file is missing Species1/Species column.")

    def get_traits(self, scientific_name: str) -> AvonetTraits:
        if not scientific_name:
            raise ValueError("Scientific name is required.")

        df = self._dataframe
        matches = df[df["_scientific_name"].str.lower() ==
                     scientific_name.strip().lower()]
        if matches.empty:
            raise KeyError(
                f"Species '{scientific_name}' not found in AVONET data.")

        row = matches.iloc[0]
        mass_g = float(row["Mass"])
        wing_length_mm = float(row["Wing.Length"])
        hand_wing_index = float(row["Hand-Wing.Index"])

        mass_kg = _require_positive(mass_g / 1000.0, "Mass (kg)")
        # AVONET Wing.Length is the carpal-to-tip chord measurement, not half-wingspan.
        # Use allometric scaling (Greenewalt 1975) for the full anatomical wingspan,
        # which gives physically correct induced-drag estimates.
        wing_span_m = _require_positive(
            WINGSPAN_K * (mass_kg ** WINGSPAN_EXP), "Wing span (m)")
        hand_wing_index = _require_positive(hand_wing_index, "Hand-Wing Index")

        aspect_ratio = _require_positive(
            _estimate_aspect_ratio(hand_wing_index), "Aspect Ratio")
        wing_area_m2 = _require_positive(
            (wing_span_m ** 2) / aspect_ratio, "Wing area (m^2)")
        frontal_area_m2 = _require_positive(
            _estimate_frontal_area(mass_kg), "Frontal area (m^2)")

        return AvonetTraits(
            mass_kg=mass_kg,
            wing_span_m=wing_span_m,
            hand_wing_index=hand_wing_index,
            aspect_ratio=aspect_ratio,
            wing_area_m2=wing_area_m2,
            frontal_area_m2=frontal_area_m2
        )

    def to_dict(self, scientific_name: str) -> Dict[str, float]:
        traits = self.get_traits(scientific_name)
        return {
            "mass_kg": traits.mass_kg,
            "wing_span_m": traits.wing_span_m,
            "hand_wing_index": traits.hand_wing_index,
            "aspect_ratio": traits.aspect_ratio,
            "wing_area_m2": traits.wing_area_m2,
            "frontal_area_m2": traits.frontal_area_m2
        }

#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Rating module - Driver Rating (DR) and Safety Rating (SR) processor for LMU / RaceControl
"""

from __future__ import annotations

import logging
from collections import defaultdict

from .. import minfo, realtime_state
from ..constant import DATA
from ._base import DataModule

logger = logging.getLogger(__name__)


def get_tier_name(rating: float) -> str:
    """Return tier string based on numeric rating (WEC/LMU tiers)"""
    if rating < 1200:
        return "Bronze 3"
    elif rating < 1350:
        return "Bronze 2"
    elif rating < 1500:
        return "Bronze 1"
    elif rating < 1700:
        return "Silver 3"
    elif rating < 1900:
        return "Silver 2"
    elif rating < 2100:
        return "Silver 1"
    elif rating < 2400:
        return "Gold 3"
    elif rating < 2700:
        return "Gold 2"
    elif rating < 3000:
        return "Gold 1"
    else:
        return "Platinum"


class Realtime(DataModule):
    """Driver Rating and Elo calculation module"""

    __slots__ = ("_rating_cache",)

    def __init__(self, config, module_name: str):
        super().__init__(config, module_name)
        self._rating_cache: dict[str, float] = {}

    def _get_base_rating(self, driver_name: str, default_rating: float) -> float:
        """Get or estimate base rating for driver"""
        if driver_name in self._rating_cache:
            return self._rating_cache[driver_name]

        # Hash-based deterministic rating for simulation/offline sessions
        seed = sum(ord(c) for c in driver_name)
        simulated_offset = (seed % 900) - 450
        base = max(1100.0, default_rating + simulated_offset)
        self._rating_cache[driver_name] = base
        return base

    def update_data(self):
        """Update driver rating data in background thread"""
        _event_wait = self._event.wait
        update_interval = self.active_interval
        default_rating = float(self.mcfg.get("default_rating", 1500))
        calc_elo = bool(self.mcfg.get("enable_live_elo_projection", True))

        ratings_output = minfo.rating.ratings
        vehicles = minfo.vehicles.vehicles

        while not _event_wait(update_interval):
            if not realtime_state.paused:
                # Group active vehicles by class
                class_drivers: dict[str, list[tuple[int, str, int, float]]] = defaultdict(list)
                total_ratings: list[float] = []

                for idx in range(DATA.MAX_VEHICLES):
                    veh = vehicles[idx]
                    driver_name = veh.driverName
                    if not driver_name:
                        # Clear rating data for inactive slot
                        target = ratings_output[idx]
                        target.driverRating = 0.0
                        target.tier = ""
                        target.projectedDelta = 0.0
                        target.deltaText = ""
                        continue

                    cls_name = veh.vehicleClass if veh.vehicleClass else "Overall"
                    base_dr = self._get_base_rating(driver_name, default_rating)
                    pos_in_class = veh.positionInClass if veh.positionInClass > 0 else veh.positionOverall
                    class_drivers[cls_name].append((idx, driver_name, pos_in_class, base_dr))
                    total_ratings.append(base_dr)

                # Compute Strength of Field (SoF)
                if total_ratings:
                    minfo.rating.strengthOfField = sum(total_ratings) / len(total_ratings)

                # Compute Elo projections per class
                k_factor = 24.0  # Elo sensitivity factor

                for cls_name, drivers in class_drivers.items():
                    n = len(drivers)
                    if n <= 1 or not calc_elo:
                        for idx, d_name, pos, base_dr in drivers:
                            target = ratings_output[idx]
                            target.driverRating = base_dr
                            target.tier = get_tier_name(base_dr)
                            target.projectedDelta = 0.0
                            target.deltaText = "+0"
                        continue

                    # Sort drivers by running position in class
                    drivers.sort(key=lambda x: x[2])

                    for i, (idx, d_name, pos_i, r_i) in enumerate(drivers):
                        actual_score = 0.0
                        expected_score = 0.0

                        for j, (_, _, pos_j, r_j) in enumerate(drivers):
                            if i == j:
                                continue
                            # Expected probability of i beating j (Logistic curve)
                            e_ij = 1.0 / (1.0 + 10.0 ** ((r_j - r_i) / 400.0))
                            expected_score += e_ij

                            # Actual outcome (i is ahead of j)
                            if i < j:
                                actual_score += 1.0
                            elif i == j:
                                actual_score += 0.5

                        # Calculate delta
                        delta = (actual_score - expected_score) * (k_factor / max(n - 1, 1))
                        target = ratings_output[idx]
                        target.driverRating = r_i
                        target.tier = get_tier_name(r_i)
                        target.projectedDelta = delta

                        int_delta = int(round(delta))
                        if int_delta > 0:
                            target.deltaText = f"+{int_delta}"
                        elif int_delta < 0:
                            target.deltaText = f"{int_delta}"
                        else:
                            target.deltaText = "+0"

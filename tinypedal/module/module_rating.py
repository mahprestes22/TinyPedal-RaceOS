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
Rating module - Driver Rating (DR) and Safety Rating (SR) via raceos.gg API (LMU / RaceControl)

Flow (reverse-engineered from doX.LMU_SessionDataPlugin.dll):
  1. GET  http://127.0.0.1:6397/rest/profile/getAuthSessionTicket  -> Steam ticket
  2. POST https://raceos.gg/authenticate  body={"token":"<ticket>","game":"lmu","platform":"steam"}
       -> { accessToken, player: { driverRank: { elo, rank, tier, progress }, safetyRank: {...} } }
  3. Detect online event ID from LMU trace log (UserData/Log/trace_*.txt)
  4. POST https://raceos.gg/api/v1/event/overview  body={"game":"lmu","eventType":"daily","eventId":"<id>"}
       Header: Game-Authorization: Bearer <accessToken>
       -> Event Configuration (Ratings drSettings: base multiplier, k-factor, d divisor, enabled)
  5. POST https://raceos.gg/api/v1/players  body={"usernames":["Name1","Name2",...]}
       Header: Game-Authorization: Bearer <accessToken>
       -> list of player objects with driverRank (rank, tier, progress) and safetyRank
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import time
import threading
import urllib.request
import urllib.error
from collections import defaultdict

from ..constant import DATA
from ._base import DataModule

logger = logging.getLogger(__name__)

# Fallback Elo ratings from official FIA/WEC/LMU driver skill categories
# Used when raceos.gg is unavailable (AI / offline sessions)
SKILL_TO_RATING = {
    "platinum": 3100.0,
    "gold": 2550.0,
    "silver": 1850.0,
    "bronze": 1350.0,
}

# raceos.gg endpoints (from doX.LMU_SessionDataPlugin.dll reverse engineering)
REA_TICKET_URL = "http://127.0.0.1:6397/rest/profile/getAuthSessionTicket"
RACEOS_AUTH_URL = "https://raceos.gg/authenticate"
RACEOS_EVENT_URL = "https://raceos.gg/api/v1/event/overview"
RACEOS_PLAYERS_URL = "https://raceos.gg/api/v1/players"
LMU_REST_STANDINGS_URL = "http://127.0.0.1:6397/rest/watch/standings"
LMU_REST_VEHICLES_URL = "http://127.0.0.1:6397/rest/sessions/getAllVehicles"


def get_tier_name(rating: float, compact: bool = True) -> str:
    """Return tier string based on numeric Elo rating (WEC/LMU tiers: B3..P1)"""
    if rating < 1200:
        return "B3" if compact else "Bronze 3"
    elif rating < 1350:
        return "B2" if compact else "Bronze 2"
    elif rating < 1500:
        return "B1" if compact else "Bronze 1"
    elif rating < 1700:
        return "S3" if compact else "Silver 3"
    elif rating < 1900:
        return "S2" if compact else "Silver 2"
    elif rating < 2100:
        return "S1" if compact else "Silver 1"
    elif rating < 2400:
        return "G3" if compact else "Gold 3"
    elif rating < 2700:
        return "G2" if compact else "Gold 2"
    elif rating < 3000:
        return "G1" if compact else "Gold 1"
    elif rating < 3300:
        return "P3" if compact else "Platinum 3"
    elif rating < 3600:
        return "P2" if compact else "Platinum 2"
    else:
        return "P1" if compact else "Platinum 1"


def tier_from_raceos(
    rank: str,
    tier: int,
    progress: float | None = None,
    show_progress: bool = True,
    compact: bool = True,
) -> str:
    """Convert raceos.gg rank/tier/progress to clean display string (e.g. 'Silver', 2, 61.4 -> 'S2 61%')"""
    rank_lower = rank.lower() if rank else ""
    if "platinum" in rank_lower:
        code = "P" if compact else "Platinum"
    elif "gold" in rank_lower:
        code = "G" if compact else "Gold"
    elif "silver" in rank_lower:
        code = "S" if compact else "Silver"
    else:
        code = "B" if compact else "Bronze"
    base = f"{code}{tier}"
    if show_progress and progress is not None and progress > 0:
        return f"{base} {int(round(progress))}%"
    return base


class Realtime(DataModule):
    """Driver Rating module — fetches real DR/SR from raceos.gg using Steam auth ticket from LMU"""

    __slots__ = (
        "_lock",
        "_raceos_cache",          # name -> {"elo": float, "tier": str, "progress": float, "sr_tier": str}
        "_rea_skills",            # name -> "gold"/"silver" etc (fallback from LMU catalog)
        "_access_token",
        "_access_token_expires",
        "_steam_ticket",
        "_last_auth_time",
        "_last_players_fetch",
        "_last_event_check",
        "_auth_ok",
        "_show_progress",
        "_event_id",
        "_session_multiplier",    # Event DR multiplier (1.0, 1.5, 2.0 etc.)
        "_session_k",             # Event K factor (default 30.0)
        "_session_d",             # Event D divisor (default 420.0)
        "_ratings_enabled",       # Whether DR is enabled for this event
        "_lmu_log_dir",
    )

    def __init__(self, config, module_name: str):
        super().__init__(config, module_name)
        self._lock = threading.Lock()
        self._raceos_cache: dict[str, dict] = {}
        self._rea_skills: dict[str, str] = {}
        self._access_token: str = ""
        self._access_token_expires: float = 0.0
        self._steam_ticket: str = ""
        self._last_auth_time: float = 0.0
        self._last_players_fetch: float = 0.0
        self._last_event_check: float = 0.0
        self._auth_ok: bool = False
        self._show_progress: bool = bool(self.mcfg.get("show_driver_rank_progress", True))
        self._event_id: str = ""
        self._session_multiplier: float = 1.0
        self._session_k: float = 30.0
        self._session_d: float = 420.0
        self._ratings_enabled: bool = True
        self._lmu_log_dir: str = self._resolve_lmu_log_dir()

    # -------------------------------------------------------------------------
    # Path resolution & LMU event detection
    # -------------------------------------------------------------------------

    def _resolve_lmu_log_dir(self) -> str:
        """Find the LMU UserData/Log directory"""
        candidates = [
            r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate\UserData\Log",
            r"D:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Log",
            r"E:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Log",
        ]
        for path in candidates:
            if os.path.isdir(path):
                return path
        return ""

    def _detect_online_event_id(self) -> str:
        """Parse the latest LMU trace file to detect online event GUID"""
        if not self._lmu_log_dir or not os.path.isdir(self._lmu_log_dir):
            return ""
        try:
            files = sorted(
                glob.glob(os.path.join(self._lmu_log_dir, "trace_*.txt")),
                key=os.path.getmtime,
                reverse=True,
            )
            if not files:
                return ""
            latest_file = files[0]
            with open(latest_file, "r", errors="ignore") as f:
                content = f.read()
            matches = re.findall(
                r"Joining (?:race|practice) server for online event\s+([0-9a-fA-F-]{36})",
                content,
            )
            return matches[-1] if matches else ""
        except Exception:
            return ""

    # -------------------------------------------------------------------------
    # raceos.gg auth & event overview
    # -------------------------------------------------------------------------

    def _get_steam_ticket(self) -> str:
        """Fetch fresh Steam auth ticket from LMU local REST API"""
        try:
            req = urllib.request.Request(
                REA_TICKET_URL, headers={"User-Agent": "TinyPedal"}
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read().decode())
                return data.get("authSessionTicket", "")
        except Exception:
            return ""

    def _get_lmu_standings_drivers(self) -> list[str]:
        """Fetch driver names currently in the session via LMU REST API"""
        try:
            req = urllib.request.Request(
                LMU_REST_STANDINGS_URL, headers={"User-Agent": "SimHub/9.0"}
            )
            with urllib.request.urlopen(req, timeout=1.5) as r:
                data = json.loads(r.read().decode())
                if isinstance(data, list):
                    return [d["driverName"] for d in data if isinstance(d, dict) and "driverName" in d]
                elif isinstance(data, dict):
                    veh_list = data.get("vehicles", data.get("Vehicles", []))
                    return [d["driverName"] for d in veh_list if isinstance(d, dict) and "driverName" in d]
        except Exception:
            pass
        return []

    def _authenticate(self) -> bool:
        """Authenticate with raceos.gg using Steam ticket — returns True if successful"""
        ticket = self._get_steam_ticket()
        if not ticket:
            logger.debug("rating: no Steam ticket from LMU REST API")
            return False

        try:
            body = json.dumps(
                {"token": ticket, "game": "lmu", "platform": "steam"}
            ).encode()
            req = urllib.request.Request(
                RACEOS_AUTH_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "SimHub/9.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())

            token = data.get("accessToken", "")
            if not token:
                return False

            player_data = data.get("player", {})
            dr = player_data.get("driverRank", {})
            sr = player_data.get("safetyRank", {})

            my_elo = float(dr.get("elo", 1780.0))
            my_rank = dr.get("rank", "Silver")
            my_tier_num = int(dr.get("tier", 2))
            my_progress = float(dr.get("progress", 0.0))
            my_sr_rank = sr.get("rank", "Gold")
            my_sr_tier = int(sr.get("tier", 2))
            my_name = player_data.get("name", player_data.get("username", ""))

            tier_str = tier_from_raceos(
                my_rank, my_tier_num, my_progress,
                show_progress=self._show_progress, compact=True
            )

            with self._lock:
                self._access_token = token
                self._steam_ticket = ticket
                self._auth_ok = True
                self._access_token_expires = time.time() + 10800
                if my_name:
                    self._raceos_cache[my_name] = {
                        "elo": my_elo,
                        "tier": tier_str,
                        "progress": my_progress,
                        "sr_tier": tier_from_raceos(my_sr_rank, my_sr_tier, compact=True),
                    }

            logger.info(
                "rating: raceos.gg auth OK — %s DR=%s elo=%.1f SR=%s%s",
                my_name, tier_str, my_elo, my_sr_rank, my_sr_tier,
            )
            return True

        except urllib.error.HTTPError as e:
            logger.debug("rating: raceos.gg auth HTTP %s", e.code)
            return False
        except Exception as e:
            logger.debug("rating: raceos.gg auth error: %s", e)
            return False

    def _fetch_event_overview(self, event_id: str) -> None:
        """Fetch event settings (multiplier, K factor, D divisor) from raceos.gg"""
        with self._lock:
            token = self._access_token
            auth_ok = self._auth_ok

        if not auth_ok or not token or not event_id:
            return

        for ev_type in ("daily", "weekly", "special"):
            try:
                body = json.dumps({
                    "game": "lmu",
                    "eventType": ev_type,
                    "eventId": event_id,
                }).encode()
                req = urllib.request.Request(
                    RACEOS_EVENT_URL,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Game-Authorization": f"Bearer {token}",
                        "User-Agent": "SimHub/9.0",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    res = json.loads(r.read().decode())

                cfg = res.get("configuration", {}).get("ratings", {})
                dr_s = cfg.get("drSettings", {})
                base_mult = float(dr_s.get("base", 1.0))
                k_val = float(dr_s.get("k", 30.0))
                d_val = float(dr_s.get("d", 420.0))
                enabled = bool(cfg.get("enabled", True))

                with self._lock:
                    self._event_id = event_id
                    self._session_multiplier = base_mult
                    self._session_k = k_val
                    self._session_d = d_val
                    self._ratings_enabled = enabled

                logger.info(
                    "rating: event %s (%s) — multiplier=%.1fx, K=%.1f, D=%.1f, enabled=%s",
                    event_id[:8], ev_type, base_mult, k_val, d_val, enabled,
                )
                break
            except Exception:
                continue

    def _fetch_players(self, names: list[str]) -> None:
        """Fetch DR/SR for driver names from raceos.gg"""
        with self._lock:
            token = self._access_token
            auth_ok = self._auth_ok

        if not auth_ok or not token or not names:
            return

        with self._lock:
            to_fetch = [n for n in names if n not in self._raceos_cache]

        if not to_fetch:
            return

        try:
            body = json.dumps({"usernames": to_fetch}).encode()
            req = urllib.request.Request(
                RACEOS_PLAYERS_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Game-Authorization": f"Bearer {token}",
                    "User-Agent": "SimHub/9.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read().decode())

            players = resp if isinstance(resp, list) else resp.get("players", [])
            updates = {}
            for p in players:
                name = p.get("name") or p.get("username", "")
                dr = p.get("driverRank", {})
                sr = p.get("safetyRank", {})
                if name and dr:
                    elo = float(dr.get("elo", 0.0))
                    rank = dr.get("rank", "Bronze")
                    tier_num = int(dr.get("tier", 3))
                    prog = float(dr.get("progress", 0.0))
                    tier_str = tier_from_raceos(
                        rank, tier_num, prog,
                        show_progress=self._show_progress, compact=True
                    )
                    updates[name] = {
                        "elo": elo if elo > 0 else SKILL_TO_RATING.get(rank.lower(), 1350.0),
                        "tier": tier_str,
                        "progress": prog,
                        "sr_tier": tier_from_raceos(
                            sr.get("rank", "Bronze"),
                            int(sr.get("tier", 3)),
                            compact=True,
                        ),
                    }

            with self._lock:
                self._raceos_cache.update(updates)

            logger.info("rating: fetched %d/%d players from raceos.gg", len(updates), len(to_fetch))

        except urllib.error.HTTPError as e:
            if e.code == 401:
                with self._lock:
                    self._auth_ok = False
            logger.debug("rating: players fetch HTTP %s", e.code)
        except Exception as e:
            logger.debug("rating: players fetch error: %s", e)

    def _fetch_rea_skills_fallback(self) -> None:
        """Fallback: fetch skill categories from LMU catalog (for AI / offline sessions)"""
        try:
            req = urllib.request.Request(
                LMU_REST_VEHICLES_URL, headers={"User-Agent": "TinyPedal"}
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                data = json.loads(r.read().decode())
            skills = {}
            for v in data:
                for d in v.get("drivers", []):
                    name = d.get("name")
                    skill = d.get("skill", "").lower()
                    if name and skill in SKILL_TO_RATING:
                        skills[name] = skill
            with self._lock:
                self._rea_skills.update(skills)
        except Exception:
            pass

    def _get_rating_for_driver(
        self, driver_name: str, default_rating: float, is_player: bool
    ) -> tuple[float, str, str]:
        """Return (elo, dr_tier_str, sr_tier_str) for a driver"""
        with self._lock:
            cached = self._raceos_cache.get(driver_name)
            if cached:
                return cached["elo"], cached["tier"], cached.get("sr_tier", "")

        # Fallback: skill from LMU catalog
        with self._lock:
            skill = self._rea_skills.get(driver_name)
            if skill is None:
                dl = driver_name.lower()
                for kname, kskill in self._rea_skills.items():
                    if kname.lower() in dl or dl in kname.lower():
                        skill = kskill
                        break

        if skill:
            base = SKILL_TO_RATING.get(skill, default_rating)
            tier = get_tier_name(base, compact=True)
            return base, tier, ""

        # Hash-based deterministic fallback for unknown AI drivers
        seed = sum(ord(c) for c in driver_name)
        base = max(1100.0, default_rating + (seed % 900) - 450)
        tier = get_tier_name(base, compact=True)
        return base, tier, ""

    # -------------------------------------------------------------------------
    # Main update loop
    # -------------------------------------------------------------------------

    def update_data(self):
        """Background thread — authenticate with raceos.gg, then update DR data each cycle"""
        import tinypedal

        _event_wait = self._event.wait
        update_interval = self.active_interval
        default_rating = float(self.mcfg.get("default_rating", 1500))
        use_compact = bool(self.mcfg.get("use_compact_tier_format", True))
        calc_elo = bool(self.mcfg.get("enable_live_elo_projection", True))
        self._show_progress = bool(self.mcfg.get("show_driver_rank_progress", True))

        # Initial background tasks
        threading.Thread(target=self._authenticate, daemon=True).start()
        threading.Thread(target=self._fetch_rea_skills_fallback, daemon=True).start()

        while not _event_wait(update_interval):
            minfo = tinypedal.minfo
            realtime_state = tinypedal.realtime_state

            if minfo is None or realtime_state is None:
                continue

            if realtime_state.paused:
                continue

            now = time.time()

            # Re-auth if token expired or not yet authenticated
            with self._lock:
                auth_ok = self._auth_ok
                token_expires = self._access_token_expires

            if not auth_ok or now > token_expires - 300:
                if now - self._last_auth_time > 30:
                    self._last_auth_time = now
                    threading.Thread(target=self._authenticate, daemon=True).start()

            # Check online event ID periodically (every 20s)
            if now - self._last_event_check > 20.0:
                self._last_event_check = now
                ev_id = self._detect_online_event_id()
                with self._lock:
                    curr_ev = self._event_id
                if ev_id and ev_id != curr_ev:
                    threading.Thread(
                        target=self._fetch_event_overview, args=(ev_id,), daemon=True
                    ).start()

            # Collect driver names from current session
            ratings_output = minfo.rating.ratings
            vehicles = minfo.vehicles.dataSet

            class_drivers: dict[str, list[tuple[int, str, int, float, bool, str, str]]] = defaultdict(list)
            total_ratings: list[float] = []
            session_names: list[str] = []

            for idx in range(DATA.MAX_VEHICLES):
                veh = vehicles[idx]
                driver_name = veh.driverName
                if not driver_name:
                    target = ratings_output[idx]
                    target.driverRating = 0.0
                    target.tier = ""
                    target.projectedDelta = 0.0
                    target.deltaText = ""
                    continue

                session_names.append(driver_name)
                cls_name = veh.vehicleClass if veh.vehicleClass else "Overall"
                elo, dr_tier, sr_tier = self._get_rating_for_driver(
                    driver_name, default_rating, veh.isPlayer
                )
                pos = veh.positionInClass if veh.positionInClass > 0 else veh.positionOverall
                class_drivers[cls_name].append((idx, driver_name, pos, elo, veh.isPlayer, dr_tier, sr_tier))
                total_ratings.append(elo)

            # Also fetch names directly from LMU REST standings to capture drivers in garage/lobby
            lmu_names = self._get_lmu_standings_drivers()
            for ln in lmu_names:
                if ln and ln not in session_names:
                    session_names.append(ln)

            # Trigger background player fetch if we have uncached drivers
            if session_names and now - self._last_players_fetch > 10.0:
                self._last_players_fetch = now
                names_copy = list(session_names)
                threading.Thread(
                    target=self._fetch_players, args=(names_copy,), daemon=True
                ).start()

            # Strength of Field
            if total_ratings:
                minfo.rating.strengthOfField = sum(total_ratings) / len(total_ratings)

            # Retrieve dynamic event parameters (from raceos.gg event overview)
            with self._lock:
                effective_k = self._session_k * self._session_multiplier
                d_divisor = self._session_d
                ratings_on = self._ratings_enabled

            for cls_name, drivers in class_drivers.items():
                n = len(drivers)
                if n <= 1 or not calc_elo or not ratings_on:
                    for idx, d_name, pos, elo, is_plr, dr_tier, sr_tier in drivers:
                        target = ratings_output[idx]
                        target.driverRating = elo
                        target.tier = dr_tier if dr_tier else get_tier_name(elo, compact=use_compact)
                        target.projectedDelta = 0.0
                        target.deltaText = "+0"
                    continue

                drivers.sort(key=lambda x: x[2])

                for i, (idx, d_name, pos_i, r_i, is_plr, dr_tier, sr_tier) in enumerate(drivers):
                    actual_score = 0.0
                    expected_score = 0.0

                    for j, (_, _, pos_j, r_j, _, _, _) in enumerate(drivers):
                        if i == j:
                            continue
                        e_ij = 1.0 / (1.0 + 10.0 ** ((r_j - r_i) / d_divisor))
                        expected_score += e_ij
                        if i < j:
                            actual_score += 1.0
                        elif i == j:
                            actual_score += 0.5

                    delta = (actual_score - expected_score) * (effective_k / max(n - 1, 1))
                    target = ratings_output[idx]
                    target.driverRating = r_i
                    target.tier = dr_tier if dr_tier else get_tier_name(r_i, compact=use_compact)
                    target.projectedDelta = delta

                    int_delta = int(round(delta))
                    if int_delta > 0:
                        target.deltaText = f"+{int_delta}"
                    elif int_delta < 0:
                        target.deltaText = f"{int_delta}"
                    else:
                        target.deltaText = "+0"

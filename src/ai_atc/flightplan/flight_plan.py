from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
logger = logging.getLogger(__name__)
@dataclass
class Waypoint:
    name: str
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_ft: int = 0
    speed_kts: int = 0
    is_sid: bool = False
    is_star: bool = False
    passed: bool = False
@dataclass
class FlightPlan:
    callsign: str = "N12345"
    aircraft_type: str = "B738"
    origin_icao: str = ""
    destination_icao: str = ""
    departure_runway: str = ""
    arrival_runway: str = ""
    sid_name: str = ""
    star_name: str = ""
    approach_type: str = ""
    cruise_altitude_ft: int = 35000
    route_string: str = ""
    waypoints: list[Waypoint] = field(default_factory=list)
    departure_gate: str = ""
    arrival_gate: str = ""
    squawk: int = 0
    @property
    def current_waypoint_index(self) -> int:
        for i, wp in enumerate(self.waypoints):
            if not wp.passed:
                return i
        return len(self.waypoints)
    @property
    def current_waypoint(self) -> Waypoint | None:
        idx = self.current_waypoint_index
        if idx < len(self.waypoints):
            return self.waypoints[idx]
        return None
    @property
    def next_waypoint(self) -> Waypoint | None:
        idx = self.current_waypoint_index + 1
        if idx < len(self.waypoints):
            return self.waypoints[idx]
        return None
    @property
    def progress_percent(self) -> float:
        if not self.waypoints:
            return 0.0
        passed = sum(1 for wp in self.waypoints if wp.passed)
        return (passed / len(self.waypoints)) * 100
    @property
    def remaining_waypoints(self) -> list[Waypoint]:
        return [wp for wp in self.waypoints if not wp.passed]
    def mark_waypoint_passed(self, index: int) -> None:
        if 0 <= index < len(self.waypoints):
            self.waypoints[index].passed = True
    @property
    def airline_callsign(self) -> str:
        return self.callsign.upper()
def load_flight_plan(path: str | Path) -> FlightPlan:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    fp = FlightPlan(
        callsign=data.get("callsign", "N12345"),
        aircraft_type=data.get("aircraft_type", "B738"),
        origin_icao=data.get("origin", ""),
        destination_icao=data.get("destination", ""),
        departure_runway=data.get("departure_runway", ""),
        arrival_runway=data.get("arrival_runway", ""),
        sid_name=data.get("sid", ""),
        star_name=data.get("star", ""),
        approach_type=data.get("approach_type", "ILS"),
        cruise_altitude_ft=data.get("cruise_altitude", 35000),
        route_string=data.get("route", ""),
        departure_gate=data.get("departure_gate", ""),
        arrival_gate=data.get("arrival_gate", ""),
    )
    for wp_data in data.get("waypoints", []):
        wp = Waypoint(
            name=wp_data.get("name", ""),
            latitude=wp_data.get("lat", 0.0),
            longitude=wp_data.get("lon", 0.0),
            altitude_ft=wp_data.get("altitude", 0),
            speed_kts=wp_data.get("speed", 0),
        )
        fp.waypoints.append(wp)
    logger.info(
        "Loaded flight plan: %s %s -> %s (%d waypoints)",
        fp.callsign,
        fp.origin_icao,
        fp.destination_icao,
        len(fp.waypoints),
    )
    return fp
def create_sample_flight_plan() -> dict:
    return {
        "callsign": "BAW123",
        "aircraft_type": "B777",
        "origin": "KJFK",
        "destination": "EGLL",
        "departure_runway": "",
        "arrival_runway": "",
        "sid": "SKORR3",
        "star": "",
        "approach_type": "ILS",
        "cruise_altitude": 38000,
        "route": "SKORR DCT WHALE N57A ALLRY",
        "departure_gate": "A1",
        "arrival_gate": "",
        "waypoints": [
            {"name": "SKORR", "lat": 40.65, "lon": -73.80, "altitude": 5000},
            {"name": "WHALE", "lat": 41.20, "lon": -72.10},
            {"name": "ALLRY", "lat": 42.50, "lon": -70.00},
        ],
    }
def fetch_from_simbrief(username: str) -> FlightPlan | None:
    import httpx
    url = f"https://www.simbrief.com/api/xml.fetcher.php?username={username}&json=1"
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        general = data.get("general", {})
        origin = data.get("origin", {})
        destination = data.get("destination", {})
        callsign = f"{general.get('icao_airline', '')}{general.get('flight_number', '')}"
        fp = FlightPlan(
            callsign=callsign,
            aircraft_type=data.get("aircraft", {}).get("icaocode", "B738"),
            origin_icao=origin.get("icao_code", ""),
            destination_icao=destination.get("icao_code", ""),
            departure_runway=origin.get("plan_rwy", ""),
            arrival_runway=destination.get("plan_rwy", ""),
            cruise_altitude_ft=int(general.get("initial_alt", 35000)),
            route_string=general.get("route", ""),
        )
        logger.info(
            "Successfully loaded SimBrief plan: %s (%s -> %s)",
            fp.callsign,
            fp.origin_icao,
            fp.destination_icao,
        )
        return fp
    except Exception as e:
        logger.error("Failed to parse SimBrief plan: %s", e)
        return None
from __future__ import annotations
import logging
import math
from dataclasses import dataclass, field
from ai_atc.xplane.connection import XPlaneConnection
logger = logging.getLogger(__name__)
DREFS = {
    "latitude": "sim/flightmodel/position/latitude",
    "longitude": "sim/flightmodel/position/longitude",
    "elevation_m": "sim/flightmodel/position/elevation",
    "heading_true": "sim/flightmodel/position/psi",
    "heading_mag": "sim/flightmodel/position/mag_psi",
    "groundspeed_ms": "sim/flightmodel/position/groundspeed",
    "airspeed_kts": "sim/flightmodel/position/indicated_airspeed",
    "altitude_ft_msl": "sim/cockpit2/gauges/indicators/altitude_ft_pilot",
    "vertical_speed_fpm": "sim/cockpit2/gauges/indicators/vvi_fpm_pilot",
    "on_ground": "sim/flightmodel/failures/onground_any",
    "gear_deploy": "sim/aircraft/parts/acf_gear_deploy",
    "flap_ratio": "sim/cockpit2/controls/flap_ratio",
    "parking_brake": "sim/cockpit2/controls/parking_brake_ratio",
    "transponder_code": "sim/cockpit/radios/transponder_code",
    "nav1_freq": "sim/cockpit/radios/nav1_freq_hz",
    "com1_freq": "sim/cockpit2/radios/actuators/com1_frequency_hz",
    "com2_freq": "sim/cockpit2/radios/actuators/com2_frequency_hz",
    "com_selection": "sim/cockpit2/radios/actuators/com_selection",
    "engine_running": "sim/flightmodel/engine/ENGN_running",
    "throttle": "sim/cockpit2/engine/actuators/throttle_ratio_all",
}
@dataclass
class AircraftState:
    latitude: float = 0.0
    longitude: float = 0.0
    elevation_m: float = 0.0
    altitude_ft_msl: float = 0.0
    heading_true: float = 0.0
    heading_mag: float = 0.0
    groundspeed_ms: float = 0.0
    airspeed_kts: float = 0.0
    vertical_speed_fpm: float = 0.0
    on_ground: bool = True
    gear_deploy: float = 1.0
    flap_ratio: float = 0.0
    parking_brake: float = 1.0
    transponder_code: int = 1200
    engine_running: float = 0.0
    throttle: float = 0.0
    nav1_freq: int = 0
    com1_freq: int = 0
    com2_freq: int = 0
    com_selection: int = 0
    @property
    def groundspeed_kts(self) -> float:
        return self.groundspeed_ms * 1.94384
    @property
    def altitude_ft(self) -> float:
        return self.altitude_ft_msl
    @property
    def elevation_ft(self) -> float:
        return self.elevation_m * 3.28084
    @property
    def is_moving(self) -> bool:
        return self.groundspeed_kts > 2.0
    @property
    def is_airborne(self) -> bool:
        return not self.on_ground
    @property
    def is_fast(self) -> bool:
        return self.groundspeed_kts > 50.0
    @property
    def gear_is_down(self) -> bool:
        return self.gear_deploy > 0.5
    @property
    def engines_running(self) -> bool:
        return self.engine_running > 0.5
    @property
    def parking_brake_set(self) -> bool:
        return self.parking_brake > 0.5
    def distance_to(self, lat: float, lon: float) -> float:
        r_nm = 3440.065
        lat1 = math.radians(self.latitude)
        lat2 = math.radians(lat)
        dlat = lat2 - lat1
        dlon = math.radians(lon - self.longitude)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 2 * r_nm * math.asin(math.sqrt(a))
    def bearing_to(self, lat: float, lon: float) -> float:
        lat1 = math.radians(self.latitude)
        lat2 = math.radians(lat)
        dlon = math.radians(lon - self.longitude)
        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return (math.degrees(math.atan2(x, y)) + 360) % 360
class AircraftStateManager:
    def __init__(self, connection: XPlaneConnection, freq_hz: int = 5) -> None:
        self.connection = connection
        self.freq_hz = freq_hz
        self.state = AircraftState()
        self._sub_indices: dict[str, int] = {}
    def start(self) -> None:
        for name, dref in DREFS.items():
            idx = self.connection.subscribe(dref, freq_hz=self.freq_hz, callback=None)
            self._sub_indices[name] = idx
        logger.info("Aircraft state manager started (%d datarefs).", len(DREFS))
    def stop(self) -> None:
        for idx in self._sub_indices.values():
            self.connection.unsubscribe(idx)
        self._sub_indices.clear()
    def update(self) -> AircraftState:
        for name, idx in self._sub_indices.items():
            value = self.connection.get_value(idx)
            if name == "on_ground":
                self.state.on_ground = value > 0.5
            elif name == "transponder_code":
                self.state.transponder_code = int(value)
            elif name == "nav1_freq":
                self.state.nav1_freq = int(value)
            elif name == "com1_freq":
                self.state.com1_freq = int(value)
            elif name == "com2_freq":
                self.state.com2_freq = int(value)
            elif name == "com_selection":
                self.state.com_selection = int(value)
            else:
                setattr(self.state, name, value)
        return self.state
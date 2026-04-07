from __future__ import annotations
import logging
import asyncio
from dataclasses import dataclass
logger = logging.getLogger(__name__)
@dataclass
class WindInfo:
    direction: int = 0
    speed: int = 0
    gust: int = 0
    variable: bool = False
    variable_from: int = 0
    variable_to: int = 0
    @property
    def calm(self) -> bool:
        return self.speed < 3
    def __str__(self) -> str:
        if self.calm:
            return "calm"
        s = f"{self.direction:03d} at {self.speed}"
        if self.gust:
            s += f" gusting {self.gust}"
        return s
@dataclass
class MetarData:
    raw: str = ""
    station: str = ""
    wind: WindInfo | None = None
    visibility_sm: float = 10.0
    ceiling_ft: int | None = None
    temperature_c: int = 15
    dewpoint_c: int = 10
    altimeter_inhg: float = 29.92
    flight_rules: str = "VFR"
ATIS_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
class MetarService:
    def __init__(self) -> None:
        self._current: MetarData | None = None
        self._atis_index = 0
    @property
    def current(self) -> MetarData | None:
        return self._current
    @property
    def atis_letter(self) -> str:
        return ATIS_LETTERS[self._atis_index % 26]
    async def fetch(self, icao: str) -> MetarData:
        try:
            import avwx
            metar = avwx.Metar(icao)
            success = await asyncio.to_thread(metar.update)
            if success and metar.data:
                data = MetarData(
                    raw=metar.raw or "",
                    station=icao,
                    flight_rules=str(metar.data.flight_rules) if metar.data.flight_rules else "VFR",
                )
                if metar.data.wind_direction:
                    wind = WindInfo()
                    try:
                        wind.direction = int(metar.data.wind_direction.repr or "0")
                    except (ValueError, TypeError):
                        wind.variable = True
                    if metar.data.wind_speed:
                        wind.speed = int(metar.data.wind_speed.repr or "0")
                    if metar.data.wind_gust:
                        wind.gust = int(metar.data.wind_gust.repr or "0")
                    data.wind = wind
                if metar.data.visibility:
                    try:
                        data.visibility_sm = float(metar.data.visibility.repr or "10")
                    except (ValueError, TypeError):
                        data.visibility_sm = 10.0
                if metar.data.clouds:
                    for cloud in metar.data.clouds:
                        alt_cand = getattr(cloud, "altitude", getattr(cloud, "base", None))
                        if cloud.type in ("BKN", "OVC") and alt_cand:
                            alt = int(alt_cand) * 100
                            if data.ceiling_ft is None or alt < data.ceiling_ft:
                                data.ceiling_ft = alt
                if metar.data.temperature:
                    try:
                        data.temperature_c = int(metar.data.temperature.repr or "15")
                    except (ValueError, TypeError):
                        pass
                if metar.data.dewpoint:
                    try:
                        data.dewpoint_c = int(metar.data.dewpoint.repr or "10")
                    except (ValueError, TypeError):
                        pass
                if metar.data.altimeter:
                    try:
                        data.altimeter_inhg = float(metar.data.altimeter.repr or "29.92")
                    except (ValueError, TypeError):
                        pass
                self._current = data
                self._atis_index += 1
                logger.info("METAR for %s: %s", icao, data.raw)
                return data
        except ImportError:
            logger.warning("avwx-engine not installed. Using default weather.")
        except Exception:
            logger.exception("Failed to fetch METAR for %s", icao)
        fallback = MetarData(
            raw=f"{icao} 000000Z 00000KT 9999 FEW040 15/10 A2992",
            station=icao,
            wind=WindInfo(direction=0, speed=0),
            flight_rules="VFR",
        )
        self._current = fallback
        return fallback
    def determine_active_runway(self, runways: list[tuple[str, float]]) -> str:
        if not self._current or not self._current.wind or self._current.wind.calm:
            return runways[0][0] if runways else "01"
        wind_dir = self._current.wind.direction
        best_runway = runways[0][0]
        best_headwind = -999.0
        for name, heading in runways:
            import math
            diff = math.radians(wind_dir - heading)
            headwind = self._current.wind.speed * math.cos(diff)
            if headwind > best_headwind:
                best_headwind = headwind
                best_runway = name
        return best_runway
    def generate_atis(self, airport_name: str, active_runway: str) -> str:
        d = self._current
        if not d:
            return "ATIS information not available."
        lines = [f"{airport_name} information {self.atis_letter}."]
        if d.wind:
            lines.append(f"Wind {d.wind}.")
        lines.append(f"Visibility {d.visibility_sm} statute miles.")
        if d.ceiling_ft:
            lines.append(f"Ceiling {d.ceiling_ft} feet.")
        lines.append(f"Temperature {d.temperature_c}, dewpoint {d.dewpoint_c}.")
        lines.append(f"Altimeter {d.altimeter_inhg:.2f}.")
        lines.append(f"Landing and departing runway {active_runway}.")
        lines.append(f"Advise on initial contact you have information {self.atis_letter}.")
        return " ".join(lines)
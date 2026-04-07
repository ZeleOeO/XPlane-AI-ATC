from __future__ import annotations
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
logger = logging.getLogger(__name__)
ATC_ROW_CODES = {
    "50": "ATIS",
    "51": "UNICOM",
    "52": "DELIVERY",
    "53": "GROUND",
    "54": "TOWER",
    "55": "APPROACH",
    "56": "DEPARTURE",
}
@dataclass
class ATCFrequency:
    facility: str
    name: str
    freq_hz: int
    @property
    def freq_mhz(self) -> float:
        return self.freq_hz / 100.0
    @property
    def freq_str(self) -> str:
        mhz = self.freq_hz / 100.0
        return f"{mhz:.3f}"
@dataclass
class RunwayEnd:
    name: str
    latitude: float
    longitude: float
    heading: float
    @property
    def heading_int(self) -> int:
        return round(self.heading) % 360
@dataclass
class Runway:
    width_m: float
    surface: int
    end1: RunwayEnd
    end2: RunwayEnd
@dataclass
class TaxiwayNode:
    index: int
    latitude: float
    longitude: float
    usage: str
    name: str = ""
    def distance_to(self, other: TaxiwayNode) -> float:
        r = 6371000
        lat1, lat2 = math.radians(self.latitude), math.radians(other.latitude)
        dlat = lat2 - lat1
        dlon = math.radians(other.longitude - self.longitude)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 2 * r * math.asin(math.sqrt(a))
@dataclass
class TaxiwayEdge:
    node1_idx: int
    node2_idx: int
    oneway: bool
    runway_crossing: bool
    name: str = ""
@dataclass
class Airport:
    icao: str
    name: str
    elevation_ft: int
    latitude: float = 0.0
    longitude: float = 0.0
    runways: list[Runway] = field(default_factory=list)
    taxiway_nodes: dict[int, TaxiwayNode] = field(default_factory=dict)
    taxiway_edges: list[TaxiwayEdge] = field(default_factory=list)
    frequencies: list[ATCFrequency] = field(default_factory=list)
    def get_runway_pairs(self) -> list[tuple[str, float]]:
        pairs = []
        for rwy in self.runways:
            pairs.append((rwy.end1.name, rwy.end1.heading))
            pairs.append((rwy.end2.name, rwy.end2.heading))
        return pairs
    def get_runway_end(self, name: str) -> RunwayEnd | None:
        for rwy in self.runways:
            if rwy.end1.name == name:
                return rwy.end1
            if rwy.end2.name == name:
                return rwy.end2
        return None
    def get_frequencies(self, facility: str) -> list[ATCFrequency]:
        return [f for f in self.frequencies if f.facility == facility]
    def get_primary_frequency(self, facility: str) -> ATCFrequency | None:
        matches = self.get_frequencies(facility)
        return matches[0] if matches else None
    def get_adjacency(self) -> dict[int, list[tuple[int, float, str]]]:
        adj: dict[int, list[tuple[int, float, str]]] = {}
        for edge in self.taxiway_edges:
            n1 = self.taxiway_nodes.get(edge.node1_idx)
            n2 = self.taxiway_nodes.get(edge.node2_idx)
            if not n1 or not n2:
                continue
            dist = n1.distance_to(n2)
            name = edge.name
            adj.setdefault(edge.node1_idx, []).append((edge.node2_idx, dist, name))
            if not edge.oneway:
                adj.setdefault(edge.node2_idx, []).append((edge.node1_idx, dist, name))
        return adj
class AirportParser:
    APT_DAT_PATHS = [
        "Custom Scenery/Global Airports/Earth nav data/apt.dat",
        "Resources/default scenery/default apt dat/Earth nav data/apt.dat",
    ]
    def __init__(self, xplane_path: str | Path) -> None:
        self.xplane_path = Path(xplane_path)
    def find_apt_dat(self) -> Path | None:
        for rel_path in self.APT_DAT_PATHS:
            full = self.xplane_path / rel_path
            if full.exists():
                return full
        return None
    def parse_airport(self, icao: str) -> Airport | None:
        apt_dat = self.find_apt_dat()
        if not apt_dat:
            logger.error("apt.dat not found in %s", self.xplane_path)
            return None
        logger.info("Parsing airport %s from %s ...", icao, apt_dat.name)
        airport: Airport | None = None
        in_target = False
        with open(apt_dat, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n\r")
                if not line:
                    continue
                parts = line.split()
                if not parts:
                    continue
                row_code = parts[0]
                if row_code in ("1", "16", "17"):
                    if in_target:
                        break
                    if len(parts) >= 5:
                        apt_icao = parts[4]
                        if apt_icao == icao:
                            in_target = True
                            elevation = int(parts[1]) if parts[1].isdigit() else 0
                            name = " ".join(parts[5:])
                            airport = Airport(icao=icao, name=name, elevation_ft=elevation)
                    continue
                if not in_target or not airport:
                    continue
                if row_code == "100":
                    rwy = self._parse_runway(parts)
                    if rwy:
                        airport.runways.append(rwy)
                        if airport.latitude == 0.0:
                            airport.latitude = (rwy.end1.latitude + rwy.end2.latitude) / 2
                            airport.longitude = (rwy.end1.longitude + rwy.end2.longitude) / 2
                elif row_code == "1201":
                    node = self._parse_taxiway_node(parts)
                    if node:
                        airport.taxiway_nodes[node.index] = node
                elif row_code == "1202":
                    edge = self._parse_taxiway_edge(parts)
                    if edge:
                        airport.taxiway_edges.append(edge)
                elif row_code in ATC_ROW_CODES:
                    freq = self._parse_frequency(row_code, parts)
                    if freq:
                        airport.frequencies.append(freq)
        if airport:
            logger.info(
                "Parsed %s: %d runways, %d taxiway nodes, %d ATC frequencies",
                icao,
                len(airport.runways),
                len(airport.taxiway_nodes),
                len(airport.frequencies),
            )
        else:
            logger.warning("Airport %s not found in apt.dat", icao)
        return airport
    def _parse_frequency(self, row_code: str, parts: list[str]) -> ATCFrequency | None:
        try:
            freq_hz = int(parts[1])
            name = " ".join(parts[2:]) if len(parts) > 2 else ATC_ROW_CODES[row_code]
            facility = ATC_ROW_CODES[row_code]
            return ATCFrequency(facility=facility, name=name, freq_hz=freq_hz)
        except (IndexError, ValueError) as e:
            logger.debug("Failed to parse ATC frequency: %s", e)
            return None
    def _parse_runway(self, parts: list[str]) -> Runway | None:
        try:
            width = float(parts[1])
            surface = int(parts[2])
            name1 = parts[8]
            lat1 = float(parts[9])
            lon1 = float(parts[10])
            name2 = parts[17]
            lat2 = float(parts[18])
            lon2 = float(parts[19])
            hdg1 = self._bearing(lat1, lon1, lat2, lon2)
            hdg2 = (hdg1 + 180) % 360
            return Runway(
                width_m=width,
                surface=surface,
                end1=RunwayEnd(name=name1, latitude=lat1, longitude=lon1, heading=hdg1),
                end2=RunwayEnd(name=name2, latitude=lat2, longitude=lon2, heading=hdg2),
            )
        except (IndexError, ValueError) as e:
            logger.debug("Failed to parse runway: %s", e)
            return None
    def _parse_taxiway_node(self, parts: list[str]) -> TaxiwayNode | None:
        try:
            lat = float(parts[1])
            lon = float(parts[2])
            usage = parts[3]
            idx = int(parts[4])
            name = parts[5] if len(parts) > 5 else ""
            return TaxiwayNode(index=idx, latitude=lat, longitude=lon, usage=usage, name=name)
        except (IndexError, ValueError) as e:
            logger.debug("Failed to parse taxiway node: %s", e)
            return None
    def _parse_taxiway_edge(self, parts: list[str]) -> TaxiwayEdge | None:
        try:
            n1 = int(parts[1])
            n2 = int(parts[2])
            oneway = parts[3] == "oneway"
            runway_crossing = parts[3] == "runway" or (len(parts) > 4 and parts[4] == "runway")
            name = ""
            for i in range(3, len(parts)):
                if parts[i] not in ("twoway", "oneway", "runway"):
                    name = parts[i]
                    break
            return TaxiwayEdge(
                node1_idx=n1,
                node2_idx=n2,
                oneway=oneway,
                runway_crossing=runway_crossing,
                name=name,
            )
        except (IndexError, ValueError) as e:
            logger.debug("Failed to parse taxiway edge: %s", e)
            return None
    @staticmethod
    def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        lat1, lat2 = math.radians(lat1), math.radians(lat2)
        dlon = math.radians(lon2 - lon1)
        x = math.sin(dlon) * math.cos(lat2)
        y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        return (math.degrees(math.atan2(x, y)) + 360) % 360
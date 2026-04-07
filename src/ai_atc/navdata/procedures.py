from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
logger = logging.getLogger(__name__)
@dataclass
class ProcedureWaypoint:
    fix_name: str
    leg_type: str
    altitude_constraint: str = ""
    speed_constraint: str = ""
    course: float = 0.0
    distance: float = 0.0
    is_flyover: bool = False
@dataclass
class Procedure:
    proc_type: str
    name: str
    runway: str = ""
    transition: str = ""
    waypoints: list[ProcedureWaypoint] = field(default_factory=list)
    @property
    def display_name(self) -> str:
        parts = [self.name]
        if self.runway and self.runway != "ALL":
            parts.append(f"({self.runway})")
        return " ".join(parts)
    @property
    def runway_name(self) -> str:
        if self.runway.startswith("RW"):
            return self.runway[2:]
        return self.runway
    @property
    def fix_names(self) -> list[str]:
        return [wp.fix_name for wp in self.waypoints if wp.fix_name.strip()]
@dataclass
class AirportProcedures:
    icao: str
    sids: list[Procedure] = field(default_factory=list)
    stars: list[Procedure] = field(default_factory=list)
    approaches: list[Procedure] = field(default_factory=list)
    def get_sids_for_runway(self, runway: str) -> list[Procedure]:
        results = []
        target = f"RW{runway}" if not runway.startswith("RW") else runway
        for sid in self.sids:
            if sid.runway == "ALL" or sid.runway == target:
                results.append(sid)
        return results
    def get_stars_for_runway(self, runway: str) -> list[Procedure]:
        return [s for s in self.stars if s.transition == "" or s.transition == "ALL"]
    def get_approaches_for_runway(self, runway: str) -> list[Procedure]:
        target = f"RW{runway}" if not runway.startswith("RW") else runway
        return [a for a in self.approaches if a.runway == target]
    def get_unique_sid_names(self, runway: str | None = None) -> list[str]:
        if runway:
            procs = self.get_sids_for_runway(runway)
        else:
            procs = self.sids
        seen: set[str] = set()
        names: list[str] = []
        for p in procs:
            if p.name not in seen:
                seen.add(p.name)
                names.append(p.name)
        return names
    def get_unique_star_names(self) -> list[str]:
        seen: set[str] = set()
        names: list[str] = []
        for p in self.stars:
            if p.name not in seen:
                seen.add(p.name)
                names.append(p.name)
        return names
class CIFPParser:
    CIFP_PATHS = [
        "Custom Data/CIFP",
        "Resources/default data/CIFP",
    ]
    def __init__(self, xplane_path: str | Path) -> None:
        self.xplane_path = Path(xplane_path)
    def find_cifp_file(self, icao: str) -> Path | None:
        for rel in self.CIFP_PATHS:
            path = self.xplane_path / rel / f"{icao}.dat"
            if path.exists():
                return path
        return None
    def parse(self, icao: str) -> AirportProcedures | None:
        cifp_file = self.find_cifp_file(icao)
        if not cifp_file:
            logger.warning("CIFP file not found for %s", icao)
            return None
        logger.info("Parsing CIFP for %s from %s ...", icao, cifp_file)
        procs = AirportProcedures(icao=icao)
        current_procs: dict[tuple[str, str, str, str], Procedure] = {}
        with open(cifp_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n\r")
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                record_type, rest = line.split(":", 1)
                record_type = record_type.strip()
                if record_type not in ("SID", "STAR", "APPCH"):
                    continue
                fields = rest.split(",")
                if len(fields) < 6:
                    continue
                try:
                    proc = self._parse_record(record_type, fields)
                    if not proc:
                        continue
                    key = (proc.proc_type, proc.name, proc.runway, proc.transition)
                    if key not in current_procs:
                        current_procs[key] = proc
                    else:
                        current_procs[key].waypoints.extend(proc.waypoints)
                except Exception:
                    logger.debug("Failed to parse CIFP line: %s", line)
                    continue
        for proc in current_procs.values():
            if proc.proc_type == "SID":
                procs.sids.append(proc)
            elif proc.proc_type == "STAR":
                procs.stars.append(proc)
            elif proc.proc_type == "APPCH":
                procs.approaches.append(proc)
        logger.info(
            "Parsed %s procedures: %d SIDs, %d STARs, %d approaches",
            icao,
            len(procs.sids),
            len(procs.stars),
            len(procs.approaches),
        )
        return procs
    def _parse_record(self, record_type: str, fields: list[str]) -> Procedure | None:
        seqno = fields[0].strip()
        route_type = fields[1].strip()
        name = fields[2].strip()
        transition = fields[3].strip()
        fix_name = fields[4].strip() if len(fields) > 4 else ""
        runway = ""
        trans = ""
        if transition.startswith("RW"):
            runway = transition
        elif transition == "ALL":
            runway = "ALL"
        else:
            trans = transition
            if route_type in ("1", "4"):
                runway = transition
                trans = ""
        leg_type = ""
        altitude_constraint = ""
        for f in fields[5:]:
            f = f.strip()
            if f in (
                "IF", "TF", "CF", "DF", "FA", "FC", "FD", "FM",
                "CA", "CD", "CI", "CR", "VA", "VD", "VI", "VM", "VR",
                "AF", "RF", "HA", "HF", "HM", "PI",
            ):
                leg_type = f
                break
        for f in fields:
            f = f.strip()
            if f and len(f) == 5 and f.isdigit():
                altitude_constraint = f
                break
            if f and f.startswith("+") and f[1:].isdigit():
                altitude_constraint = f
                break
            if f and f.startswith("-") and f[1:].isdigit():
                altitude_constraint = f
                break
        wp = ProcedureWaypoint(
            fix_name=fix_name,
            leg_type=leg_type,
            altitude_constraint=altitude_constraint,
        )
        return Procedure(
            proc_type=record_type,
            name=name,
            runway=runway,
            transition=trans,
            waypoints=[wp],
        )
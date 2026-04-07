from __future__ import annotations
import heapq
import logging
import math
from functools import lru_cache
from dataclasses import dataclass, field
from ai_atc.navdata.airport import Airport, TaxiwayNode
logger = logging.getLogger(__name__)
@dataclass
class TaxiRoute:
    node_indices: list[int]
    total_distance_m: float
    taxiway_names: list[str]
    has_runway_crossing: bool
    runway_crossings: list[str]
    instruction: str
    @property
    def distance_ft(self) -> float:
        return self.total_distance_m * 3.28084
class TaxiwayRouter:
    def __init__(self, airport: Airport) -> None:
        self.airport = airport
        self._adjacency = airport.get_adjacency()
    def find_nearest_node(self, lat: float, lon: float) -> int | None:
        best_idx = None
        best_dist = float("inf")
        for idx, node in self.airport.taxiway_nodes.items():
            dist = self._haversine(lat, lon, node.latitude, node.longitude)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        return best_idx
    def find_nearest_runway_node(self, runway_name: str) -> int | None:
        rwy_end = self.airport.get_runway_end(runway_name)
        if not rwy_end:
            return None
        return self.find_nearest_node(rwy_end.latitude, rwy_end.longitude)
    @lru_cache(maxsize=128)
    def find_route(self, start_idx: int, end_idx: int) -> TaxiRoute | None:
        if start_idx not in self.airport.taxiway_nodes:
            logger.warning("Start node %d not in taxiway network", start_idx)
            return None
        if end_idx not in self.airport.taxiway_nodes:
            logger.warning("End node %d not in taxiway network", end_idx)
            return None
        start_node = self.airport.taxiway_nodes[start_idx]
        end_node = self.airport.taxiway_nodes[end_idx]
        open_set: list[tuple[float, int]] = [(0.0, start_idx)]
        came_from: dict[int, int] = {}
        g_score: dict[int, float] = {start_idx: 0.0}
        edge_names: dict[tuple[int, int], str] = {}
        for edge in self.airport.taxiway_edges:
            edge_names[(edge.node1_idx, edge.node2_idx)] = edge.name
            if not edge.oneway:
                edge_names[(edge.node2_idx, edge.node1_idx)] = edge.name
        while open_set:
            _, current = heapq.heappop(open_set)
            if current == end_idx:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return self._build_route(path, g_score[end_idx], edge_names)
            for neighbor, dist, _ in self._adjacency.get(current, []):
                tentative_g = g_score[current] + dist
                if tentative_g < g_score.get(neighbor, float("inf")):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    n_node = self.airport.taxiway_nodes[neighbor]
                    h = self._haversine(
                        n_node.latitude, n_node.longitude,
                        end_node.latitude, end_node.longitude,
                    )
                    f = tentative_g + h
                    heapq.heappush(open_set, (f, neighbor))
        logger.warning("No taxi route found from node %d to node %d", start_idx, end_idx)
        return None
    def find_route_by_position(self, from_lat: float, from_lon: float, to_runway: str) -> TaxiRoute | None:
        start = self.find_nearest_node(from_lat, from_lon)
        end = self.find_nearest_runway_node(to_runway)
        if start is None or end is None:
            logger.warning("Cannot find start/end nodes for taxi route to %s", to_runway)
            return None
        return self.find_route(start, end)
    def _build_route(
        self,
        path: list[int],
        total_distance: float,
        edge_names: dict[tuple[int, int], str],
    ) -> TaxiRoute:
        taxiway_names: list[str] = []
        runway_crossings: list[str] = []
        has_rwy_cross = False
        for i in range(len(path) - 1):
            n1, n2 = path[i], path[i + 1]
            name = edge_names.get((n1, n2), "")
            for edge in self.airport.taxiway_edges:
                if (edge.node1_idx == n1 and edge.node2_idx == n2) or (
                    edge.node1_idx == n2 and edge.node2_idx == n1 and not edge.oneway
                ):
                    if edge.runway_crossing:
                        has_rwy_cross = True
                        if edge.name:
                            runway_crossings.append(edge.name)
            if name and (not taxiway_names or taxiway_names[-1] != name):
                taxiway_names.append(name)
        instruction = self._generate_instruction(taxiway_names, runway_crossings)
        return TaxiRoute(
            node_indices=path,
            total_distance_m=total_distance,
            taxiway_names=taxiway_names,
            has_runway_crossing=has_rwy_cross,
            runway_crossings=runway_crossings,
            instruction=instruction,
        )
    def _generate_instruction(self, taxiway_names: list[str], runway_crossings: list[str]) -> str:
        if not taxiway_names:
            return "taxi direct"
        phonetic = {
            "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta",
            "E": "Echo", "F": "Foxtrot", "G": "Golf", "H": "Hotel",
            "I": "India", "J": "Juliet", "K": "Kilo", "L": "Lima",
            "M": "Mike", "N": "November", "P": "Papa", "Q": "Quebec",
            "R": "Romeo", "S": "Sierra", "T": "Tango", "U": "Uniform",
            "V": "Victor", "W": "Whiskey", "X": "X-ray", "Y": "Yankee",
            "Z": "Zulu",
        }
        named = []
        for n in taxiway_names:
            if n.upper() in phonetic:
                named.append(phonetic[n.upper()])
            elif len(n) <= 3 and n.isalpha():
                named.append(" ".join(phonetic.get(c.upper(), c) for c in n))
            else:
                named.append(n)
        route = ", ".join(named)
        instruction = f"via {route}"
        if runway_crossings:
            crosses = ", ".join(set(runway_crossings))
            instruction += f", cross runway {crosses}"
        return instruction
    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000
        lat1, lat2 = math.radians(lat1), math.radians(lat2)
        dlat = lat2 - lat1
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        return 2 * r * math.asin(math.sqrt(a))
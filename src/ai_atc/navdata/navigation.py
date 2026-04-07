from __future__ import annotations
import math
EARTH_RADIUS_NM = 3440.065
def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_NM * c
def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - \
        math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360
def cross_track_error_nm(
    lat_p: float, lon_p: float,
    lat_start: float, lon_start: float,
    lat_end: float, lon_end: float
) -> float:
    d_pt = distance_nm(lat_start, lon_start, lat_p, lon_p) / EARTH_RADIUS_NM
    brg_pt = math.radians(bearing_degrees(lat_start, lon_start, lat_p, lon_p))
    brg_track = math.radians(bearing_degrees(lat_start, lon_start, lat_end, lon_end))
    return math.asin(math.sin(d_pt) * math.sin(brg_pt - brg_track)) * EARTH_RADIUS_NM
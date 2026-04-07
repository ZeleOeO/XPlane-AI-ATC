from ai_atc.navdata.navigation import distance_nm
US_ARTCC = {
    "ZBW": (42.7, -71.4),
    "ZNY": (40.7, -73.0),
    "ZDC": (39.1, -77.5),
    "ZJX": (30.6, -81.9),
    "ZMA": (25.8, -80.3),
    "ZHU": (29.9, -95.3),
    "ZFW": (32.8, -97.0),
    "ZAB": (35.1, -106.6),
    "ZLA": (34.6, -118.0),
    "ZOA": (37.5, -122.0),
    "ZSE": (47.3, -122.3),
    "ZLC": (40.7, -111.9),
    "ZDV": (39.8, -104.9),
    "ZKC": (38.8, -94.7),
    "ZMP": (44.6, -93.1),
    "ZAU": (41.7, -88.3),
    "ZID": (39.7, -86.2),
    "ZTL": (33.3, -84.3),
    "ZME": (35.0, -89.9),
}
def get_nearest_artcc(lat: float, lon: float) -> str:
    nearest = "Center"
    min_dist = float('inf')
    for name, (alat, alon) in US_ARTCC.items():
        dist = distance_nm(lat, lon, alat, alon)
        if dist < min_dist:
            min_dist = dist
            nearest = name
    return nearest
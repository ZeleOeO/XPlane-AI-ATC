#!/usr/bin/env python3
"""Isolated test — imports ONLY correction.py, no Groq or heavy deps."""
import sys, re
sys.path.insert(0, "src")

# Import ONLY the correction module (no llm_agent, no groq)
from ai_atc.voice.correction import extract_numbers, extract_runway, validate_readback

print("=== Comma Number Fixes ===")
r1 = extract_numbers("35,000 feet")
print(f"  '35,000 feet' → {r1}  {'✓' if 35000 in r1 else '✗ FAIL'}")

r2 = extract_numbers("1,200")
print(f"  '1,200' → {r2}  {'✓' if 1200 in r2 else '✗ FAIL'}")

print("\n=== Runway Comma Fixes ===")
r3 = extract_runway("runway 22, left")
print(f"  'runway 22, left' → {r3}  {'✓' if r3 == '22L' else '✗ FAIL'}")

r4 = extract_runway("22, left")
print(f"  '22, left' → {r4}  {'✓' if r4 and '22' in r4 else '✗ FAIL'}")

print("\n=== Replaying Your Failed Readbacks ===")
e = {"destination": "KORD", "sid": "Radar Vectors", "runway": "23L", "altitude": "35000", "squawk": "1200"}

# Log line 87: "United 410, runway 23 left, altitude of 35,000 feet."
t1 = "United 410, runway 23 left, altitude of 35,000 feet."
p1, m1 = validate_readback(t1, e, required_fields=["runway", "altitude", "squawk"])
print(f"  Log L87: passed={p1}, missing={m1}  {'✓' if len(m1) <= 1 else '✗ FAIL'}")

# Log line 95: "Kled to Kord Airport, runway 22, left, 1200."
t2 = "United Airlines 410, Kled to Kord Airport, climb via 6, altitude 65,000 feet, runway 22, left, 1200."
p2, m2 = validate_readback(t2, e, required_fields=["destination", "runway", "squawk"])
print(f"  Log L95: passed={p2}, missing={m2}  {'✓' if p2 else '✗'}")

# Log line 65: "Clients to KORD Airport via radar, walk 1,200."
t3 = "United Airlines 410.  Clients to KORD Airport via radar detector C2, climb 75,000 feet and walk 1,200."
p3, m3 = validate_readback(t3, e, required_fields=["destination", "squawk"])
print(f"  Log L65: passed={p3}, missing={m3}  {'✓' if p3 else '✗'}")

print("\nDone!")

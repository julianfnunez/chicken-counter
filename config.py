"""Coop configuration from environment variables."""
import os

def load_coops():
    if "COOP_COUNT" not in os.environ:
        return [{"id": 1, "name": "Main coop",
                 "expected": int(os.environ.get("EXPECTED_CHICKENS", "3")),
                 "url": os.environ.get("RTSP_URL", "")}]
    count = int(os.environ["COOP_COUNT"])
    if not 1 <= count <= 20:
        raise ValueError("COOP_COUNT must be between 1 and 20")
    coops = []
    for i in range(1, count + 1):
        prefix = f"COOP_{i}_"
        expected = int(os.environ[prefix + "EXPECTED_CHICKENS"])
        if not 0 <= expected <= 100:
            raise ValueError(f"{prefix}EXPECTED_CHICKENS must be between 0 and 100")
        coops.append({"id": i, "name": os.environ.get(prefix + "NAME", f"Coop {i}"),
                      "expected": expected, "url": os.environ.get(prefix + "RTSP_URL", "")})
    return coops


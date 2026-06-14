import socket
import time
import sys

services = [
    ("bff-gateway", 8000),
    ("workflow-orchestrator", 8001),
    ("message-broker", 6379),
    ("state-vault", 5432),
    ("vector-store", 6333),
]

RETRY_SECONDS = 60

for host, port in services:
    ok = False
    for i in range(RETRY_SECONDS):
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"{host}:{port} is up")
                ok = True
                break
        except Exception:
            time.sleep(1)
    if not ok:
        print(f"Timed out waiting for {host}:{port}", file=sys.stderr)
        sys.exit(1)

print("All services available")

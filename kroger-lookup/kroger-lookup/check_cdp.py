"""Run this while Chrome is open with --remote-debugging-port=9333"""
import urllib.request
import json
import socket

print(f"=== CDP Diagnostic ===")

# 1. Check if port 9333 is open at all
try:
    s = socket.create_connection(("localhost", 9333), timeout=3)
    s.close()
    print("✓ Port 9333 is open")
except Exception as e:
    print(f"✗ Port 9333 not reachable: {e}")
    print("  Chrome may not have the debug port open.")
    exit(1)

# 2. Try /json/version
for url in [
    "http://localhost:9333/json/version",
    "http://127.0.0.1:9333/json/version",
]:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            data = json.loads(r.read())
            print(f"✓ {url}")
            print(f"  Browser: {data.get('Browser')}")
            print(f"  wsUrl:   {data.get('webSocketDebuggerUrl')}")
    except Exception as e:
        print(f"✗ {url}: {e}")

# 3. Try /json
try:
    with urllib.request.urlopen("http://localhost:9333/json", timeout=3) as r:
        tabs = json.loads(r.read())
        print(f"✓ /json: {len(tabs)} tabs")
        for t in tabs[:3]:
            print(f"  [{t.get('type')}] {t.get('url','')[:60]}")
except Exception as e:
    print(f"✗ /json: {e}")

"""
Diagnostic: inspect Chrome's cookie DB for kroger.com entries.
Run with: python check_cookies.py
"""
import os
import json
import shutil
import sqlite3
import tempfile

# --- Find User Data ---
user_data = next(
    (p for p in [
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
        os.path.expanduser("~/.config/google-chrome"),
        os.path.expanduser("~/Library/Application Support/Google/Chrome"),
    ] if os.path.isdir(p)),
    None
)
print(f"User Data dir: {user_data}")

# --- Detect profile ---
local_state_path = os.path.join(user_data, "Local State")
profile_name = "Default"
with open(local_state_path, "r", encoding="utf-8") as f:
    ls = json.load(f)
profile_name = ls.get("profile", {}).get("last_used", "Default")
print(f"Last used profile: {profile_name}")

# --- Find cookie DB ---
cookie_src = os.path.join(user_data, profile_name, "Network", "Cookies")
if not os.path.exists(cookie_src):
    cookie_src = os.path.join(user_data, profile_name, "Cookies")
print(f"Cookie DB path: {cookie_src}")
print(f"Cookie DB exists: {os.path.exists(cookie_src)}")

# --- Copy and inspect ---
tmp = tempfile.mkdtemp()
tmp_cookie = os.path.join(tmp, "Cookies")
shutil.copy2(cookie_src, tmp_cookie)

conn = sqlite3.connect(tmp_cookie)
conn.row_factory = sqlite3.Row

# Total cookie count
total = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()[0]
print(f"\nTotal cookies in DB: {total}")

# All distinct host_keys (top 30)
print("\nTop 30 domains with cookies:")
rows = conn.execute(
    "SELECT host_key, COUNT(*) as c FROM cookies GROUP BY host_key ORDER BY c DESC LIMIT 30"
).fetchall()
for r in rows:
    print(f"  {r['host_key']:45s} {r['c']} cookies")

# Kroger specifically
print("\nKroger.com cookie rows:")
kroger = conn.execute(
    "SELECT name, host_key, length(encrypted_value) as val_len, expires_utc "
    "FROM cookies WHERE host_key LIKE '%kroger%' ORDER BY host_key, name"
).fetchall()
if kroger:
    for r in kroger:
        print(f"  [{r['host_key']}] {r['name']:30s} encrypted_len={r['val_len']}")
else:
    print("  *** NO kroger.com cookies found ***")
    print("  → Open kroger.com in Chrome and browse around, then re-run this script.")

conn.close()
shutil.rmtree(tmp, ignore_errors=True)

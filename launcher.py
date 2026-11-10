"""Launch the laptop app and a temporary public Cloudflare Quick Tunnel."""
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

import local_db
from laptop_app import app, owner_pin

ROOT = Path(__file__).resolve().parent
CLOUDFLARED = ROOT / "cloudflared.exe"
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def wait_for_server(timeout=30):
    started = time.time()
    while time.time() - started < timeout:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    local_db.init_db()
    pin = owner_pin()
    print("=" * 76)
    print("LAGGAM IPHOTOO — LAPTOP EVENT SERVER")
    print("=" * 76)
    print("Studio PIN (keep private): " + pin)
    print("Photo database: " + str(local_db.DB_PATH))
    print("Photos stay in the folder you select; they are not copied to cloud storage.")
    print("")

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info"))
    server_thread = threading.Thread(target=server.run, name="laggam-web-server", daemon=True)
    server_thread.start()
    if not wait_for_server():
        print("The local web server did not start. Check the error messages above.")
        server.should_exit = True
        return 1

    webbrowser.open("http://127.0.0.1:8000")
    if not CLOUDFLARED.is_file():
        print("cloudflared.exe is missing. Run setup_laptop.bat first.")
        print("Local admin page: http://127.0.0.1:8000")
        input("Press Enter to stop the local server...")
        server.should_exit = True
        return 1

    print("Starting Cloudflare Quick Tunnel. Keep this window open during the event.")
    print("The temporary public URL will appear below.")
    command = [str(CLOUDFLARED), "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate"]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        print("Could not start cloudflared: " + str(exc))
        server.should_exit = True
        return 1

    try:
        for line in process.stdout:
            line = line.rstrip()
            if line:
                print("[TUNNEL] " + line)
            match = URL_PATTERN.search(line)
            if match:
                url = match.group(0).rstrip(".,)")
                local_db.set_setting("public_base_url", url)
                print("")
                print("=" * 76)
                print("PUBLIC GUEST LINK: " + url)
                print("Open this laptop's site and create the event AFTER this URL appears.")
                print("Event QR codes will now point to the public guest link.")
                print("=" * 76)
                print("")
    except KeyboardInterrupt:
        print("\nStopping the tunnel and local web server...")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        local_db.set_setting("public_base_url", "")
        server.should_exit = True
        server_thread.join(timeout=8)
    return 0


if __name__ == "__main__":
    sys.exit(main())

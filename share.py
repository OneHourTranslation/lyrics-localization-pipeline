"""
share.py — starts the review server and exposes it publicly via ngrok.

Usage:
  python share.py [--port 8080]

First-time setup (once only):
  1. Install ngrok
       Windows : winget install ngrok
       Mac     : brew install ngrok
       Linux   : snap install ngrok
  2. Sign up free at https://ngrok.com
  3. Run: ngrok config add-authtoken <your-token>
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request


def _check_ngrok() -> bool:
    try:
        subprocess.run(["ngrok", "version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _get_public_url(retries: int = 20) -> str | None:
    for _ in range(retries):
        try:
            with urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=2) as r:
                data = json.loads(r.read())
                for tunnel in data.get("tunnels", []):
                    if tunnel.get("proto") == "https":
                        return tunnel["public_url"]
        except Exception:
            pass
        time.sleep(1)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Start review server + ngrok tunnel")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    # ── ngrok check ──────────────────────────────────────────────────────────
    if not _check_ngrok():
        print("\nngrok is not installed. Install it first:")
        print("  Windows : winget install ngrok")
        print("  Mac     : brew install ngrok")
        print("  Linux   : snap install ngrok")
        print("\nThen sign up free at https://ngrok.com and run:")
        print("  ngrok config add-authtoken <your-token>")
        print()
        sys.exit(1)

    # ── start review server ───────────────────────────────────────────────────
    print("\nStarting review server...", flush=True)
    server = subprocess.Popen(
        [sys.executable, "review.py", "serve", "--port", str(args.port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    if server.poll() is not None:
        print("Review server failed to start. Run `python review.py serve` to see the error.")
        sys.exit(1)

    # ── start ngrok ───────────────────────────────────────────────────────────
    print("Opening ngrok tunnel...", flush=True)
    ngrok = subprocess.Popen(
        ["ngrok", "http", str(args.port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print("Waiting for public URL...", end="", flush=True)
    url = _get_public_url()

    if not url:
        print("\n\nCould not get ngrok URL.")
        print("Make sure you have added your authtoken: ngrok config add-authtoken <token>")
        server.terminate()
        ngrok.terminate()
        sys.exit(1)

    # ── print share info ──────────────────────────────────────────────────────
    divider = "-" * 48
    print(f"\n\n  {divider}")
    print(f"  Review tool is LIVE - share this link:")
    print(f"  {divider}")
    print(f"\n      {url}\n")
    print(f"  Local (your machine only): http://localhost:{args.port}")
    print(f"\n  {divider}")
    print(f"  Press Ctrl+C to stop sharing.")
    print(f"  {divider}\n")

    # ── keep running until Ctrl+C ─────────────────────────────────────────────
    try:
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down...")
        server.terminate()
        ngrok.terminate()


if __name__ == "__main__":
    main()

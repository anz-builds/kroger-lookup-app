"""Start the backend: `python -m kroger_lookup`. Also the PyInstaller entry point."""
import os

import uvicorn

from kroger_lookup.main import WEB_MODE, app


def main() -> None:
    # The desktop app talks to the backend over localhost only; the web build listens on all interfaces
    host = "0.0.0.0" if WEB_MODE else "127.0.0.1"
    port = int(os.environ.get("PORT", "8000"))
    print(f"Starting Kroger Price Lookup on http://{host}:{port} (web_mode={WEB_MODE})")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

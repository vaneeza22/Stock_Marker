# Run Meridian in VS Code (Windows / macOS / Linux)

Requires Python 3.11+ (https://python.org; on Windows tick "Add to PATH").

1. Unzip, then `File > Open Folder...` and choose the `meridian` folder.
2. Open the terminal (Ctrl+`) and run:

   Windows (PowerShell):
   ```
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   macOS / Linux:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
   (If PowerShell blocks activation: `Set-ExecutionPolicy -Scope Process Bypass`.)
3. Check the real Nasdaq feed from your machine: `python scripts/check_nasdaq.py`
4. Start the app: `python run.py` (opens http://localhost:8000). Or press F5 and pick "Meridian: run app".
5. Look at the pills at the top of the UI: `data: nasdaq` = live; `data: synthetic` = simulated fallback (labelled everywhere).

Optional: put `ANTHROPIC_API_KEY=...` in `.env` to use the LLM planner instead of the offline planner.

## Notes
- Real Nasdaq data uses the unofficial api.nasdaq.com endpoints: free, may be delayed, may change or rate-limit. `MERIDIAN_PROVIDER=auto` falls back to simulated data and says so.
- Windows: the sandbox still blocks sockets, dangerous imports and enforces a wall-clock timeout, but CPU/memory rlimits are POSIX-only. Use WSL or `SANDBOX_BACKEND=docker` for hard limits. Celery workers need Linux/WSL/Docker; on Windows keep `MERIDIAN_JOBS=thread` (default).
- Everything at once with Docker: `docker compose up --build`.
- Tests: `pytest`.

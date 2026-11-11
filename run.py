"""One-command launcher:  python run.py  ->  http://localhost:8000"""
import threading
import webbrowser

import uvicorn

if __name__ == "__main__":
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000")).start()
    uvicorn.run("meridian.api.app:app", host="127.0.0.1", port=8000, reload=False)

# Hardened sandbox image used by SANDBOX_BACKEND=docker.
# Run with:  docker run --rm -i --network none --read-only --cap-drop ALL --pids-limit 64 -u 65534 meridian-sandbox python -I /sandbox/runner.py
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1
RUN pip install --no-cache-dir numpy pandas
COPY meridian/sandbox/runner.py /sandbox/runner.py
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT []

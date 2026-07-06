FROM registry.access.redhat.com/ubi9/python-312:latest

USER 0

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=1001:0 --chmod=775 lifecycle-graph.py server.py lifecycle-config.yaml LIFECYCLE.md ./
COPY --chown=1001:0 --chmod=775 static/ static/

RUN python lifecycle-graph.py --product all --output-dir docs && chown -R 1001:0 docs/

USER 1001

ENV FLASK_HOST=0.0.0.0 \
    FLASK_PORT=8080

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "2", "server:app"]

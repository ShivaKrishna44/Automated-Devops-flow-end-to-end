"""
Demo application — a tiny Flask service the pipeline builds, deploys, and
monitors. Intentionally simple: the point of this project is the end-to-end
automation around the app, not the app's business logic.
"""
import os
from flask import Flask, jsonify

app = Flask(__name__)

VERSION = os.getenv("APP_VERSION", "1.0.0")


@app.route("/")
def home():
    return jsonify(service="demo-app", status="running", version=VERSION)


@app.route("/healthz")
def health():
    # Used by the Kubernetes liveness/readiness probes and the Verify agent.
    return jsonify(status="healthy"), 200


@app.route("/metrics")
def metrics():
    # Minimal Prometheus-style metric so the monitoring stack has something
    # to scrape. A real app would use prometheus_client.
    return (
        "# HELP demo_app_up 1 if the app is up\n"
        "# TYPE demo_app_up gauge\n"
        "demo_app_up 1\n",
        200,
        {"Content-Type": "text/plain"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

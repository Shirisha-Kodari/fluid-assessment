from flask import Flask, jsonify
import redis, os

app = Flask(__name__)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
r = redis.Redis(host=REDIS_HOST, port=6379, db=0, socket_connect_timeout=2)

@app.route("/")
def index():
    count = r.incr("hits")
    return jsonify({"message": "Hello from DevOps Challenge", "hits": count})

@app.route("/health")
def health():
    # liveness: is the process alive at all (no external deps checked)
    return jsonify({"status": "ok"}), 200

@app.route("/ready")
def ready():
    # readiness: can we actually serve traffic (dependency check)
    try:
        r.ping()
        return jsonify({"status": "ready"}), 200
    except Exception as e:
        return jsonify({"status": "not ready", "error": str(e)}), 503

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
from flask import Flask, jsonify, request, Response
import requests

app = Flask(__name__)

# Base URLs ng Microservices
RESERVATION_SERVICE_URL = "http://127.0.0.1:5001"
INVENTORY_SERVICE_URL = "http://127.0.0.1:5002"

def proxy_request(target_url):
    headers = {key: value for key, value in request.headers if key.lower() != 'host'}
    
    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=5
        )
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [(name, value) for (name, value) in resp.raw.headers.items() 
                            if name.lower() not in excluded_headers]
        
        return Response(resp.content, resp.status_code, response_headers)
        
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "SERVICE_UNAVAILABLE", "message": "Target microservice is unreachable"}), 503
    except requests.exceptions.Timeout:
        return jsonify({"error": "GATEWAY_TIMEOUT", "message": "Target microservice timed out"}), 504

# ---------------------------------------------------------
# ROUTES FOR RESERVATION SERVICE (/api/reservations/*)
# ---------------------------------------------------------
@app.route('/api/reservations', methods=['GET', 'POST'], defaults={'path': ''})
@app.route('/api/reservations/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def reservation_gateway(path):
    target_path = f"/reservations/{path}" if path else "/reservations"
    return proxy_request(f"{RESERVATION_SERVICE_URL}{target_path}")

# ---------------------------------------------------------
# ROUTES FOR INVENTORY SERVICE (/api/medicines/*)
# ---------------------------------------------------------
@app.route('/api/medicines', methods=['GET', 'POST'], defaults={'path': ''})
@app.route('/api/medicines/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def inventory_gateway(path):
    target_path = f"/medicines/{path}" if path else "/medicines"
    return proxy_request(f"{INVENTORY_SERVICE_URL}{target_path}")

# ---------------------------------------------------------
# GATEWAY HEALTH CHECK
# ---------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({
        "service": "api-gateway",
        "status": "UP"
    }), 200

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from datetime import datetime, timedelta
import random
import os

app = Flask(__name__)
CORS(app)

# ──────────────────────────────────────────────────────────────────────────────
# DATABASE SETUP
# ──────────────────────────────────────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "arrosage_intelligent"

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Ping to check connection
    client.server_info()
    db = client[DB_NAME]
    print("✓ MongoDB connected successfully")
except ConnectionFailure:
    print("✗ MongoDB connection failed - Running in demo mode")
    db = None

# Create collections with indexes if they don't exist
if db is not None:
    # Collection for humidity readings
    if "readings" not in db.list_collection_names():
        db.create_collection("readings")
        db.readings.create_index("timestamp", expireAfterSeconds=604800)  # 7 days TTL
        print("✓ Created 'readings' collection with TTL index")
    
    # Collection for logic/irrigation rules
    if "logic" not in db.list_collection_names():
        db.create_collection("logic")
        print("✓ Created 'logic' collection")
    
    # Initialize default logic if empty
    if db.logic.count_documents({}) == 0:
        db.logic.insert_one({
            "name": "default",
            "dry_threshold": 30,
            "optimal_min": 45,
            "optimal_max": 75,
            "wet_threshold": 80,
            "auto_irrigation": True,
            "last_updated": datetime.utcnow()
        })
        print("✓ Initialized default logic rules")

# ──────────────────────────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    """Check API and database health"""
    return jsonify({
        "status": "ok",
        "db": "connected" if db is not None else "offline",
        "timestamp": datetime.utcnow().isoformat()
    })

@app.route("/api/latest", methods=["GET"])
def get_latest():
    """Get the latest humidity reading"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    reading = db.readings.find_one(sort=[("timestamp", -1)])
    if reading:
        reading.pop("_id", None)
        return jsonify(reading)
    return jsonify({"humidity": 0, "timestamp": datetime.utcnow().isoformat()}), 200

@app.route("/api/history", methods=["GET"])
def get_history():
    """Get last 50 readings"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    readings = list(db.readings.find().sort("timestamp", -1).limit(50))
    for r in readings:
        r.pop("_id", None)
    return jsonify(readings)

@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Get statistics from last 50 readings"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    readings = list(db.readings.find().sort("timestamp", -1).limit(50))
    
    if not readings:
        return jsonify({"avg": 0, "min": 0, "max": 0}), 200
    
    humidities = [r["humidity"] for r in readings]
    return jsonify({
        "avg": round(sum(humidities) / len(humidities)),
        "min": min(humidities),
        "max": max(humidities)
    })

@app.route("/api/readings", methods=["POST"])
def add_reading():
    """Add a new humidity reading"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    data = request.get_json()
    
    if not data or "humidity" not in data:
        return jsonify({"error": "Missing humidity field"}), 400
    
    reading = {
        "humidity": data["humidity"],
        "timestamp": datetime.utcnow().isoformat(),
        "source": data.get("source", "sensor")
    }
    
    result = db.readings.insert_one(reading)
    reading["_id"] = str(result.inserted_id)
    
    return jsonify(reading), 201

@app.route("/api/readings/bulk", methods=["POST"])
def bulk_add_readings():
    """Add multiple readings at once"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    data = request.get_json()
    
    if not isinstance(data, list) or not data:
        return jsonify({"error": "Expected array of readings"}), 400
    
    readings = []
    for item in data:
        if "humidity" in item:
            readings.append({
                "humidity": item["humidity"],
                "timestamp": item.get("timestamp", datetime.utcnow().isoformat()),
                "source": item.get("source", "sensor")
            })
    
    if readings:
        result = db.readings.insert_many(readings)
        return jsonify({"inserted": len(result.inserted_ids)}), 201
    
    return jsonify({"error": "No valid readings"}), 400

# ──────────────────────────────────────────────────────────────────────────────
# LOGIC ROUTES
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/logic", methods=["GET"])
def get_logic():
    """Get current irrigation logic rules"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    logic = db.logic.find_one({"name": "default"})
    if logic:
        logic.pop("_id", None)
        logic.pop("last_updated", None)
        return jsonify(logic)
    
    return jsonify({
        "dry_threshold": 30,
        "optimal_min": 45,
        "optimal_max": 75,
        "wet_threshold": 80,
        "auto_irrigation": True
    })

@app.route("/api/logic", methods=["PUT"])
def update_logic():
    """Update irrigation logic rules"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    data = request.get_json()
    
    update_data = {
        "last_updated": datetime.utcnow(),
        **data
    }
    
    result = db.logic.update_one(
        {"name": "default"},
        {"$set": update_data},
        upsert=True
    )
    
    return jsonify({
        "modified": result.modified_count,
        "message": "Logic updated successfully"
    })

@app.route("/api/analyze", methods=["GET"])
def analyze_readings():
    """Analyze readings and recommend irrigation"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    latest = db.readings.find_one(sort=[("timestamp", -1)])
    logic = db.logic.find_one({"name": "default"}) or {}
    
    if not latest:
        return jsonify({"error": "No readings available"}), 404
    
    humidity = latest["humidity"]
    dry_threshold = logic.get("dry_threshold", 30)
    optimal_min = logic.get("optimal_min", 45)
    optimal_max = logic.get("optimal_max", 75)
    wet_threshold = logic.get("wet_threshold", 80)
    
    if humidity < dry_threshold:
        status = "ALERTE_SECHERESSE"
        recommendation = "Irrigation immédiate recommandée"
        urgency = "CRITIQUE"
    elif humidity < optimal_min:
        status = "SEC"
        recommendation = "Irrigation recommandée"
        urgency = "HAUTE"
    elif optimal_min <= humidity <= optimal_max:
        status = "OPTIMAL"
        recommendation = "Aucune action requise"
        urgency = "BASSE"
    elif humidity <= wet_threshold:
        status = "HUMIDE"
        recommendation = "Attendre avant irrigation"
        urgency = "BASSE"
    else:
        status = "TRES_HUMIDE"
        recommendation = "Trop d'eau - vérifier le système"
        urgency = "MOYENNE"
    
    return jsonify({
        "current_humidity": humidity,
        "status": status,
        "recommendation": recommendation,
        "urgency": urgency,
        "thresholds": {
            "dry": dry_threshold,
            "optimal_min": optimal_min,
            "optimal_max": optimal_max,
            "wet": wet_threshold
        },
        "timestamp": latest["timestamp"]
    })

# ──────────────────────────────────────────────────────────────────────────────
# DEMO MODE
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/demo/seed", methods=["POST"])
def seed_demo_data():
    """Populate database with demo data"""
    if db is None:
        return jsonify({"error": "Database offline"}), 503
    
    # Generate 50 demo readings
    readings = []
    base_time = datetime.utcnow() - timedelta(minutes=500)
    
    for i in range(50):
        readings.append({
            "humidity": random.randint(25, 80),
            "timestamp": (base_time + timedelta(minutes=i*10)).isoformat(),
            "source": "demo"
        })
    
    db.readings.delete_many({"source": "demo"})  # Clear old demo data
    result = db.readings.insert_many(readings)
    
    return jsonify({
        "inserted": len(result.inserted_ids),
        "message": "Demo data seeded successfully"
    })

# ──────────────────────────────────────────────────────────────────────────────
# ERROR HANDLERS
# ──────────────────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🌾 Système d'Arrosage Intelligent - API Backend")
    print("📊 Démarrage du serveur sur http://localhost:5000")
    app.run(debug=True, host="localhost", port=5000)

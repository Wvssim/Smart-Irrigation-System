from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from datetime import datetime, timedelta
import random
import os

app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Connection
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = MongoClient(MONGO_URL)
db = client["irrigation_system"]
measurements = db["measurements"]
logs = db["logs"]

# Créer les indexes
measurements.create_index("timestamp", expireAfterSeconds=604800)  # 7 jours
logs.create_index("timestamp", expireAfterSeconds=2592000)  # 30 jours

# ─── HEALTHCHECK ────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "irrigation-api"}

# ─── LATEST ─────────────────────────────────────────────────────────────
@app.get("/api/latest")
async def get_latest():
    """Retourne la mesure la plus récente"""
    try:
        doc = measurements.find_one(sort=[("timestamp", -1)])
        if doc:
            return {
                "humidity": doc["humidity"],
                "timestamp": doc["timestamp"].isoformat(),
                "temperature": doc.get("temperature", None),
                "sensor_id": doc.get("sensor_id", "default")
            }
        
        # Pas de données, créer une mesure de démo
        humidity = random.randint(25, 80)
        measurement = {
            "humidity": humidity,
            "timestamp": datetime.utcnow(),
            "temperature": random.randint(15, 30),
            "sensor_id": "demo",
            "alert": humidity < 30
        }
        measurements.insert_one(measurement)
        log_entry = {
            "timestamp": datetime.utcnow(),
            "level": "WARNING" if humidity < 30 else "INFO",
            "message": f"Mesure initiale: {humidity}%",
            "humidity": humidity
        }
        logs.insert_one(log_entry)
        return {
            "humidity": humidity,
            "timestamp": measurement["timestamp"].isoformat(),
            "temperature": measurement["temperature"],
            "sensor_id": "demo"
        }
    except Exception as e:
        return {"error": str(e)}, 500

# ─── HISTORY ────────────────────────────────────────────────────────────
@app.get("/api/history")
async def get_history(limit: int = 50):
    """Retourne les 50 dernières mesures"""
    docs = list(measurements.find().sort("timestamp", -1).limit(limit))
    return [
        {
            "humidity": doc["humidity"],
            "timestamp": doc["timestamp"].isoformat(),
            "temperature": doc.get("temperature"),
            "sensor_id": doc.get("sensor_id")
        }
        for doc in reversed(docs)
    ]

# ─── STATS ──────────────────────────────────────────────────────────────
@app.get("/api/stats")
async def get_stats(hours: int = 24):
    """Retourne les statistiques des dernières 24h"""
    since = datetime.utcnow() - timedelta(hours=hours)
    docs = list(measurements.find({"timestamp": {"$gte": since}}))
    
    if not docs:
        return {"avg": 0, "min": 0, "max": 0, "count": 0}
    
    values = [doc["humidity"] for doc in docs]
    return {
        "avg": round(sum(values) / len(values)),
        "min": min(values),
        "max": max(values),
        "count": len(values)
    }

# ─── LOGS ───────────────────────────────────────────────────────────────
@app.get("/api/logs")
async def get_logs(limit: int = 100):
    """Retourne les derniers logs"""
    docs = list(logs.find().sort("timestamp", -1).limit(limit))
    return [
        {
            "timestamp": doc["timestamp"].isoformat(),
            "level": doc.get("level", "INFO"),
            "message": doc["message"],
            "humidity": doc.get("humidity")
        }
        for doc in reversed(docs)
    ]

# ─── CREATE MEASUREMENT ─────────────────────────────────────────────────
@app.post("/api/measurements")
async def create_measurement(humidity: int, temperature: int = None, sensor_id: str = "sensor-1"):
    """Crée une nouvelle mesure"""
    if not (0 <= humidity <= 100):
        return {"error": "Humidity must be between 0 and 100"}, 400
    
    measurement = {
        "humidity": humidity,
        "temperature": temperature,
        "timestamp": datetime.utcnow(),
        "sensor_id": sensor_id,
        "alert": humidity < 30
    }
    
    result = measurements.insert_one(measurement)
    
    # Log l'événement
    log_level = "CRITICAL" if humidity < 20 else "WARNING" if humidity < 30 else "INFO"
    log_entry = {
        "timestamp": datetime.utcnow(),
        "level": log_level,
        "message": f"Humidité: {humidity}% | Capteur: {sensor_id} | Temp: {temperature}°C",
        "humidity": humidity,
        "measurement_id": str(result.inserted_id)
    }
    logs.insert_one(log_entry)
    
    return {
        "id": str(result.inserted_id),
        "humidity": humidity,
        "timestamp": measurement["timestamp"].isoformat(),
        "alert": measurement["alert"]
    }

# ─── SIMULATE SENSOR ────────────────────────────────────────────────────
@app.post("/api/simulate")
async def simulate_sensor():
    """Simule une lecture de capteur"""
    humidity = random.randint(20, 85)
    temperature = random.randint(12, 32)
    
    measurement = {
        "humidity": humidity,
        "temperature": temperature,
        "timestamp": datetime.utcnow(),
        "sensor_id": "sim-sensor",
        "alert": humidity < 30
    }
    
    result = measurements.insert_one(measurement)
    
    # Log
    if humidity < 30:
        log_msg = f"⚠️ ALERTE: Humidité critique {humidity}%"
        log_level = "CRITICAL"
    elif humidity < 50:
        log_msg = f"⚡ Humidité basse: {humidity}%"
        log_level = "WARNING"
    else:
        log_msg = f"✓ Conditions normales: {humidity}%"
        log_level = "INFO"
    
    log_entry = {
        "timestamp": datetime.utcnow(),
        "level": log_level,
        "message": log_msg,
        "humidity": humidity,
        "measurement_id": str(result.inserted_id)
    }
    logs.insert_one(log_entry)
    
    return {
        "id": str(result.inserted_id),
        "humidity": humidity,
        "temperature": temperature,
        "timestamp": measurement["timestamp"].isoformat(),
        "alert": measurement["alert"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

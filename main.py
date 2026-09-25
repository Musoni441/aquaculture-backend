import os
import math
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Field, SQLModel, Session, create_engine, select

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./aquaculture.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, echo=False)

class SensorLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    species_key: str  
    temperature: float
    ph: float
    dissolved_oxygen: float
    tan: float  
    nitrite: float
    calculated_nh3: float  
    ammonia_status: str     
    nitrite_status: str     
    do_status: str          
    temp_status: str        
    ph_status: str          
    required_salt_g_per_m3: float 

SPECIES_THRESHOLDS = {
    "catfish_adult": {
        "temp": {"optMin": 26.0, "optMax": 30.0, "stressMin": 22.0, "stressMax": 33.0},
        "do": {"optMin": 4.0, "optMax": 8.0, "stressMin": 1.5, "stressMax": 3.9},
        "ph": {"optMin": 6.5, "optMax": 8.0, "stressMin": 6.0, "stressMax": 8.5},
        "nh3": {"maxOpt": 0.05, "maxStress": 0.20},
        "nitrite": {"maxOpt": 0.5, "maxStress": 2.0}
    },
    "catfish_nursery": {
        "temp": {"optMin": 28.0, "optMax": 31.0, "stressMin": 25.0, "stressMax": 32.0},
        "do": {"optMin": 4.5, "optMax": 8.0, "stressMin": 2.5, "stressMax": 4.4},
        "ph": {"optMin": 6.8, "optMax": 7.5, "stressMin": 6.2, "stressMax": 8.0},
        "nh3": {"maxOpt": 0.02, "maxStress": 0.05},
        "nitrite": {"maxOpt": 0.2, "maxStress": 0.5}
    },
    "tilapia_adult": {
        "temp": {"optMin": 27.0, "optMax": 30.0, "stressMin": 21.0, "stressMax": 34.0},
        "do": {"optMin": 5.0, "optMax": 8.0, "stressMin": 1.5, "stressMax": 4.9},
        "ph": {"optMin": 6.5, "optMax": 8.5, "stressMin": 5.5, "stressMax": 9.0},
        "nh3": {"maxOpt": 0.05, "maxStress": 0.20},
        "nitrite": {"maxOpt": 0.5, "maxStress": 2.0}
    },
    "tilapia_nursery": {
        "temp": {"optMin": 28.0, "optMax": 30.0, "stressMin": 24.0, "stressMax": 32.0},
        "do": {"optMin": 5.0, "optMax": 8.0, "stressMin": 3.0, "stressMax": 4.9},
        "ph": {"optMin": 7.0, "optMax": 8.0, "stressMin": 6.0, "stressMax": 8.5},
        "nh3": {"maxOpt": 0.02, "maxStress": 0.05},
        "nitrite": {"maxOpt": 0.1, "maxStress": 0.4}
    },
    "carp_adult": {
        "temp": {"optMin": 23.0, "optMax": 28.0, "stressMin": 15.0, "stressMax": 32.0},
        "do": {"optMin": 5.0, "optMax": 7.0, "stressMin": 2.0, "stressMax": 4.9},
        "ph": {"optMin": 7.0, "optMax": 8.0, "stressMin": 6.5, "stressMax": 8.5},
        "nh3": {"maxOpt": 0.02, "maxStress": 0.05},
        "nitrite": {"maxOpt": 0.2, "maxStress": 1.0}
    },
    "carp_nursery": {
        "temp": {"optMin": 24.0, "optMax": 26.0, "stressMin": 20.0, "stressMax": 29.0},
        "do": {"optMin": 6.0, "optMax": 8.0, "stressMin": 4.0, "stressMax": 5.9},
        "ph": {"optMin": 7.2, "optMax": 7.8, "stressMin": 6.7, "stressMax": 8.2},
        "nh3": {"maxOpt": 0.01, "maxStress": 0.03},
        "nitrite": {"maxOpt": 0.1, "maxStress": 0.3}
    }
}

def evaluate_range(val, limits):
    if limits["optMin"] <= val <= limits["optMax"]: return "Optimal"
    if limits["stressMin"] <= val <= limits["stressMax"]: return "Stress"
    return "Critical"

def evaluate_max(val, limits):
    if val <= limits["maxOpt"]: return "Optimal"
    if val <= limits["maxStress"]: return "Stress"
    return "Critical"

app = FastAPI(title="Rwanda Aquaculture API Engine")

@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

class TelemetryIn(BaseModel):
    species_key: str
    temperature: float
    ph: float
    dissolved_oxygen: float
    tan: float
    nitrite: float

@app.post("/api/telemetry")
def receive_telemetry(data: TelemetryIn):
    if data.species_key not in SPECIES_THRESHOLDS:
        raise HTTPException(status_code=400, detail="Invalid profile.")
    
    rules = SPECIES_THRESHOLDS[data.species_key]
    pKa = (2729.92 / (273.15 + data.temperature)) + 0.09018
    fraction = 1 / (math.pow(10, (pKa - data.ph)) + 1)
    nh3 = data.tan * fraction
    salt_g_per_m3 = (data.nitrite * 20) * 1.65

    log_entry = SensorLog(
        species_key=data.species_key,
        temperature=data.temperature,
        ph=data.ph,
        dissolved_oxygen=data.dissolved_oxygen,
        tan=data.tan,
        nitrite=data.nitrite,
        calculated_nh3=round(nh3, 5),
        temp_status=evaluate_range(data.temperature, rules["temp"]),
        ph_status=evaluate_range(data.ph, rules["ph"]),
        do_status=evaluate_range(data.dissolved_oxygen, rules["do"]),
        ammonia_status=evaluate_max(nh3, rules["nh3"]),
        nitrite_status=evaluate_max(data.nitrite, rules["nitrite"]),
        required_salt_g_per_m3=round(salt_g_per_m3, 2)
    )

    with Session(engine) as session:
        session.add(log_entry)
        session.commit()
        session.refresh(log_entry)
        
    return {"status": "success", "id": log_entry.id}

@app.get("/api/history")
def get_history(limit: int = 20):
    with Session(engine) as session:
        statement = select(SensorLog).order_by(SensorLog.timestamp.desc()).limit(limit)
        return session.exec(statement).all()

"""
Parking lot management API (simple version).

Run with:  python main.py
Then open: http://localhost:8000/
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# --------------------------------------------------------------------------- #
# 1. DATABASE SETUP
# --------------------------------------------------------------------------- #
# Type your own Postgres details here: USER, PASSWORD and DATABASE_NAME
DATABASE_URL = "postgresql+psycopg2://postgres:kis1234@127.0.0.1:5432/parkinglot"

# The "engine" is the connection to your database
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# --------------------------------------------------------------------------- #
# 2. TABLES
# --------------------------------------------------------------------------- #
class Floor(Base):
    __tablename__ = "floors"

    id = Column(Integer, primary_key=True)
    floor_number = Column(Integer, unique=True, nullable=False)
    capacity = Column(Integer, nullable=False)  # max vehicles allowed on this floor


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True)
    floor_id = Column(Integer, ForeignKey("floors.id"), nullable=False)  # which floor it is on
    number_plate = Column(String(20), unique=True, nullable=False)  # unique: one plate = one spot
    vehicle_type = Column(String(30), nullable=False)
    colour = Column(String(30), nullable=False)
    brand = Column(String(50), nullable=False)
    model = Column(String(50), nullable=False)
    entered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# Create the tables in Postgres if they don't exist yet
Base.metadata.create_all(engine)

# --------------------------------------------------------------------------- #
# 3. DATA SHAPES (what the browser sends us)
# --------------------------------------------------------------------------- #
class FloorIn(BaseModel):
    floor_number: int
    capacity: int


class CapacityUpdate(BaseModel):
    capacity: int


class VehicleIn(BaseModel):
    number_plate: str
    vehicle_type: str
    colour: str
    brand: str
    model: str


class VehicleEdit(BaseModel):
    # Everything is optional so you only send the fields you want to change
    number_plate: Optional[str] = None
    vehicle_type: Optional[str] = None
    colour: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    floor_number: Optional[int] = None  # send this to move the vehicle to another floor


# --------------------------------------------------------------------------- #
# 4. SMALL HELPER FUNCTIONS
# --------------------------------------------------------------------------- #
def get_db():
    """Gives each request its own database session, and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def clean_plate(plate):
    """' dl 3c ab 1234 ' -> 'DL3CAB1234'"""
    plate = plate.strip().upper().replace(" ", "")
    if plate == "":
        raise HTTPException(422, "Number plate cannot be empty")
    return plate


def find_floor(db, floor_number, lock=False):
    """Look up a floor by its number, or return a 404 error if it doesn't exist.
    lock=True stops two people from taking the last free spot at the same time."""
    query = db.query(Floor).filter(Floor.floor_number == floor_number)
    if lock:
        query = query.with_for_update()
    floor = query.first()
    if floor is None:
        raise HTTPException(404, f"Floor {floor_number} does not exist")
    return floor


def find_vehicle(db, plate):
    """Look up a vehicle by number plate, or return a 404 error."""
    vehicle = db.query(Vehicle).filter(Vehicle.number_plate == clean_plate(plate)).first()
    if vehicle is None:
        raise HTTPException(404, f"No vehicle with plate {plate}")
    return vehicle


def count_vehicles(db, floor):
    """How many vehicles are parked on this floor right now."""
    return db.query(Vehicle).filter(Vehicle.floor_id == floor.id).count()


def floor_info(db, floor):
    """Turn a Floor row into the dictionary the browser expects."""
    occupied = count_vehicles(db, floor)
    return {
        "floor_number": floor.floor_number,
        "capacity": floor.capacity,
        "occupied": occupied,
        "available": floor.capacity - occupied,
    }


def vehicle_info(db, vehicle):
    """Turn a Vehicle row into the dictionary the browser expects."""
    floor = db.query(Floor).filter(Floor.id == vehicle.floor_id).first()
    return {
        "number_plate": vehicle.number_plate,
        "vehicle_type": vehicle.vehicle_type,
        "colour": vehicle.colour,
        "brand": vehicle.brand,
        "model": vehicle.model,
        "floor_number": floor.floor_number,
        "entered_at": vehicle.entered_at,
    }


# --------------------------------------------------------------------------- #
# 5. THE APP
# --------------------------------------------------------------------------- #
app = FastAPI(title="Parking Lot Management")


# ---------------------------- FLOORS ---------------------------------------- #
@app.post("/floors", status_code=201)
def create_floors(floors: list[FloorIn], db=Depends(get_db)):
    """Create one or more floors, each with its own max capacity."""
    new_floors = []
    seen_numbers = []

    for item in floors:
        if item.capacity <= 0:
            raise HTTPException(422, "Capacity must be at least 1")
        if item.floor_number in seen_numbers:
            raise HTTPException(422, f"Floor {item.floor_number} appears twice in the request")
        if db.query(Floor).filter(Floor.floor_number == item.floor_number).first():
            raise HTTPException(409, f"Floor {item.floor_number} already exists")

        seen_numbers.append(item.floor_number)
        new_floors.append(Floor(floor_number=item.floor_number, capacity=item.capacity))

    db.add_all(new_floors)
    db.commit()
    return [floor_info(db, f) for f in new_floors]


@app.get("/floors")
def list_floors(db=Depends(get_db)):
    floors = db.query(Floor).order_by(Floor.floor_number).all()
    return [floor_info(db, f) for f in floors]


@app.get("/floors/{floor_number}")
def read_floor(floor_number: int, db=Depends(get_db)):
    return floor_info(db, find_floor(db, floor_number))


@app.patch("/floors/{floor_number}")
def change_capacity(floor_number: int, body: CapacityUpdate, db=Depends(get_db)):
    floor = find_floor(db, floor_number, lock=True)
    occupied = count_vehicles(db, floor)

    if body.capacity <= 0:
        raise HTTPException(422, "Capacity must be at least 1")
    if body.capacity < occupied:
        raise HTTPException(409, f"Cannot set capacity below current occupancy ({occupied})")

    floor.capacity = body.capacity
    db.commit()
    return floor_info(db, floor)


@app.delete("/floors/{floor_number}", status_code=204)
def delete_floor(floor_number: int, force: bool = False, db=Depends(get_db)):
    """Delete a floor. If vehicles are parked there, you must pass ?force=true."""
    floor = find_floor(db, floor_number, lock=True)
    occupied = count_vehicles(db, floor)

    if occupied > 0 and not force:
        raise HTTPException(409, f"Floor has {occupied} vehicle(s). Pass ?force=true to delete anyway.")

    # Delete the vehicles on this floor first, then the floor itself
    db.query(Vehicle).filter(Vehicle.floor_id == floor.id).delete()
    db.delete(floor)
    db.commit()


# ---------------------------- VEHICLES -------------------------------------- #
@app.post("/floors/{floor_number}/vehicles", status_code=201)
def add_vehicle(floor_number: int, body: VehicleIn, db=Depends(get_db)):
    floor = find_floor(db, floor_number, lock=True)
    plate = clean_plate(body.number_plate)

    # Is there still room on this floor?
    if count_vehicles(db, floor) >= floor.capacity:
        raise HTTPException(409, f"Floor {floor_number} is full")

    # Is this car already parked somewhere?
    if db.query(Vehicle).filter(Vehicle.number_plate == plate).first():
        raise HTTPException(409, f"Vehicle {plate} is already parked")

    vehicle = Vehicle(
        floor_id=floor.id,
        number_plate=plate,
        vehicle_type=body.vehicle_type,
        colour=body.colour,
        brand=body.brand,
        model=body.model,
    )
    db.add(vehicle)
    db.commit()
    return vehicle_info(db, vehicle)


@app.get("/floors/{floor_number}/vehicles")
def list_vehicles(floor_number: int, db=Depends(get_db)):
    floor = find_floor(db, floor_number)
    vehicles = db.query(Vehicle).filter(Vehicle.floor_id == floor.id).order_by(Vehicle.entered_at).all()
    return [vehicle_info(db, v) for v in vehicles]


@app.get("/vehicles/{number_plate}")
def read_vehicle(number_plate: str, db=Depends(get_db)):
    return vehicle_info(db, find_vehicle(db, number_plate))


@app.patch("/vehicles/{number_plate}")
def edit_vehicle(number_plate: str, body: VehicleEdit, db=Depends(get_db)):
    vehicle = find_vehicle(db, number_plate)

    # Change the plate (if a new one was sent)
    if body.number_plate is not None:
        new_plate = clean_plate(body.number_plate)
        if new_plate != vehicle.number_plate:
            if db.query(Vehicle).filter(Vehicle.number_plate == new_plate).first():
                raise HTTPException(409, "That number plate is already in use")
            vehicle.number_plate = new_plate

    # Change the other details (if sent)
    if body.vehicle_type is not None:
        vehicle.vehicle_type = body.vehicle_type
    if body.colour is not None:
        vehicle.colour = body.colour
    if body.brand is not None:
        vehicle.brand = body.brand
    if body.model is not None:
        vehicle.model = body.model

    # Move to another floor (if a different floor number was sent)
    if body.floor_number is not None:
        current_floor = db.query(Floor).filter(Floor.id == vehicle.floor_id).first()
        if body.floor_number != current_floor.floor_number:
            new_floor = find_floor(db, body.floor_number, lock=True)
            if count_vehicles(db, new_floor) >= new_floor.capacity:
                raise HTTPException(409, f"Floor {body.floor_number} is full")
            vehicle.floor_id = new_floor.id

    db.commit()
    return vehicle_info(db, vehicle)


@app.delete("/vehicles/{number_plate}", status_code=204)
def remove_vehicle(number_plate: str, db=Depends(get_db)):
    vehicle = find_vehicle(db, number_plate)
    db.delete(vehicle)
    db.commit()


# --------------------------------------------------------------------------- #
# 6. SERVE THE WEBSITE (keep this at the bottom!)
# --------------------------------------------------------------------------- #
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
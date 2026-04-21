from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Float, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import List, Optional
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
import uuid

DATABASE_URL = "postgresql://postgres:pawcare123@localhost:5432/pawcare_db"
SECRET_KEY = "pawcare-secret-key-2024"
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class User(Base):
    __tablename__ = "users"
    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = Column(String, unique=True, nullable=False, index=True)
    name          = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    pets          = relationship("Pet", back_populates="owner")

class Pet(Base):
    __tablename__ = "pets"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id   = Column(String, ForeignKey("users.id"), nullable=False)
    name       = Column(String, nullable=False)
    breed      = Column(String)
    birth_date = Column(String)
    sex        = Column(String)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    owner          = relationship("User", back_populates="pets")
    health_records = relationship("HealthRecord", back_populates="pet")
    weight_logs    = relationship("WeightLog", back_populates="pet")

class HealthRecord(Base):
    __tablename__ = "health_records"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id      = Column(String, ForeignKey("pets.id"), nullable=False)
    record_type = Column(String, nullable=False)
    title       = Column(String, nullable=False)
    description = Column(Text)
    record_date = Column(String, nullable=False)
    next_date   = Column(String)
    created_at  = Column(DateTime, default=datetime.utcnow)
    pet         = relationship("Pet", back_populates="health_records")

class WeightLog(Base):
    __tablename__ = "weight_logs"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id      = Column(String, ForeignKey("pets.id"), nullable=False)
    weight_kg   = Column(Float, nullable=False)
    measured_at = Column(DateTime, default=datetime.utcnow)
    pet         = relationship("Pet", back_populates="weight_logs")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PawCare API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security    = HTTPBearer()

def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Неверный токен")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: str
    name: str
    email: str

class PetCreate(BaseModel):
    name: str
    breed: Optional[str] = None
    birth_date: Optional[str] = None
    sex: Optional[str] = None

class PetResponse(BaseModel):
    id: str
    name: str
    breed: Optional[str] = None
    birth_date: Optional[str] = None
    sex: Optional[str] = None

class HealthRecordCreate(BaseModel):
    record_type: str
    title: str
    description: Optional[str] = None
    record_date: str
    next_date: Optional[str] = None

class HealthRecordResponse(BaseModel):
    id: str
    record_type: str
    title: str
    description: Optional[str] = None
    record_date: str
    next_date: Optional[str] = None

class WeightCreate(BaseModel):
    weight_kg: float

class WeightResponse(BaseModel):
    id: str
    weight_kg: float
    measured_at: str

@app.get("/")
def root():
    return {"message": "PawCare API работает!", "version": "1.0.0"}

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/v1/auth/register", response_model=TokenResponse)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=400, detail="Email уже занят")
    user = User(
        email=request.email,
        name=request.name,
        password_hash=pwd_context.hash(request.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id,
        name=user.name,
        email=user.email,
    )

@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not pwd_context.verify(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id,
        name=user.name,
        email=user.email,
    )

@app.get("/api/v1/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.id, "name": current_user.name, "email": current_user.email}

@app.get("/api/v1/pets", response_model=List[PetResponse])
def get_pets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pets = db.query(Pet).filter(Pet.owner_id == current_user.id, Pet.is_deleted == False).all()
    return [PetResponse(id=p.id, name=p.name, breed=p.breed, birth_date=p.birth_date, sex=p.sex) for p in pets]

@app.post("/api/v1/pets", response_model=PetResponse)
def create_pet(data: PetCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = Pet(owner_id=current_user.id, name=data.name, breed=data.breed, birth_date=data.birth_date, sex=data.sex)
    db.add(pet)
    db.commit()
    db.refresh(pet)
    return PetResponse(id=pet.id, name=pet.name, breed=pet.breed, birth_date=pet.birth_date, sex=pet.sex)

@app.delete("/api/v1/pets/{pet_id}")
def delete_pet(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    pet.is_deleted = True
    db.commit()
    return {"message": "Питомец удалён"}

@app.get("/api/v1/pets/{pet_id}/health", response_model=List[HealthRecordResponse])
def get_health(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    records = db.query(HealthRecord).filter(HealthRecord.pet_id == pet_id).order_by(HealthRecord.record_date.desc()).all()
    return [HealthRecordResponse(id=r.id, record_type=r.record_type, title=r.title, description=r.description, record_date=r.record_date, next_date=r.next_date) for r in records]

@app.post("/api/v1/pets/{pet_id}/health", response_model=HealthRecordResponse)
def add_health(pet_id: str, data: HealthRecordCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    record = HealthRecord(pet_id=pet_id, record_type=data.record_type, title=data.title, description=data.description, record_date=data.record_date, next_date=data.next_date)
    db.add(record)
    db.commit()
    db.refresh(record)
    return HealthRecordResponse(id=record.id, record_type=record.record_type, title=record.title, description=record.description, record_date=record.record_date, next_date=record.next_date)

@app.get("/api/v1/pets/{pet_id}/weight", response_model=List[WeightResponse])
def get_weight(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.q
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.database import get_db
from app.models import HealthRecord, WeightLog, Pet, User
from app.config import settings
import uuid

router = APIRouter(tags=["health"])
security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Неверный токен")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

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
    description: Optional[str]
    record_date: str
    next_date: Optional[str]

class WeightCreate(BaseModel):
    weight_kg: float

class WeightResponse(BaseModel):
    id: str
    weight_kg: float
    measured_at: str

@router.get("/pets/{pet_id}/health", response_model=List[HealthRecordResponse])
def get_health_records(
    pet_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pet = db.query(Pet).filter(
        Pet.id == pet_id,
        Pet.owner_id == current_user.id
    ).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    records = db.query(HealthRecord).filter(
        HealthRecord.pet_id == pet_id
    ).order_by(HealthRecord.record_date.desc()).all()
    return [HealthRecordResponse(
        id=str(r.id),
        record_type=r.record_type,
        title=r.title,
        description=r.description,
        record_date=r.record_date,
        next_date=r.next_date
    ) for r in records]

@router.post("/pets/{pet_id}/health", response_model=HealthRecordResponse)
def add_health_record(
    pet_id: str,
    data: HealthRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pet = db.query(Pet).filter(
        Pet.id == pet_id,
        Pet.owner_id == current_user.id
    ).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    record = HealthRecord(
        id=uuid.uuid4(),
        pet_id=pet_id,
        record_type=data.record_type,
        title=data.title,
        description=data.description,
        record_date=data.record_date,
        next_date=data.next_date,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return HealthRecordResponse(
        id=str(record.id),
        record_type=record.record_type,
        title=record.title,
        description=record.description,
        record_date=record.record_date,
        next_date=record.next_date
    )

@router.get("/pets/{pet_id}/weight", response_model=List[WeightResponse])
def get_weight_logs(
    pet_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pet = db.query(Pet).filter(
        Pet.id == pet_id,
        Pet.owner_id == current_user.id
    ).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    logs = db.query(WeightLog).filter(
        WeightLog.pet_id == pet_id
    ).order_by(WeightLog.measured_at.desc()).all()
    return [WeightResponse(
        id=str(l.id),
        weight_kg=l.weight_kg,
        measured_at=str(l.measured_at)
    ) for l in logs]

@router.post("/pets/{pet_id}/weight", response_model=WeightResponse)
def add_weight(
    pet_id: str,
    data: WeightCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pet = db.query(Pet).filter(
        Pet.id == pet_id,
        Pet.owner_id == current_user.id
    ).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    log = WeightLog(
        id=uuid.uuid4(),
        pet_id=pet_id,
        weight_kg=data.weight_kg,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return WeightResponse(
        id=str(log.id),
        weight_kg=log.weight_kg,
        measured_at=str(log.measured_at)
    )
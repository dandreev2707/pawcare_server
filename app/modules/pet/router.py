from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.database import get_db
from app.models import Pet, User
from app.config import settings
import uuid

router = APIRouter(prefix="/pets", tags=["pets"])
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
        if not user_id:
            raise HTTPException(status_code=401, detail="Неверный токен")
    except JWTError:
        raise HTTPException(status_code=401, detail="Неверный токен")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

class PetCreate(BaseModel):
    name: str
    breed: Optional[str] = None
    birth_date: Optional[str] = None
    sex: Optional[str] = None

class PetResponse(BaseModel):
    id: str
    name: str
    breed: Optional[str]
    birth_date: Optional[str]
    sex: Optional[str]

    class Config:
        from_attributes = True

@router.get("", response_model=List[PetResponse])
def get_pets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pets = db.query(Pet).filter(
        Pet.owner_id == current_user.id,
        Pet.is_deleted == False
    ).all()
    return [PetResponse(
        id=str(p.id),
        name=p.name,
        breed=p.breed,
        birth_date=p.birth_date,
        sex=p.sex
    ) for p in pets]

@router.post("", response_model=PetResponse)
def create_pet(
    pet_data: PetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pet = Pet(
        id=uuid.uuid4(),
        owner_id=current_user.id,
        name=pet_data.name,
        breed=pet_data.breed,
        birth_date=pet_data.birth_date,
        sex=pet_data.sex,
    )
    db.add(pet)
    db.commit()
    db.refresh(pet)
    return PetResponse(
        id=str(pet.id),
        name=pet.name,
        breed=pet.breed,
        birth_date=pet.birth_date,
        sex=pet.sex
    )

@router.delete("/{pet_id}")
def delete_pet(
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
    pet.is_deleted = True
    db.commit()
    return {"message": "Питомец удалён"}
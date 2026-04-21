from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta
from app.database import get_db
from app.models import User
from app.config import settings
import uuid

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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

def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    data = {"sub": user_id, "exp": expire}
    return jwt.encode(data, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

@router.post("/register", response_model=TokenResponse)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == request.email).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким email уже существует"
        )
    hashed = pwd_context.hash(request.password)
    user = User(
        id=uuid.uuid4(),
        email=request.email,
        name=request.name,
        password_hash=hashed,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(str(user.id))
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=str(user.id),
        name=user.name,
        email=user.email,
    )

@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not pwd_context.verify(request.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Неверный email или пароль"
        )
    token = create_token(str(user.id))
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=str(user.id),
        name=user.name,
        email=user.email,
    )
from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Float, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import List, Optional
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, date
import uuid
import os
import shutil
import httpx

# ── Настройки ──────────────────────────────────────────
DATABASE_URL        = "postgresql://postgres:pawcare123@localhost:5432/pawcare_db"
SECRET_KEY          = "pawcare-secret-key-2024"
ALGORITHM           = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
UPLOAD_DIR          = "uploads"
YANDEX_API_KEY      = "1ca7aeee-1cc2-43ca-96f7-81a6efa139d3"

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── База данных ─────────────────────────────────────────
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── Модели таблиц ───────────────────────────────────────
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
    photo_url  = Column(String)
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

class Reminder(Base):
    __tablename__ = "reminders"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id     = Column(String, ForeignKey("pets.id"), nullable=False)
    user_id    = Column(String, ForeignKey("users.id"), nullable=False)
    title      = Column(String, nullable=False)
    remind_at  = Column(String, nullable=False)
    is_done    = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class TelegramUser(Base):
    __tablename__ = "telegram_users"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    chat_id    = Column(String, nullable=False)
    username   = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# Создаём все таблицы
Base.metadata.create_all(bind=engine)

# ── Приложение ──────────────────────────────────────────
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

# ── Вспомогательные функции ─────────────────────────────
def create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": user_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload  = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id  = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Неверный токен")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

# ── Pydantic схемы ──────────────────────────────────────
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
    breed:      Optional[str] = None
    birth_date: Optional[str] = None
    sex:        Optional[str] = None

class PetResponse(BaseModel):
    id: str
    name: str
    breed:      Optional[str] = None
    birth_date: Optional[str] = None
    sex:        Optional[str] = None
    photo_url:  Optional[str] = None  

class HealthRecordCreate(BaseModel):
    record_type: str
    title: str
    description: Optional[str] = None
    record_date: str
    next_date:   Optional[str] = None

class HealthRecordResponse(BaseModel):
    id: str
    record_type: str
    title: str
    description: Optional[str] = None
    record_date: str
    next_date:   Optional[str] = None

class WeightCreate(BaseModel):
    weight_kg: float

class WeightResponse(BaseModel):
    id: str
    weight_kg: float
    measured_at: str

class ReminderCreate(BaseModel):
    pet_id:    str
    title:     str
    remind_at: str

# ── Эндпоинты ───────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "PawCare API работает!", "version": "1.0.0"}

@app.get("/api/health")
def health_check():
    return {"status": "ok"}

# AUTH
@app.post("/api/v1/auth/register", response_model=TokenResponse)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=400, detail="Email уже занят")
    user = User(
        email=request.email,
        name=request.name,
        password_hash=pwd_context.hash(request.password),
    )
    db.add(user); db.commit(); db.refresh(user)
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id, name=user.name, email=user.email,
    )

@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not pwd_context.verify(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id, name=user.name, email=user.email,
    )

@app.get("/api/v1/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.id, "name": current_user.name, "email": current_user.email}

# PETS
@app.get("/api/v1/pets", response_model=List[PetResponse])
def get_pets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pets = db.query(Pet).filter(Pet.owner_id == current_user.id, Pet.is_deleted == False).all()
    return [PetResponse(
        id=p.id, name=p.name, breed=p.breed,
        birth_date=p.birth_date, sex=p.sex, photo_url=p.photo_url
    ) for p in pets]

@app.post("/api/v1/pets", response_model=PetResponse)
def create_pet(data: PetCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = Pet(owner_id=current_user.id, name=data.name, breed=data.breed,
              birth_date=data.birth_date, sex=data.sex)
    db.add(pet); db.commit(); db.refresh(pet)
    return PetResponse(id=pet.id, name=pet.name, breed=pet.breed,
                       birth_date=pet.birth_date, sex=pet.sex, photo_url=pet.photo_url)

@app.delete("/api/v1/pets/{pet_id}")
def delete_pet(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    pet.is_deleted = True
    db.commit()
    return {"message": "Питомец удалён"}

@app.post("/api/v1/pets/{pet_id}/photo")
async def upload_pet_photo(
    pet_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    ext      = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"{pet_id}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    pet.photo_url = f"/uploads/{filename}"
    db.commit()
    return {"photo_url": pet.photo_url}

@app.get("/uploads/{filename}")
async def get_upload(filename: str):
    filepath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(filepath)

# HEALTH
@app.get("/api/v1/pets/{pet_id}/health", response_model=List[HealthRecordResponse])
def get_health(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    records = db.query(HealthRecord).filter(
        HealthRecord.pet_id == pet_id
    ).order_by(HealthRecord.record_date.desc()).all()
    return [HealthRecordResponse(
        id=r.id, record_type=r.record_type, title=r.title,
        description=r.description, record_date=r.record_date, next_date=r.next_date
    ) for r in records]

@app.post("/api/v1/pets/{pet_id}/health", response_model=HealthRecordResponse)
def add_health(pet_id: str, data: HealthRecordCreate,
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    record = HealthRecord(
        pet_id=pet_id, record_type=data.record_type, title=data.title,
        description=data.description, record_date=data.record_date, next_date=data.next_date
    )
    db.add(record); db.commit(); db.refresh(record)
    return HealthRecordResponse(
        id=record.id, record_type=record.record_type, title=record.title,
        description=record.description, record_date=record.record_date, next_date=record.next_date
    )

@app.delete("/api/v1/pets/{pet_id}/health/{record_id}")
def delete_health_record(pet_id: str, record_id: str,
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    record = db.query(HealthRecord).filter(
        HealthRecord.id == record_id, HealthRecord.pet_id == pet_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(record); db.commit()
    return {"message": "Запись удалена"}

# WEIGHT
@app.get("/api/v1/pets/{pet_id}/weight", response_model=List[WeightResponse])
def get_weight(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    logs = db.query(WeightLog).filter(
        WeightLog.pet_id == pet_id
    ).order_by(WeightLog.measured_at.desc()).all()
    return [WeightResponse(id=l.id, weight_kg=l.weight_kg, measured_at=str(l.measured_at)) for l in logs]

@app.post("/api/v1/pets/{pet_id}/weight", response_model=WeightResponse)
def add_weight(pet_id: str, data: WeightCreate,
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    log = WeightLog(pet_id=pet_id, weight_kg=data.weight_kg)
    db.add(log); db.commit(); db.refresh(log)
    return WeightResponse(id=log.id, weight_kg=log.weight_kg, measured_at=str(log.measured_at))

# REMINDERS
@app.get("/api/v1/reminders")
def get_reminders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    today     = date.today()
    yesterday = today - timedelta(days=1)

    pets = db.query(Pet).filter(
        Pet.owner_id == current_user.id, Pet.is_deleted == False
    ).all()

    reminders = []

    # Из медицинских записей
    for pet in pets:
        records = db.query(HealthRecord).filter(
            HealthRecord.pet_id == pet.id,
            HealthRecord.next_date != None
        ).all()
        for r in records:
            try:
                record_date = date.fromisoformat(r.next_date)
            except Exception:
                continue
            if record_date < yesterday:
                continue
            reminders.append({
                "id":          None,
                "pet_name":    pet.name,
                "pet_id":      str(pet.id),
                "record_type": r.record_type,
                "title":       r.title,
                "next_date":   r.next_date,
                "remind_at":   r.next_date,
                "source":      "health_record",
            })

    # Пользовательские
    custom = db.query(Reminder).filter(Reminder.user_id == current_user.id).all()
    for r in custom:
        pet = db.query(Pet).filter(Pet.id == r.pet_id).first()
        reminders.append({
            "id":          r.id,
            "pet_name":    pet.name if pet else "Питомец",
            "pet_id":      r.pet_id,
            "record_type": "custom",
            "title":       r.title,
            "next_date":   r.remind_at,
            "remind_at":   r.remind_at,
            "source":      "custom",
        })

    reminders.sort(key=lambda x: x["remind_at"] or "")
    return reminders

@app.post("/api/v1/reminders")
def create_reminder(data: ReminderCreate,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder = Reminder(
        pet_id=data.pet_id, user_id=current_user.id,
        title=data.title, remind_at=data.remind_at,
    )
    db.add(reminder); db.commit(); db.refresh(reminder)
    return {"id": reminder.id, "title": reminder.title,
            "remind_at": reminder.remind_at, "pet_id": reminder.pet_id}

@app.delete("/api/v1/reminders/{reminder_id}")
def delete_reminder(reminder_id: str,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id, Reminder.user_id == current_user.id
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    db.delete(reminder); db.commit()
    return {"message": "Напоминание удалено"}

# MAP
@app.get("/api/v1/map/vets")
async def get_vets(lat: float, lon: float, current_user: User = Depends(get_current_user)):
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": "ветеринарная клиника",
        "format": "json",
        "limit": 15,
        "addressdetails": 1,
        "viewbox": f"{lon-0.1},{lat+0.1},{lon+0.1},{lat-0.1}",
        "bounded": 1,
    }
    headers = {"User-Agent": "PawCare/1.0"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params,
                                        headers=headers, timeout=10)
            data = response.json()
            clinics = []
            for item in data:
                addr = item.get("address", {})
                road    = addr.get("road", "")
                house   = addr.get("house_number", "")
                city    = addr.get("city", addr.get("town", addr.get("village", "")))
                address = f"{road} {house}, {city}".strip(", ")
                clinics.append({
                    "name":    item.get("display_name", "Ветклиника").split(",")[0],
                    "address": address or item.get("display_name", "Адрес не указан"),
                    "phone":   "Уточните по телефону",
                    "hours":   "Уточните режим работы",
                    "lat":     float(item.get("lat", lat)),
                    "lon":     float(item.get("lon", lon)),
                })
            return clinics
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка поиска: {str(e)}")

# ── TELEGRAM BOT ────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_ЗДЕСЬ"

class TelegramLinkRequest(BaseModel):
    chat_id: str
    username: Optional[str] = None
    link_code: str

# Хранилище кодов привязки (в памяти)
link_codes: dict = {}

@app.post("/api/v1/telegram/generate-code")
def generate_link_code(current_user: User = Depends(get_current_user)):
    import random
    import string
    code = ''.join(random.choices(string.digits, k=6))
    link_codes[code] = current_user.id
    return {"code": code}

@app.post("/api/v1/telegram/link")
def link_telegram(
    request: TelegramLinkRequest,
    db: Session = Depends(get_db)
):
    user_id = link_codes.get(request.link_code)
    if not user_id:
        raise HTTPException(status_code=400, detail="Неверный код или код устарел")

    existing = db.query(TelegramUser).filter(
        TelegramUser.user_id == user_id
    ).first()
    if existing:
        existing.chat_id = request.chat_id
        existing.username = request.username
    else:
        tg_user = TelegramUser(
            user_id=user_id,
            chat_id=request.chat_id,
            username=request.username,
        )
        db.add(tg_user)
    db.commit()
    del link_codes[request.link_code]
    return {"message": "Аккаунт успешно привязан!"}

@app.delete("/api/v1/telegram/unlink")
def unlink_telegram(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tg = db.query(TelegramUser).filter(
        TelegramUser.user_id == current_user.id
    ).first()
    if tg:
        db.delete(tg)
        db.commit()
    return {"message": "Telegram отвязан"}

@app.get("/api/v1/telegram/status")
def telegram_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tg = db.query(TelegramUser).filter(
        TelegramUser.user_id == current_user.id
    ).first()
    return {
        "linked": tg is not None,
        "username": tg.username if tg else None,
    }

@app.get("/api/v1/telegram/pets")
def telegram_get_pets(chat_id: str, db: Session = Depends(get_db)):
    tg = db.query(TelegramUser).filter(
        TelegramUser.chat_id == chat_id
    ).first()
    if not tg:
        raise HTTPException(status_code=404, detail="Аккаунт не привязан")
    pets = db.query(Pet).filter(
        Pet.owner_id == tg.user_id,
        Pet.is_deleted == False
    ).all()
    return [{"id": p.id, "name": p.name, "breed": p.breed, "sex": p.sex} for p in pets]

@app.get("/api/v1/telegram/reminders")
def telegram_get_reminders(chat_id: str, db: Session = Depends(get_db)):
    tg = db.query(TelegramUser).filter(
        TelegramUser.chat_id == chat_id
    ).first()
    if not tg:
        raise HTTPException(status_code=404, detail="Аккаунт не привязан")

    today = date.today()
    yesterday = today - timedelta(days=1)
    pets = db.query(Pet).filter(
        Pet.owner_id == tg.user_id,
        Pet.is_deleted == False
    ).all()

    reminders = []
    for pet in pets:
        records = db.query(HealthRecord).filter(
            HealthRecord.pet_id == pet.id,
            HealthRecord.next_date != None
        ).all()
        for r in records:
            try:
                record_date = date.fromisoformat(r.next_date)
            except Exception:
                continue
            if record_date < yesterday:
                continue
            reminders.append({
                "pet_name": pet.name,
                "record_type": r.record_type,
                "title": r.title,
                "remind_at": r.next_date,
            })

    custom = db.query(Reminder).filter(
        Reminder.user_id == tg.user_id
    ).all()
    for r in custom:
        pet = db.query(Pet).filter(Pet.id == r.pet_id).first()
        reminders.append({
            "pet_name": pet.name if pet else "Питомец",
            "record_type": "custom",
            "title": r.title,
            "remind_at": r.remind_at,
        })

    reminders.sort(key=lambda x: x["remind_at"] or "")
    return reminders

@app.delete("/api/v1/telegram/unlink-by-chat")
def unlink_by_chat(chat_id: str, db: Session = Depends(get_db)):
    tg = db.query(TelegramUser).filter(
        TelegramUser.chat_id == chat_id
    ).first()
    if not tg:
        raise HTTPException(status_code=404, detail="Аккаунт не привязан")
    db.delete(tg)
    db.commit()
    return {"message": "Отвязано"}
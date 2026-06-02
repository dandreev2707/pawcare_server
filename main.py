from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, HTMLResponse
from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Float, Text, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import List, Optional
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, date, timezone
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import uuid
import os
import random
import string
import shutil
import httpx
import io
from fpdf import FPDF
import cloudinary
import cloudinary.uploader

load_dotenv()

# Настройки
DATABASE_URL        = os.getenv("DATABASE_URL", "")
# Railway выдаёт postgres://, SQLAlchemy 2.x требует postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
SECRET_KEY          = os.getenv("SECRET_KEY")
ALGORITHM           = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
UPLOAD_DIR          = "uploads"
YANDEX_API_KEY      = os.getenv("YANDEX_API_KEY", "")
GOOGLE_CLIENT_ID    = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8001/api/v1/auth/google/callback")
BOT_SECRET          = os.getenv("BOT_SECRET", "")

os.makedirs(UPLOAD_DIR, exist_ok=True)

CLOUDINARY_CLOUD_NAME  = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY_VAL = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET  = os.getenv("CLOUDINARY_API_SECRET", "")

if CLOUDINARY_CLOUD_NAME:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY_VAL,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )

# База данных
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Модели таблиц
class User(Base):
    __tablename__ = "users"
    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = Column(String, unique=True, nullable=False, index=True)
    name          = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)
    auth_provider = Column(String, default='email')
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    owner          = relationship("User", back_populates="pets")
    health_records = relationship("HealthRecord", back_populates="pet")
    weight_logs    = relationship("WeightLog", back_populates="pet")
    heat_cycles    = relationship("HeatCycle", back_populates="pet")

class HealthRecord(Base):
    __tablename__ = "health_records"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id      = Column(String, ForeignKey("pets.id"), nullable=False)
    record_type = Column(String, nullable=False)
    title       = Column(String, nullable=False)
    description = Column(Text)
    record_date = Column(String, nullable=False)
    next_date   = Column(String)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    pet         = relationship("Pet", back_populates="health_records")

class WeightLog(Base):
    __tablename__ = "weight_logs"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id      = Column(String, ForeignKey("pets.id"), nullable=False)
    weight_kg   = Column(Float, nullable=False)
    measured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    pet         = relationship("Pet", back_populates="weight_logs")

class Reminder(Base):
    __tablename__ = "reminders"
    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id      = Column(String, ForeignKey("pets.id"), nullable=False)
    user_id     = Column(String, ForeignKey("users.id"), nullable=False)
    title       = Column(String, nullable=False)
    remind_at   = Column(String, nullable=False)
    is_done     = Column(Boolean, default=False)
    repeat_rule = Column(String)  # None | 'weekly' | 'monthly' | 'yearly'
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class TelegramUser(Base):
    __tablename__ = "telegram_users"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String, ForeignKey("users.id"), nullable=False, unique=True)
    chat_id    = Column(String, nullable=False)
    username   = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class HeatCycle(Base):
    __tablename__ = "heat_cycles"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pet_id     = Column(String, ForeignKey("pets.id"), nullable=False)
    started_at = Column(String, nullable=False)
    ended_at   = Column(String)
    notes      = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    pet        = relationship("Pet", back_populates="heat_cycles")

class TelegramLoginCode(Base):
    __tablename__ = "telegram_login_codes"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    chat_id    = Column(String, nullable=False, index=True)
    code       = Column(String, nullable=False, unique=True)
    is_used    = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class GoogleOAuthState(Base):
    __tablename__ = "google_oauth_states"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    state      = Column(String, nullable=False, unique=True)
    jwt_token  = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# Создаём все таблицы
Base.metadata.create_all(bind=engine)

# Миграция: обновляем существующую БД
with engine.connect() as _conn:
    _conn.execute(text("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL"))
    _conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR DEFAULT 'email'"))
    _conn.commit()

# Приложение
app = FastAPI(title="PawCare API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
security    = HTTPBearer()

# Вспомогательные функции
def create_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
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

# Pydantic схемы
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

class PetUpdate(BaseModel):
    name:       Optional[str] = None
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
    pet_id:      str
    title:       str
    remind_at:   str
    repeat_rule: Optional[str] = None

class ReminderResponse(BaseModel):
    id: str
    pet_id: str
    title: str
    remind_at: str
    repeat_rule: Optional[str] = None

class HealthRecordUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    record_date: Optional[str] = None
    next_date:   Optional[str] = None

class GoogleCodeExchangeRequest(BaseModel):
    code: str

class TelegramLoginRequest(BaseModel):
    code: str

class TelegramLoginCodeRequest(BaseModel):
    chat_id:    str
    bot_secret: Optional[str] = None
    first_name: Optional[str] = None
    username:   Optional[str] = None

class HeatCycleCreate(BaseModel):
    started_at: str
    notes:      Optional[str] = None

class HeatCycleUpdate(BaseModel):
    started_at: Optional[str] = None
    ended_at:   Optional[str] = None
    notes:      Optional[str] = None

class HeatCycleResponse(BaseModel):
    id:         str
    started_at: str
    ended_at:   Optional[str] = None
    notes:      Optional[str] = None

# Эндпоинты

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
        auth_provider='email',
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id, name=user.name, email=user.email,
    )

@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not user.password_hash or not pwd_context.verify(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id, name=user.name, email=user.email,
    )

@app.get("/api/v1/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.id, "name": current_user.name, "email": current_user.email, "auth_provider": current_user.auth_provider or "email"}

# GOOGLE OAUTH
@app.get("/api/v1/auth/google/initiate")
def google_initiate(db: Session = Depends(get_db)):
    """Перенаправляет пользователя на страницу авторизации Google."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth не настроен (GOOGLE_CLIENT_ID отсутствует)")
    state = "".join(random.choices(string.ascii_letters + string.digits, k=32))
    db.add(GoogleOAuthState(state=state))
    db.commit()
    google_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        f"&state={state}"
    )
    return RedirectResponse(url=google_url)

@app.get("/api/v1/auth/google/callback")
async def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    """Принимает код от Google, выдаёт JWT и возвращает HTML-страницу с кодом."""
    oauth_state = db.query(GoogleOAuthState).filter(
        GoogleOAuthState.state == state,
        GoogleOAuthState.jwt_token == None,  # noqa
    ).first()
    if not oauth_state:
        raise HTTPException(status_code=400, detail="Неверный state параметр")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Ошибка обмена кода Google")
        token_data = token_resp.json()
        id_token   = token_data.get("id_token", "")

        info_resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
        )
        if info_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Неверный Google id_token")
        info = info_resp.json()

    email = info.get("email")
    name  = info.get("name") or (email.split("@")[0] if email else "User")
    if not email:
        raise HTTPException(status_code=400, detail="Email не получен от Google")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            name=name,
            auth_provider='google',
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    jwt_token = create_token(user.id)
    oauth_state.jwt_token = jwt_token
    db.commit()

    # Показываем короткий state-код (первые 8 символов) для ввода в приложении
    display_code = state[:8]
    return HTMLResponse(content=f"""
    <html><head><meta charset="utf-8"><title>PawCare — авторизация</title>
    <style>body{{font-family:sans-serif;display:flex;flex-direction:column;align-items:center;
    justify-content:center;min-height:100vh;background:#f0faf4;margin:0}}
    .card{{background:white;border-radius:16px;padding:40px;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
    h2{{color:#2C6E49}} .code{{font-size:32px;font-weight:700;letter-spacing:6px;color:#2C6E49;
    background:#E8F5EE;padding:16px 32px;border-radius:12px;margin:16px 0}}</style></head>
    <body><div class="card">
    <h2>✅ Авторизация через Google успешна!</h2>
    <p>Введите этот код в приложении PawCare:</p>
    <div class="code">{display_code}</div>
    <p style="color:#888;font-size:13px">Код действителен 10 минут</p>
    </div></body></html>
    """)

@app.post("/api/v1/auth/google/exchange", response_model=TokenResponse)
def google_exchange(req: GoogleCodeExchangeRequest, db: Session = Depends(get_db)):
    """Обменивает 8-символьный код на JWT токен."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    oauth_state = db.query(GoogleOAuthState).filter(
        GoogleOAuthState.state.like(f"{req.code}%"),
        GoogleOAuthState.jwt_token != None,  # noqa
        GoogleOAuthState.created_at > cutoff,
    ).first()
    if not oauth_state:
        raise HTTPException(status_code=401, detail="Неверный или устаревший код Google авторизации")

    payload = jwt.decode(oauth_state.jwt_token, SECRET_KEY, algorithms=[ALGORITHM])
    user_id = payload.get("sub")
    user    = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    db.delete(oauth_state)
    db.commit()
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id, name=user.name, email=user.email,
    )

# TELEGRAM LOGIN
@app.post("/api/v1/auth/telegram-login", response_model=TokenResponse)
def telegram_login(req: TelegramLoginRequest, db: Session = Depends(get_db)):
    """Вход по коду, полученному от Telegram-бота командой /login."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    login_code = db.query(TelegramLoginCode).filter(
        TelegramLoginCode.code == req.code,
        TelegramLoginCode.is_used == False,  # noqa
        TelegramLoginCode.created_at > cutoff,
    ).first()
    if not login_code:
        raise HTTPException(status_code=401, detail="Неверный или устаревший код")
    tg_user = db.query(TelegramUser).filter(
        TelegramUser.chat_id == login_code.chat_id
    ).first()
    if not tg_user:
        raise HTTPException(status_code=401, detail="Telegram аккаунт не привязан к PawCare")
    user = db.query(User).filter(User.id == tg_user.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    login_code.is_used = True
    db.commit()
    return TokenResponse(
        access_token=create_token(user.id),
        token_type="bearer",
        user_id=user.id, name=user.name, email=user.email,
    )

@app.post("/api/v1/telegram/generate-login-code")
def generate_telegram_login_code(req: TelegramLoginCodeRequest, db: Session = Depends(get_db)):
    """Генерирует 6-значный код входа для Telegram-бота (внутренний эндпоинт)."""
    if BOT_SECRET and req.bot_secret != BOT_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    tg_user = db.query(TelegramUser).filter(
        TelegramUser.chat_id == req.chat_id
    ).first()
    if not tg_user:
        # Авторегистрация: создаём аккаунт по Telegram ID
        name = req.first_name or req.username or "Telegram User"
        email = f"tg_{req.chat_id}@telegram.local"
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, name=name, auth_provider='telegram')
            db.add(user)
            db.commit()
            db.refresh(user)
        tg_user = TelegramUser(
            user_id=user.id,
            chat_id=req.chat_id,
            username=req.username,
        )
        db.add(tg_user)
        db.commit()
    code = "".join(random.choices(string.digits, k=6))
    db.add(TelegramLoginCode(chat_id=req.chat_id, code=code))
    db.commit()
    return {"code": code}

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
    if not data.name or not data.name.strip():
        raise HTTPException(status_code=422, detail="Имя питомца не может быть пустым")
    pet = Pet(owner_id=current_user.id, name=data.name.strip(), breed=data.breed,
              birth_date=data.birth_date, sex=data.sex)
    db.add(pet)
    db.commit()
    db.refresh(pet)
    return PetResponse(id=pet.id, name=pet.name, breed=pet.breed,
                       birth_date=pet.birth_date, sex=pet.sex, photo_url=pet.photo_url)

@app.put("/api/v1/pets/{pet_id}", response_model=PetResponse)
def update_pet(pet_id: str, data: PetUpdate,
               current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    if data.name is not None:
        pet.name = data.name
    if data.breed is not None:
        pet.breed = data.breed
    if data.birth_date is not None:
        pet.birth_date = data.birth_date
    if data.sex is not None:
        pet.sex = data.sex
    db.commit()
    db.refresh(pet)
    return PetResponse(id=pet.id, name=pet.name, breed=pet.breed,
                       birth_date=pet.birth_date, sex=pet.sex, photo_url=pet.photo_url)

@app.delete("/api/v1/pets/{pet_id}")
def delete_pet(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")

    # Удаляем все связанные данные
    db.query(HealthRecord).filter(HealthRecord.pet_id == pet_id).delete()
    db.query(WeightLog).filter(WeightLog.pet_id == pet_id).delete()
    db.query(Reminder).filter(Reminder.pet_id == pet_id).delete()
    db.query(HeatCycle).filter(HeatCycle.pet_id == pet_id).delete()

    # Удаляем фото: с Cloudinary или с диска
    if pet.photo_url:
        if pet.photo_url.startswith("http") and CLOUDINARY_CLOUD_NAME:
            try:
                cloudinary.uploader.destroy(f"pawcare/pets/{pet_id}")
            except Exception:
                pass
        elif pet.photo_url.startswith("/uploads/"):
            filepath = os.path.join(UPLOAD_DIR, os.path.basename(pet.photo_url))
            if os.path.exists(filepath):
                os.remove(filepath)

    db.delete(pet)
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
    contents = await file.read()

    if CLOUDINARY_CLOUD_NAME:
        # Cloudinary: сохраняем только в облаке, URL берём оттуда
        result = cloudinary.uploader.upload(
            contents,
            public_id=f"pawcare/pets/{pet_id}",
            overwrite=True,
            resource_type="image",
        )
        pet.photo_url = result["secure_url"]
    else:
        # Локальный режим: сохраняем на диск
        ext      = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        filename = f"{pet_id}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(contents)
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
    db.add(record)
    db.commit()
    db.refresh(record)
    return HealthRecordResponse(
        id=record.id, record_type=record.record_type, title=record.title,
        description=record.description, record_date=record.record_date, next_date=record.next_date
    )

@app.put("/api/v1/pets/{pet_id}/health/{record_id}", response_model=HealthRecordResponse)
def update_health_record(pet_id: str, record_id: str, data: HealthRecordUpdate,
                         current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    record = db.query(HealthRecord).filter(
        HealthRecord.id == record_id, HealthRecord.pet_id == pet_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if data.title is not None:
        record.title = data.title
    if data.description is not None:
        record.description = data.description
    if data.record_date is not None:
        record.record_date = data.record_date
    if data.next_date is not None:
        record.next_date = data.next_date
    db.commit()
    db.refresh(record)
    return HealthRecordResponse(
        id=record.id, record_type=record.record_type, title=record.title,
        description=record.description, record_date=record.record_date, next_date=record.next_date,
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
    db.delete(record)
    db.commit()
    return {"message": "Запись удалена"}

def _build_health_pdf(pet, records) -> bytes:
    type_labels = {
        "vaccination":   "Прививка",
        "deworming":     "Дегельминтизация",
        "antiparasitic": "Обработка от паразитов",
        "vet_visit":     "Визит к врачу",
        "chronic_disease": "Хроническое заболевание",
        "medication":    "Медикамент",
    }

    pdf = FPDF()
    pdf.add_page()

    font_path = os.path.join(os.path.dirname(__file__), "DejaVuSans.ttf")
    bold_path = os.path.join(os.path.dirname(__file__), "DejaVuSans-Bold.ttf")
    if os.path.exists(font_path):
        pdf.add_font("DejaVu", "", font_path, uni=True)
        pdf.add_font("DejaVu", "B", bold_path if os.path.exists(bold_path) else font_path, uni=True)
        base_font = "DejaVu"
    else:
        base_font = "Helvetica"

    pdf.set_font(base_font, "B", 18)
    pdf.cell(0, 12, f"Медицинская карта: {pet.name}", ln=True, align="C")
    pdf.set_font(base_font, "", 11)
    pdf.set_text_color(100, 100, 100)
    info_parts = []
    if pet.breed:
        info_parts.append(pet.breed)
    if pet.birth_date:
        info_parts.append(f"Дата рождения: {pet.birth_date}")
    if pet.sex:
        info_parts.append("Мальчик" if pet.sex == "male" else "Девочка")
    if info_parts:
        pdf.cell(0, 7, "  |  ".join(info_parts), ln=True, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.set_draw_color(44, 110, 73)
    pdf.set_line_width(0.8)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    if not records:
        pdf.set_font(base_font, "", 12)
        pdf.cell(0, 10, "Записи отсутствуют", ln=True, align="C")
    else:
        for r in records:
            label = type_labels.get(r.record_type, r.record_type)
            pdf.set_fill_color(232, 245, 238)
            pdf.set_font(base_font, "B", 12)
            pdf.cell(0, 8, f"{r.title}  [{label}]", ln=True, fill=True)
            pdf.set_font(base_font, "", 10)
            pdf.set_text_color(80, 80, 80)
            dates = f"Дата: {r.record_date}"
            if r.next_date:
                dates += f"   |   Следующая: {r.next_date}"
            pdf.cell(0, 6, dates, ln=True)
            if r.description:
                pdf.set_text_color(40, 40, 40)
                pdf.multi_cell(0, 6, r.description)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(3)

    pdf.set_y(-15)
    pdf.set_font(base_font, "", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, f"Сформировано: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC  |  PawCare", align="C")

    pdf_bytes = bytes(pdf.output())
    return pdf_bytes


@app.get("/api/v1/pets/{pet_id}/health/export")
def export_health_pdf(pet_id: str,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    records = db.query(HealthRecord).filter(
        HealthRecord.pet_id == pet_id
    ).order_by(HealthRecord.record_date.desc()).all()
    try:
        pdf_bytes = _build_health_pdf(pet, records)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации PDF: {str(e)}")
    filename = f"health_{pet.name}_{date.today()}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

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
    db.add(log)
    db.commit()
    db.refresh(log)
    return WeightResponse(id=log.id, weight_kg=log.weight_kg, measured_at=str(log.measured_at))

@app.delete("/api/v1/pets/{pet_id}/weight/{weight_id}")
def delete_weight(pet_id: str, weight_id: str,
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    log = db.query(WeightLog).filter(WeightLog.id == weight_id, WeightLog.pet_id == pet_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(log)
    db.commit()
    return {"message": "Запись удалена"}

# DASHBOARD STATS
@app.get("/api/v1/dashboard/stats")
def get_dashboard_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pets = db.query(Pet).filter(
        Pet.owner_id == current_user.id, Pet.is_deleted == False
    ).all()
    pets_count = len(pets)
    pet_ids = [p.id for p in pets]
    pet_names = {p.id: p.name for p in pets}

    now_str = datetime.now().isoformat()
    next_reminder = (
        db.query(Reminder)
        .filter(
            Reminder.user_id == current_user.id,
            Reminder.is_done == False,
            Reminder.remind_at >= now_str,
        )
        .order_by(Reminder.remind_at)
        .first()
    )

    next_reminder_data = None
    if next_reminder:
        next_reminder_data = {
            "title": next_reminder.title,
            "remind_at": next_reminder.remind_at,
            "pet_name": pet_names.get(next_reminder.pet_id, ""),
        }

    recent_weight = None
    if pet_ids:
        wlog = (
            db.query(WeightLog)
            .filter(WeightLog.pet_id.in_(pet_ids))
            .order_by(WeightLog.measured_at.desc())
            .first()
        )
        if wlog:
            recent_weight = {
                "pet_name": pet_names.get(wlog.pet_id, ""),
                "weight_kg": wlog.weight_kg,
                "measured_at": str(wlog.measured_at),
            }

    return {
        "pets_count": pets_count,
        "next_reminder": next_reminder_data,
        "recent_weight": recent_weight,
    }

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
    custom = db.query(Reminder).filter(
        Reminder.user_id == current_user.id, Reminder.is_done == False
    ).all()
    pet_ids = {r.pet_id for r in custom}
    pets_by_id = {
        p.id: p for p in db.query(Pet).filter(Pet.id.in_(pet_ids)).all()
    } if pet_ids else {}
    for r in custom:
        pet = pets_by_id.get(r.pet_id)
        reminders.append({
            "id":          r.id,
            "pet_name":    pet.name if pet else "Питомец",
            "pet_id":      r.pet_id,
            "record_type": "custom",
            "title":       r.title,
            "next_date":   r.remind_at,
            "remind_at":   r.remind_at,
            "source":      "custom",
            "repeat_rule": r.repeat_rule,
        })

    reminders.sort(key=lambda x: x["remind_at"] or "")
    return reminders

@app.post("/api/v1/reminders", response_model=ReminderResponse)
def create_reminder(data: ReminderCreate,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        datetime.fromisoformat(data.remind_at)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Неверный формат даты. Ожидается ISO 8601 (например, 2025-06-01T10:00:00)")
    reminder = Reminder(
        pet_id=data.pet_id, user_id=current_user.id,
        title=data.title, remind_at=data.remind_at,
        repeat_rule=data.repeat_rule,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return ReminderResponse(
        id=reminder.id, pet_id=reminder.pet_id, title=reminder.title,
        remind_at=reminder.remind_at, repeat_rule=reminder.repeat_rule,
    )

@app.delete("/api/v1/reminders/{reminder_id}")
def delete_reminder(reminder_id: str,
                    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id, Reminder.user_id == current_user.id
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    db.delete(reminder)
    db.commit()
    return {"message": "Напоминание удалено"}

@app.put("/api/v1/reminders/{reminder_id}/done")
def complete_reminder(reminder_id: str,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id, Reminder.user_id == current_user.id
    ).first()
    if not reminder:
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    reminder.is_done = True

    if reminder.repeat_rule:
        try:
            from calendar import monthrange
            dt = datetime.fromisoformat(reminder.remind_at)
            rule = reminder.repeat_rule
            if rule == 'daily':
                next_dt = dt + timedelta(days=1)
            elif rule == 'weekly':
                next_dt = dt + timedelta(weeks=1)
            elif rule == 'monthly':
                m, y = dt.month + 1, dt.year
                if m > 12:
                    m, y = 1, y + 1
                max_day = monthrange(y, m)[1]
                next_dt = dt.replace(year=y, month=m, day=min(dt.day, max_day))
            elif rule == 'yearly':
                next_dt = dt.replace(year=dt.year + 1)
            else:
                next_dt = None
            if next_dt:
                new_r = Reminder(
                    pet_id=reminder.pet_id, user_id=reminder.user_id,
                    title=reminder.title, remind_at=next_dt.isoformat(),
                    repeat_rule=reminder.repeat_rule,
                )
                db.add(new_r)
        except Exception:
            pass

    db.commit()
    return {"message": "Выполнено"}

# HEAT CYCLES
@app.get("/api/v1/pets/{pet_id}/heat-cycles", response_model=List[HeatCycleResponse])
def get_heat_cycles(pet_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cycles = db.query(HeatCycle).filter(
        HeatCycle.pet_id == pet_id
    ).order_by(HeatCycle.started_at.desc()).all()
    return [HeatCycleResponse(id=c.id, started_at=c.started_at, ended_at=c.ended_at, notes=c.notes) for c in cycles]

@app.post("/api/v1/pets/{pet_id}/heat-cycles", response_model=HeatCycleResponse)
def add_heat_cycle(pet_id: str, data: HeatCycleCreate,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cycle = HeatCycle(pet_id=pet_id, started_at=data.started_at, notes=data.notes)
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return HeatCycleResponse(id=cycle.id, started_at=cycle.started_at, ended_at=cycle.ended_at, notes=cycle.notes)

@app.put("/api/v1/pets/{pet_id}/heat-cycles/{cycle_id}", response_model=HeatCycleResponse)
def update_heat_cycle(pet_id: str, cycle_id: str, data: HeatCycleUpdate,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cycle = db.query(HeatCycle).filter(HeatCycle.id == cycle_id, HeatCycle.pet_id == pet_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    if data.started_at is not None:
        cycle.started_at = data.started_at
    if data.ended_at is not None:
        cycle.ended_at = data.ended_at
    if data.notes is not None:
        cycle.notes = data.notes
    db.commit()
    db.refresh(cycle)
    return HeatCycleResponse(id=cycle.id, started_at=cycle.started_at, ended_at=cycle.ended_at, notes=cycle.notes)

@app.delete("/api/v1/pets/{pet_id}/heat-cycles/{cycle_id}")
def delete_heat_cycle(pet_id: str, cycle_id: str,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pet = db.query(Pet).filter(Pet.id == pet_id, Pet.owner_id == current_user.id).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    cycle = db.query(HeatCycle).filter(HeatCycle.id == cycle_id, HeatCycle.pet_id == pet_id).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(cycle)
    db.commit()
    return {"message": "Запись удалена"}

# MAP
SEARCH_RADIUS_M = 20000  # радиус поиска в метрах (~город)

# OSM-теги для Overpass API (надёжнее Nominatim для поиска POI)
_OVERPASS_FILTERS = {
    "vets":         '["amenity"="veterinary"]',
    "pet_store":    '["shop"="pet"]',
    "grooming":     '["shop"="pet_grooming"]',
    "pet_pharmacy": '["shop"~"pet|veterinary"]["name"~"[Аа]птек|[Фф]арм|[Зз]оо", i]',
    "dog_park":     '["leisure"="dog_park"]',
}

# Fallback Nominatim-запросы если Overpass вернул 0 результатов
_NOMINATIM_QUERIES = {
    "vets":         "ветеринарная клиника",
    "pet_store":    "зоомагазин",
    "grooming":     "груминг животных",
    "pet_pharmacy": "зооаптека",
    "dog_park":     "площадка для выгула собак",
}


def _parse_overpass(elements: list, place_type: str) -> list:
    results = []
    for el in elements:
        tags = el.get("tags", {})
        name = (tags.get("name") or tags.get("name:ru") or "").strip()
        if not name:
            continue
        # У way/relation — координаты из center
        if el["type"] == "node":
            lat_v = float(el.get("lat", 0))
            lon_v = float(el.get("lon", 0))
        else:
            center = el.get("center", {})
            lat_v = float(center.get("lat", 0))
            lon_v = float(center.get("lon", 0))
        if lat_v == 0 and lon_v == 0:
            continue

        street  = tags.get("addr:street", "")
        house   = tags.get("addr:housenumber", "")
        city    = tags.get("addr:city", tags.get("addr:town", ""))
        parts   = [p for p in [street, house, city] if p]
        address = ", ".join(parts) if parts else ""

        phone = (tags.get("phone") or tags.get("contact:phone") or
                 tags.get("contact:mobile") or "").strip()
        hours = tags.get("opening_hours", "").strip()

        results.append({
            "name":       name,
            "address":    address or "Адрес не указан",
            "phone":      phone,
            "hours":      hours,
            "lat":        lat_v,
            "lon":        lon_v,
            "place_type": place_type,
        })
    return results


async def _nominatim_fallback(lat: float, lon: float, place_type: str) -> list:
    query = _NOMINATIM_QUERIES.get(place_type, "")
    if not query:
        return []
    url = "https://nominatim.openstreetmap.org/search"
    # ~20 км в градусах ≈ 0.18 по широте, 0.25 по долготе
    delta_lat = 0.18
    delta_lon = 0.25
    params = {
        "q": query,
        "format": "json",
        "limit": 15,
        "addressdetails": 1,
        "viewbox": f"{lon-delta_lon},{lat+delta_lat},{lon+delta_lon},{lat-delta_lat}",
        "bounded": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params,
                                    headers={"User-Agent": "PawCare/1.0"})
            data = resp.json()
        places = []
        for item in data:
            addr  = item.get("address", {})
            road  = addr.get("road", "")
            house = addr.get("house_number", "")
            city  = addr.get("city", addr.get("town", addr.get("village", "")))
            address = ", ".join(p for p in [road, house, city] if p)
            places.append({
                "name":       item.get("display_name", "").split(",")[0],
                "address":    address or "Адрес не указан",
                "phone":      "",
                "hours":      "",
                "lat":        float(item.get("lat", lat)),
                "lon":        float(item.get("lon", lon)),
                "place_type": place_type,
            })
        return places
    except Exception:
        return []


@app.get("/api/v1/map/vets")
async def get_vets(lat: float, lon: float, place_type: str = "vets",
                   current_user: User = Depends(get_current_user)):
    osm_filter = _OVERPASS_FILTERS.get(place_type, _OVERPASS_FILTERS["vets"])
    overpass_query = (
        f"[out:json][timeout:20];"
        f"("
        f"  node{osm_filter}(around:{SEARCH_RADIUS_M},{lat},{lon});"
        f"  way{osm_filter}(around:{SEARCH_RADIUS_M},{lat},{lon});"
        f");"
        f"out body center;"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": overpass_query},
                headers={"User-Agent": "PawCare/1.0"},
            )
            elements = resp.json().get("elements", [])
        places = _parse_overpass(elements, place_type)
    except Exception:
        places = []

    # Если Overpass не вернул ничего — используем Nominatim как резервный
    if not places:
        places = await _nominatim_fallback(lat, lon, place_type)

    return places

# TELEGRAM BOT

class TelegramLinkRequest(BaseModel):
    chat_id: str
    username: Optional[str] = None
    link_code: str

# Хранилище кодов привязки (в памяти)
link_codes: dict = {}

@app.post("/api/v1/telegram/generate-code")
def generate_link_code(current_user: User = Depends(get_current_user)):
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

@app.get("/api/v1/telegram/health")
def telegram_get_health(chat_id: str, pet_name: str, db: Session = Depends(get_db)):
    tg = db.query(TelegramUser).filter(TelegramUser.chat_id == chat_id).first()
    if not tg:
        raise HTTPException(status_code=403, detail="Аккаунт не привязан")
    pet = db.query(Pet).filter(
        Pet.owner_id == tg.user_id,
        Pet.is_deleted == False,
        Pet.name.ilike(pet_name)
    ).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    records = db.query(HealthRecord).filter(
        HealthRecord.pet_id == pet.id
    ).order_by(HealthRecord.record_date.desc()).all()
    return {
        "pet_name": pet.name,
        "records": [
            {
                "title": r.title,
                "record_type": r.record_type,
                "record_date": r.record_date,
                "next_date": r.next_date,
                "description": r.description,
            }
            for r in records
        ]
    }

@app.get("/api/v1/map/vets-public")
async def get_vets_public(lat: float, lon: float):
    """Публичный эндпоинт для бота (без JWT)"""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": "ветеринарная клиника",
        "format": "json",
        "limit": 10,
        "viewbox": f"{lon-0.1},{lat+0.1},{lon+0.1},{lat-0.1}",
        "bounded": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params,
                                    headers={"User-Agent": "PawCareBot/1.0"})
        results = resp.json()
        clinics = []
        for r in results:
            clinics.append({
                "name": r.get("display_name", "").split(",")[0],
                "address": ", ".join(r.get("display_name", "").split(",")[1:3]).strip(),
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            })
        return clinics
    except Exception:
        return []

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
    custom_pet_ids = {r.pet_id for r in custom}
    custom_pets_by_id = {
        p.id: p for p in db.query(Pet).filter(Pet.id.in_(custom_pet_ids)).all()
    } if custom_pet_ids else {}
    for r in custom:
        pet = custom_pets_by_id.get(r.pet_id)
        reminders.append({
            "pet_name": pet.name if pet else "Питомец",
            "record_type": "custom",
            "title": r.title,
            "remind_at": r.remind_at,
        })

    reminders.sort(key=lambda x: x["remind_at"] or "")
    return reminders

@app.get("/api/v1/telegram/all-due")
def get_all_due_notifications(db: Session = Depends(get_db)):
    """Все напоминания на сегодня для всех привязанных пользователей"""
    today = date.today()
    tg_users = db.query(TelegramUser).all()
    result = []

    for tg in tg_users:
        pets = db.query(Pet).filter(
            Pet.owner_id == tg.user_id,
            Pet.is_deleted == False,
        ).all()

        for pet in pets:
            records = db.query(HealthRecord).filter(
                HealthRecord.pet_id == pet.id,
                HealthRecord.next_date != None,
            ).all()
            for r in records:
                try:
                    if date.fromisoformat(r.next_date) == today:
                        result.append({
                            "chat_id": tg.chat_id,
                            "title": r.title,
                            "pet_name": pet.name,
                            "record_type": r.record_type,
                            "remind_at": r.next_date,
                        })
                except Exception:
                    continue

        custom = db.query(Reminder).filter(Reminder.user_id == tg.user_id).all()
        due_custom = []
        for r in custom:
            try:
                remind_dt = _parse_remind_at(r.remind_at)
                if remind_dt.date() == today:
                    due_custom.append(r)
            except Exception:
                continue
        if due_custom:
            due_pet_ids = {r.pet_id for r in due_custom}
            due_pets_by_id = {
                p.id: p for p in db.query(Pet).filter(Pet.id.in_(due_pet_ids)).all()
            }
            for r in due_custom:
                pet = due_pets_by_id.get(r.pet_id)
                result.append({
                    "chat_id": tg.chat_id,
                    "title": r.title,
                    "pet_name": pet.name if pet else "Питомец",
                    "record_type": "custom",
                    "remind_at": r.remind_at,
                })

    return result


def _parse_remind_at(s: str) -> datetime:
    """Парсит строку времени, поддерживая UTC (Z / +00:00) и наивный формат."""
    s = s.strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fallback: обрезаем миллисекунды и пробуем снова
        dt = datetime.fromisoformat(s[:19])
    # Если есть tzinfo — переводим в UTC naive для единообразного сравнения
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

@app.get("/api/v1/telegram/due-in-hour")
def get_due_in_hour(db: Session = Depends(get_db)):
    """Напоминания ровно через ~1 час (окно ±5 мин) для всех привязанных пользователей"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_start = now + timedelta(minutes=50)
    window_end   = now + timedelta(minutes=70)

    all_reminders = db.query(Reminder).filter(
        Reminder.is_done == False,
    ).all()

    # Фильтруем в Python — так корректно обрабатываются оба формата хранения
    reminders = []
    for r in all_reminders:
        try:
            remind_dt = _parse_remind_at(r.remind_at)
            if window_start <= remind_dt <= window_end:
                reminders.append(r)
        except Exception:
            continue

    result = []
    for r in reminders:
        tg = db.query(TelegramUser).filter(
            TelegramUser.user_id == r.user_id
        ).first()
        if not tg:
            continue
        pet = db.query(Pet).filter(Pet.id == r.pet_id).first()
        result.append({
            "id":          r.id,
            "chat_id":    tg.chat_id,
            "title":      r.title,
            "pet_name":   pet.name if pet else "Питомец",
            "remind_at":  r.remind_at,
            "record_type": "custom",
        })
    return result

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


@app.get("/api/v1/telegram/health-by-id")
def telegram_get_health_by_id(chat_id: str, pet_id: str, db: Session = Depends(get_db)):
    tg = db.query(TelegramUser).filter(TelegramUser.chat_id == chat_id).first()
    if not tg:
        raise HTTPException(status_code=403, detail="Аккаунт не привязан")
    pet = db.query(Pet).filter(
        Pet.id == pet_id,
        Pet.owner_id == tg.user_id,
        Pet.is_deleted == False,
    ).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    records = db.query(HealthRecord).filter(
        HealthRecord.pet_id == pet_id
    ).order_by(HealthRecord.record_date.desc()).all()
    return {
        "pet_name": pet.name,
        "pet_id": pet.id,
        "records": [
            {
                "title": r.title,
                "record_type": r.record_type,
                "record_date": r.record_date,
                "next_date": r.next_date,
                "description": r.description,
            } for r in records
        ],
    }


@app.get("/api/v1/telegram/pdf")
def telegram_get_pdf(chat_id: str, pet_id: str, db: Session = Depends(get_db)):
    tg = db.query(TelegramUser).filter(TelegramUser.chat_id == chat_id).first()
    if not tg:
        raise HTTPException(status_code=403, detail="Аккаунт не привязан")
    pet = db.query(Pet).filter(
        Pet.id == pet_id,
        Pet.owner_id == tg.user_id,
        Pet.is_deleted == False,
    ).first()
    if not pet:
        raise HTTPException(status_code=404, detail="Питомец не найден")
    records = db.query(HealthRecord).filter(
        HealthRecord.pet_id == pet_id
    ).order_by(HealthRecord.record_date.desc()).all()
    pdf_bytes = _build_health_pdf(pet, records)
    filename = f"health_{pet.name}_{date.today()}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# APScheduler: фоновые задачи
def _cleanup_expired_codes():
    """Удаляет просроченные коды входа (старше 15 мин) и OAuth-состояния (старше 10 мин)."""
    db = SessionLocal()
    try:
        tg_cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        db.query(TelegramLoginCode).filter(
            TelegramLoginCode.created_at < tg_cutoff
        ).delete(synchronize_session=False)

        google_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.query(GoogleOAuthState).filter(
            GoogleOAuthState.created_at < google_cutoff
        ).delete(synchronize_session=False)

        db.commit()
    finally:
        db.close()


def _mark_overdue_reminders():
    """Помечает просроченные однократные напоминания как выполненные."""
    db = SessionLocal()
    try:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        overdue = db.query(Reminder).filter(
            Reminder.is_done == False,  # noqa
            Reminder.repeat_rule == None,  # noqa
            Reminder.remind_at < now_str,
        ).all()
        for r in overdue:
            r.is_done = True
        if overdue:
            db.commit()
    finally:
        db.close()


_scheduler = BackgroundScheduler(timezone="Europe/Moscow")
_scheduler.add_job(_cleanup_expired_codes,  "interval", minutes=5,  id="cleanup_codes")
_scheduler.add_job(_mark_overdue_reminders, "interval", minutes=10, id="mark_overdue")
_scheduler.start()
atexit.register(lambda: _scheduler.shutdown(wait=False))
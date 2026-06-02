"""
Юнит-тесты PawCare (pytest + FastAPI TestClient + SQLite in-memory).

Запуск:  cd pawcare_server && pytest tests/test_unit.py -v
Покрытие: pytest tests/test_unit.py -v --tb=short

Группы тестов:
  TestTokenCreation     — создание и декодирование JWT (UT-01..UT-03)
  TestPasswordHashing   — bcrypt хеширование и верификация (UT-04..UT-06)
  TestAuthEndpoints     — /api/v1/auth/* (UT-07..UT-10)
  TestPetEndpoints      — /api/v1/pets (UT-11..UT-13)
  TestHealthEndpoints   — /api/v1/pets/{id}/health (UT-14..UT-15)
  TestReminderEndpoints — /api/v1/reminders (UT-16)
"""

import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jose import jwt
from datetime import datetime, timezone

# conftest.py уже установил переменные окружения до этой точки
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import (
    app, Base, get_db,
    create_token, pwd_context,
    SECRET_KEY, ALGORITHM,
)

# ── Тестовая база данных (SQLite) ──────────────────────────────────────────
TEST_DB_URL = "sqlite:///./test_pawcare.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

TS = int(time.time())  # уникальный суффикс для email в каждом запуске


# ══════════════════════════════════════════════════════════════════════════════
# UT-01..UT-03  Создание и декодирование JWT-токена
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenCreation:
    """Проверяет функцию create_token(): формат, payload, срок действия."""

    def test_ut01_create_token_returns_string(self):
        """UT-01: create_token() возвращает непустую строку."""
        token = create_token("test-user-id")
        assert isinstance(token, str) and len(token) > 0

    def test_ut02_token_contains_user_id(self):
        """UT-02: payload токена содержит корректное поле sub = user_id."""
        user_id = "user-abc-123"
        token = create_token(user_id)
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload.get("sub") == user_id

    def test_ut03_token_expires_in_7_days(self):
        """UT-03: срок действия токена — ровно 7 суток (604800 с, допуск ±60 с)."""
        token = create_token("any-user")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta_sec = (exp - datetime.now(timezone.utc)).total_seconds()
        assert abs(delta_sec - 7 * 24 * 3600) < 60


# ══════════════════════════════════════════════════════════════════════════════
# UT-04..UT-06  Хеширование паролей bcrypt
# ══════════════════════════════════════════════════════════════════════════════

class TestPasswordHashing:
    """Проверяет bcrypt: хеш отличается от plaintext, верификация работает."""

    def test_ut04_hash_is_not_plaintext(self):
        """UT-04: хеш bcrypt начинается с $2b$ и не совпадает с паролем."""
        password = "MySecret123!"
        hashed = pwd_context.hash(password)
        assert hashed != password
        assert hashed.startswith("$2b$")

    def test_ut05_verify_correct_password(self):
        """UT-05: pwd_context.verify() возвращает True для верного пароля."""
        password = "CorrectPass!99"
        hashed = pwd_context.hash(password)
        assert pwd_context.verify(password, hashed) is True

    def test_ut06_verify_wrong_password(self):
        """UT-06: pwd_context.verify() возвращает False для неверного пароля."""
        hashed = pwd_context.hash("OriginalPass")
        assert pwd_context.verify("WrongPass", hashed) is False


# ══════════════════════════════════════════════════════════════════════════════
# UT-07..UT-10  Эндпоинты аутентификации
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthEndpoints:
    """Интеграционные юнит-тесты /api/v1/auth/* через FastAPI TestClient."""

    def test_ut07_register_new_user(self):
        """UT-07: регистрация нового пользователя — HTTP 200, токен в ответе."""
        r = client.post("/api/v1/auth/register", json={
            "name": "Тест Юзер",
            "email": f"ut07_{TS}@pawcare.test",
            "password": "TestPass123!",
        })
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body["email"] == f"ut07_{TS}@pawcare.test"

    def test_ut08_register_duplicate_email(self):
        """UT-08: повторная регистрация с тем же email — HTTP 400."""
        email = f"ut08_{TS}@pawcare.test"
        client.post("/api/v1/auth/register",
                    json={"name": "A", "email": email, "password": "Pass1!"})
        r2 = client.post("/api/v1/auth/register",
                         json={"name": "B", "email": email, "password": "Pass2!"})
        assert r2.status_code == 400

    def test_ut09_login_valid_credentials(self):
        """UT-09: вход с верными данными — HTTP 200, access_token в ответе."""
        email = f"ut09_{TS}@pawcare.test"
        client.post("/api/v1/auth/register",
                    json={"name": "Login", "email": email, "password": "Pass123!"})
        r = client.post("/api/v1/auth/login",
                        json={"email": email, "password": "Pass123!"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_ut10_login_invalid_password(self):
        """UT-10: вход с неверным паролем — HTTP 401."""
        email = f"ut10_{TS}@pawcare.test"
        client.post("/api/v1/auth/register",
                    json={"name": "Inv", "email": email, "password": "RealPass!"})
        r = client.post("/api/v1/auth/login",
                        json={"email": email, "password": "WrongPass!"})
        assert r.status_code == 401

    def test_ut10b_get_me_without_token(self):
        """UT-10b: GET /auth/me без токена — HTTP 401/403."""
        r = client.get("/api/v1/auth/me")
        assert r.status_code in (401, 403)

    def test_ut10c_get_me_with_valid_token(self):
        """UT-10c: GET /auth/me с верным токеном — HTTP 200, email совпадает."""
        email = f"ut10c_{TS}@pawcare.test"
        reg = client.post("/api/v1/auth/register",
                          json={"name": "Me", "email": email, "password": "Pass123!"})
        token = reg.json()["access_token"]
        r = client.get("/api/v1/auth/me",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["email"] == email


# ══════════════════════════════════════════════════════════════════════════════
# UT-11..UT-13  Эндпоинты питомцев
# ══════════════════════════════════════════════════════════════════════════════

class TestPetEndpoints:
    """Юнит-тесты CRUD /api/v1/pets и проверка изоляции данных."""

    @classmethod
    def setup_class(cls):
        email = f"ut_pets_{TS}@pawcare.test"
        reg = client.post("/api/v1/auth/register",
                          json={"name": "PetOwner", "email": email, "password": "Pass123!"})
        cls.token = reg.json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_ut11_create_pet_valid(self):
        """UT-11: создание питомца с обязательными полями — HTTP 200, id присвоен."""
        r = client.post("/api/v1/pets",
                        json={"name": "Барсик", "breed": "Хаски"},
                        headers=self.headers)
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Барсик"
        assert "id" in body

    def test_ut12_create_pet_empty_name(self):
        """UT-12: питомец с пустым именем — HTTP 422 Unprocessable Entity."""
        r = client.post("/api/v1/pets",
                        json={"name": "", "breed": "Любая"},
                        headers=self.headers)
        assert r.status_code == 422

    def test_ut13_get_pets_returns_only_own(self):
        """UT-13: GET /pets возвращает только питомцев текущего пользователя (IDOR)."""
        # Второй пользователь добавляет питомца
        email2 = f"ut13_other_{TS}@pawcare.test"
        reg2 = client.post("/api/v1/auth/register",
                           json={"name": "Other", "email": email2, "password": "Pass123!"})
        h2 = {"Authorization": f"Bearer {reg2.json()['access_token']}"}
        client.post("/api/v1/pets", json={"name": "ЧужойПёс"}, headers=h2)

        r = client.get("/api/v1/pets", headers=self.headers)
        names = [p["name"] for p in r.json()]
        assert "ЧужойПёс" not in names

    def test_ut13b_update_other_user_pet(self):
        """UT-13b: PUT чужого питомца — HTTP 403/404 (защита от IDOR)."""
        email3 = f"ut13b_{TS}@pawcare.test"
        reg3 = client.post("/api/v1/auth/register",
                           json={"name": "Third", "email": email3, "password": "Pass123!"})
        h3 = {"Authorization": f"Bearer {reg3.json()['access_token']}"}
        r_pet = client.post("/api/v1/pets", json={"name": "ЧужойПёс2"}, headers=h3)
        pet_id = r_pet.json()["id"]

        r_upd = client.put(f"/api/v1/pets/{pet_id}",
                           json={"name": "Взломан"},
                           headers=self.headers)
        assert r_upd.status_code in (403, 404)


# ══════════════════════════════════════════════════════════════════════════════
# UT-14..UT-15  Медицинский журнал
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoints:
    """Юнит-тесты /api/v1/pets/{pet_id}/health."""

    @classmethod
    def setup_class(cls):
        email = f"ut_health_{TS}@pawcare.test"
        reg = client.post("/api/v1/auth/register",
                          json={"name": "HealthOwner", "email": email, "password": "Pass123!"})
        cls.token = reg.json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}
        r_pet = client.post("/api/v1/pets", json={"name": "МедПёс"}, headers=cls.headers)
        cls.pet_id = r_pet.json()["id"]

    def test_ut14_create_health_record(self):
        """UT-14: добавление записи о вакцинации — HTTP 200, record_type корректен."""
        r = client.post(f"/api/v1/pets/{self.pet_id}/health", json={
            "record_type": "vaccination",
            "title": "Вакцинация от бешенства",
            "record_date": "2024-03-15",
        }, headers=self.headers)
        assert r.status_code == 200
        assert r.json()["record_type"] == "vaccination"
        assert "id" in r.json()

    def test_ut15_get_health_records(self):
        """UT-15: GET медицинских записей питомца — HTTP 200, список записей."""
        r = client.get(f"/api/v1/pets/{self.pet_id}/health", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# UT-16  Напоминания
# ══════════════════════════════════════════════════════════════════════════════

class TestReminderEndpoints:
    """Юнит-тесты /api/v1/reminders."""

    @classmethod
    def setup_class(cls):
        email = f"ut_rem_{TS}@pawcare.test"
        reg = client.post("/api/v1/auth/register",
                          json={"name": "RemOwner", "email": email, "password": "Pass123!"})
        cls.token = reg.json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {cls.token}"}
        r_pet = client.post("/api/v1/pets", json={"name": "НапоминаниеПёс"}, headers=cls.headers)
        cls.pet_id = r_pet.json()["id"]

    def test_ut16_create_reminder(self):
        """UT-16: создание напоминания с корректными данными — HTTP 200, id присвоен."""
        r = client.post("/api/v1/reminders", json={
            "pet_id": self.pet_id,
            "title": "Прививка от бешенства",
            "remind_at": "2025-12-01T10:00:00",
        }, headers=self.headers)
        assert r.status_code == 200
        assert "id" in r.json()

    def test_ut16b_get_reminders(self):
        """UT-16b: GET /reminders — HTTP 200, массив напоминаний."""
        r = client.get("/api/v1/reminders", headers=self.headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

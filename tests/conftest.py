"""
Конфигурация pytest для юнит-тестов PawCare.
Устанавливает переменные окружения ДО импорта main,
чтобы SQLAlchemy использовал SQLite вместо PostgreSQL.
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_pawcare.db"
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-testing-only-32chars")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "")
os.environ.setdefault("CLOUDINARY_API_KEY", "")
os.environ.setdefault("CLOUDINARY_API_SECRET", "")
os.environ.setdefault("YANDEX_API_KEY", "")

"""
Нагрузочное тестирование PawCare API (Locust)

Установка:  pip install locust
Запуск:     locust -f locustfile.py --host https://web-production-ff3c6.up.railway.app
Web UI:     http://localhost:8089

Сценарий:
  Каждый виртуальный пользователь проходит полный цикл:
  регистрация → логин → CRUD питомца → медзапись → вес → напоминание

Рекомендованные параметры для дипломной демонстрации:
  Users: 50,  Spawn rate: 5/s,  Run time: 2m
"""

import time
import random
from locust import HttpUser, task, between, events


class PawCareUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Регистрация и логин перед началом задач."""
        ts = int(time.time() * 1000) + random.randint(0, 9999)
        self.email = f"load_{ts}@pawcare.test"
        self.password = "LoadTest123!"
        self.token = None
        self.pet_id = None

        # Регистрация
        r = self.client.post(
            "/api/v1/auth/register",
            json={"name": "Нагрузочный Тест", "email": self.email, "password": self.password},
            name="/api/v1/auth/register",
        )
        if r.status_code == 200:
            self.token = r.json().get("access_token")
        elif r.status_code == 400:
            # Email уже существует — логинимся
            r2 = self.client.post(
                "/api/v1/auth/login",
                json={"email": self.email, "password": self.password},
                name="/api/v1/auth/login",
            )
            if r2.status_code == 200:
                self.token = r2.json().get("access_token")

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    # ── Задача 1: Список питомцев (наиболее частая операция) ────────────────
    @task(5)
    def get_pets(self):
        self.client.get("/api/v1/pets", headers=self._headers, name="/api/v1/pets [GET]")

    # ── Задача 2: Создание питомца ───────────────────────────────────────────
    @task(2)
    def create_pet(self):
        if not self.token:
            return
        r = self.client.post(
            "/api/v1/pets",
            json={"name": f"Пёс_{random.randint(1000, 9999)}", "breed": "Лабрадор"},
            headers=self._headers,
            name="/api/v1/pets [POST]",
        )
        if r.status_code == 200:
            self.pet_id = r.json().get("id")

    # ── Задача 3: Добавление медзаписи ───────────────────────────────────────
    @task(2)
    def add_health_record(self):
        if not self.token or not self.pet_id:
            return
        self.client.post(
            f"/api/v1/pets/{self.pet_id}/health",
            json={
                "record_type": random.choice(["vaccination", "vet_visit", "medication"]),
                "title": "Нагрузочный тест",
                "record_date": "2024-06-01",
            },
            headers=self._headers,
            name="/api/v1/pets/{id}/health [POST]",
        )

    # ── Задача 4: Добавление веса ────────────────────────────────────────────
    @task(2)
    def add_weight(self):
        if not self.token or not self.pet_id:
            return
        self.client.post(
            f"/api/v1/pets/{self.pet_id}/weight",
            json={"weight_kg": round(random.uniform(2.0, 60.0), 1)},
            headers=self._headers,
            name="/api/v1/pets/{id}/weight [POST]",
        )

    # ── Задача 5: Создание напоминания ───────────────────────────────────────
    @task(1)
    def create_reminder(self):
        if not self.token or not self.pet_id:
            return
        self.client.post(
            "/api/v1/reminders",
            json={
                "pet_id": self.pet_id,
                "title": "Нагрузочное напоминание",
                "remind_at": "2026-12-01T10:00:00",
            },
            headers=self._headers,
            name="/api/v1/reminders [POST]",
        )

    # ── Задача 6: Профиль пользователя ──────────────────────────────────────
    @task(3)
    def get_profile(self):
        if not self.token:
            return
        self.client.get(
            "/api/v1/auth/me",
            headers=self._headers,
            name="/api/v1/auth/me [GET]",
        )

    # ── Задача 7: История веса ───────────────────────────────────────────────
    @task(2)
    def get_weight_history(self):
        if not self.token or not self.pet_id:
            return
        self.client.get(
            f"/api/v1/pets/{self.pet_id}/weight",
            headers=self._headers,
            name="/api/v1/pets/{id}/weight [GET]",
        )


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    """Выводит итог в консоль при завершении."""
    stats = environment.stats
    print("\n" + "=" * 60)
    print("  ИТОГИ НАГРУЗОЧНОГО ТЕСТИРОВАНИЯ PawCare")
    print("=" * 60)
    for name, entry in stats.entries.items():
        if entry.num_requests > 0:
            print(
                f"  {name[1]:45s} | "
                f"req: {entry.num_requests:5d} | "
                f"fail: {entry.num_failures:4d} | "
                f"avg: {entry.avg_response_time:6.0f}ms | "
                f"p95: {entry.get_response_time_percentile(0.95):6.0f}ms"
            )
    total = stats.total
    pct = round((1 - total.num_failures / total.num_requests) * 100) if total.num_requests else 0
    print(f"\n  Всего запросов: {total.num_requests}")
    print(f"  Ошибок:         {total.num_failures}")
    print(f"  Успешность:     {pct}%")
    print(f"  RPS (пик):      {total.max_requests_per_sec:.1f}")
    print("=" * 60)

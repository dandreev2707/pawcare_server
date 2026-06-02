"""
Автоматическое тестирование API системы PawCare
Покрывает: аутентификация, питомцы, здоровье, напоминания, безопасность, карта
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import httpx
import json
import time
import asyncio
from datetime import datetime, timedelta

BASE_URL = "https://web-production-ff3c6.up.railway.app"

# ── Цвета для вывода в терминале ──
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

# ── Счётчики результатов ──
results = {"pass": 0, "fail": 0, "total": 0}


def log_section(title: str):
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}")


def log_test(name: str, passed: bool, detail: str = ""):
    results["total"] += 1
    if passed:
        results["pass"] += 1
        status = f"{GREEN}[PASS]{RESET}"
    else:
        results["fail"] += 1
        status = f"{RED}[FAIL]{RESET}"

    print(f"  {status}  {name}")
    if detail:
        color = GREEN if passed else RED
        print(f"         {color}→ {detail}{RESET}")


def print_summary():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  ИТОГИ ТЕСТИРОВАНИЯ{RESET}")
    print(f"{'='*60}{RESET}")
    total = results["total"]
    passed = results["pass"]
    failed = results["fail"]
    pct = round(passed / total * 100) if total > 0 else 0
    print(f"  Всего тестов:   {total}")
    print(f"  {GREEN}Пройдено:       {passed}{RESET}")
    print(f"  {RED}Провалено:      {failed}{RESET}")
    print(f"  Успешность:     {pct}%")
    print(f"{'='*60}\n")


# ════════════════════════════════════════════════════════════
# БЛОК 1: АУТЕНТИФИКАЦИЯ
# ════════════════════════════════════════════════════════════

def test_auth(client: httpx.Client) -> dict:
    log_section("БЛОК 1: АУТЕНТИФИКАЦИЯ")

    # Уникальный email для каждого запуска тестов
    ts = int(time.time())
    email = f"testuser_{ts}@pawcare.test"
    password = "TestPass123!"
    name = "Тестовый Пользователь"

    token = None

    # ── Тест 1.1: Регистрация нового пользователя ──
    r = client.post("/api/v1/auth/register",
                    json={"name": name, "email": email, "password": password})
    log_test(
        "1.1 Регистрация нового пользователя",
        r.status_code == 200,
        f"HTTP {r.status_code} | email: {email}"
    )

    # ── Тест 1.2: Повторная регистрация с тем же email ──
    r2 = client.post("/api/v1/auth/register",
                     json={"name": name, "email": email, "password": password})
    log_test(
        "1.2 Регистрация с уже существующим email (ожидается ошибка)",
        r2.status_code == 400,
        f"HTTP {r2.status_code} | detail: {r2.json().get('detail', '')}"
    )

    # ── Тест 1.3: Вход с верными данными ──
    r3 = client.post("/api/v1/auth/login",
                     json={"email": email, "password": password})
    ok = r3.status_code == 200 and "access_token" in r3.json()
    if ok:
        token = r3.json()["access_token"]
    log_test(
        "1.3 Вход с верными данными",
        ok,
        f"HTTP {r3.status_code} | токен получен: {bool(token)}"
    )

    # ── Тест 1.4: Вход с неверным паролем ──
    r4 = client.post("/api/v1/auth/login",
                     json={"email": email, "password": "WrongPassword!"})
    log_test(
        "1.4 Вход с неверным паролем (ожидается ошибка)",
        r4.status_code in (400, 401),
        f"HTTP {r4.status_code} | detail: {r4.json().get('detail', '')}"
    )

    # ── Тест 1.5: Вход с несуществующим email ──
    r5 = client.post("/api/v1/auth/login",
                     json={"email": "nobody@nowhere.com", "password": "pass"})
    log_test(
        "1.5 Вход с несуществующим email (ожидается ошибка)",
        r5.status_code in (400, 401, 404),
        f"HTTP {r5.status_code}"
    )

    # ── Тест 1.6: Запрос без токена (защищённый ресурс) ──
    r6 = client.get("/api/v1/pets")
    log_test(
        "1.6 Запрос без токена (ожидается 401/403)",
        r6.status_code in (401, 403),
        f"HTTP {r6.status_code}"
    )

    # ── Тест 1.7: Запрос с неверным токеном ──
    r7 = client.get("/api/v1/pets",
                    headers={"Authorization": "Bearer invalid.token.here"})
    log_test(
        "1.7 Запрос с неверным токеном (ожидается 401/403)",
        r7.status_code in (401, 403),
        f"HTTP {r7.status_code}"
    )

    # ── Тест 1.8: Получение профиля с верным токеном ──
    if token:
        r8 = client.get("/api/v1/auth/me",
                        headers={"Authorization": f"Bearer {token}"})
        log_test(
            "1.8 Получение профиля текущего пользователя",
            r8.status_code == 200 and r8.json().get("email") == email,
            f"HTTP {r8.status_code} | email совпадает: {r8.json().get('email') == email}"
        )

    return {"token": token, "email": email}


# ════════════════════════════════════════════════════════════
# БЛОК 2: УПРАВЛЕНИЕ ПИТОМЦАМИ
# ════════════════════════════════════════════════════════════

def test_pets(client: httpx.Client, token: str) -> str:
    log_section("БЛОК 2: УПРАВЛЕНИЕ ПИТОМЦАМИ")
    headers = {"Authorization": f"Bearer {token}"}
    pet_id = None

    # ── Тест 2.1: Создание питомца ──
    r = client.post("/api/v1/pets",
                    json={"name": "Бобик", "breed": "Лабрадор",
                          "birth_date": "2021-05-10", "sex": "male"},
                    headers=headers)
    ok = r.status_code == 200 and "id" in r.json()
    if ok:
        pet_id = r.json()["id"]
    log_test(
        "2.1 Создание питомца",
        ok,
        f"HTTP {r.status_code} | id: {pet_id}"
    )

    # ── Тест 2.2: Получение списка питомцев ──
    r2 = client.get("/api/v1/pets", headers=headers)
    pets = r2.json() if r2.status_code == 200 else []
    found = any(p["id"] == pet_id for p in pets) if pet_id else False
    log_test(
        "2.2 Получение списка питомцев",
        r2.status_code == 200 and found,
        f"HTTP {r2.status_code} | питомцев в списке: {len(pets)}, новый найден: {found}"
    )

    # ── Тест 2.3: Редактирование питомца ──
    if pet_id:
        r3 = client.put(f"/api/v1/pets/{pet_id}",
                        json={"name": "Бобик Updated", "breed": "Голден Ретривер"},
                        headers=headers)
        updated = r3.json().get("name") == "Бобик Updated" if r3.status_code == 200 else False
        log_test(
            "2.3 Редактирование питомца",
            r3.status_code == 200 and updated,
            f"HTTP {r3.status_code} | имя обновлено: {updated}"
        )

    # ── Тест 2.4: Создание второго пользователя и попытка доступа к чужому питомцу ──
    ts = int(time.time())
    r_reg = client.post("/api/v1/auth/register",
                        json={"name": "Чужой", "email": f"other_{ts}@test.com",
                              "password": "Pass123!"})
    r_login = client.post("/api/v1/auth/login",
                          json={"email": f"other_{ts}@test.com", "password": "Pass123!"})
    if r_login.status_code == 200:
        other_token = r_login.json()["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}
        if pet_id:
            r4 = client.put(f"/api/v1/pets/{pet_id}",
                            json={"name": "Взломан"},
                            headers=other_headers)
            log_test(
                "2.4 Попытка изменить чужого питомца (ожидается ошибка)",
                r4.status_code in (403, 404),
                f"HTTP {r4.status_code} | доступ запрещён: {r4.status_code in (403, 404)}"
            )

    return pet_id


# ════════════════════════════════════════════════════════════
# БЛОК 3: МЕДИЦИНСКИЙ ЖУРНАЛ
# ════════════════════════════════════════════════════════════

def test_health(client: httpx.Client, token: str, pet_id: str) -> str:
    log_section("БЛОК 3: МЕДИЦИНСКИЙ ЖУРНАЛ")
    headers = {"Authorization": f"Bearer {token}"}
    record_id = None

    # ── Тест 3.1: Добавление записи о вакцинации ──
    r = client.post(f"/api/v1/pets/{pet_id}/health",
                    json={"record_type": "vaccination",
                          "title": "Вакцинация от бешенства",
                          "description": "Вакцина Nobivac",
                          "record_date": "2024-03-15",
                          "next_date": "2025-03-15"},
                    headers=headers)
    ok = r.status_code == 200 and "id" in r.json()
    if ok:
        record_id = r.json()["id"]
    log_test(
        "3.1 Добавление записи о вакцинации",
        ok,
        f"HTTP {r.status_code} | id: {record_id}"
    )

    # ── Тест 3.2: Добавление записи о визите к ветеринару ──
    r2 = client.post(f"/api/v1/pets/{pet_id}/health",
                     json={"record_type": "vet_visit",
                           "title": "Плановый осмотр",
                           "record_date": "2024-06-01"},
                     headers=headers)
    log_test(
        "3.2 Добавление записи о визите к ветеринару",
        r2.status_code == 200,
        f"HTTP {r2.status_code}"
    )

    # ── Тест 3.3: Получение медицинских записей питомца ──
    r3 = client.get(f"/api/v1/pets/{pet_id}/health", headers=headers)
    records = r3.json() if r3.status_code == 200 else []
    log_test(
        "3.3 Получение медицинских записей питомца",
        r3.status_code == 200 and len(records) >= 2,
        f"HTTP {r3.status_code} | записей: {len(records)}"
    )

    # ── Тест 3.4: Экспорт медкарты в PDF ──
    r4 = client.get(f"/api/v1/pets/{pet_id}/health/export",
                    headers=headers)
    is_pdf = r4.headers.get("content-type", "").startswith("application/pdf")
    log_test(
        "3.4 Экспорт медкарты в PDF",
        r4.status_code == 200 and is_pdf,
        f"HTTP {r4.status_code} | Content-Type: {r4.headers.get('content-type', 'нет')} | размер: {len(r4.content)} байт"
    )

    # ── Тест 3.5: Удаление записи ──
    if record_id:
        r5 = client.delete(f"/api/v1/pets/{pet_id}/health/{record_id}",
                           headers=headers)
        log_test(
            "3.5 Удаление медицинской записи",
            r5.status_code == 200,
            f"HTTP {r5.status_code}"
        )

    return record_id


# ════════════════════════════════════════════════════════════
# БЛОК 4: НАПОМИНАНИЯ
# ════════════════════════════════════════════════════════════

def test_reminders(client: httpx.Client, token: str, pet_id: str):
    log_section("БЛОК 4: НАПОМИНАНИЯ")
    headers = {"Authorization": f"Bearer {token}"}
    reminder_id = None

    remind_at = (datetime.utcnow() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")

    # ── Тест 4.1: Создание напоминания ──
    r = client.post("/api/v1/reminders",
                    json={"pet_id": pet_id,
                          "title": "Тестовое напоминание",
                          "remind_at": remind_at},
                    headers=headers)
    ok = r.status_code == 200 and "id" in r.json()
    if ok:
        reminder_id = r.json()["id"]
    log_test(
        "4.1 Создание напоминания",
        ok,
        f"HTTP {r.status_code} | id: {reminder_id} | время: {remind_at}"
    )

    # ── Тест 4.2: Получение списка напоминаний ──
    r2 = client.get("/api/v1/reminders", headers=headers)
    reminders = r2.json() if r2.status_code == 200 else []
    found = any(rem["id"] == reminder_id for rem in reminders) if reminder_id else False
    log_test(
        "4.2 Получение списка напоминаний",
        r2.status_code == 200 and found,
        f"HTTP {r2.status_code} | напоминаний: {len(reminders)}, новое найдено: {found}"
    )

    # ── Тест 4.3: Отметить напоминание как выполненное ──
    if reminder_id:
        r3 = client.put(f"/api/v1/reminders/{reminder_id}/done", headers=headers)
        log_test(
            "4.3 Отметить напоминание как выполненное",
            r3.status_code == 200,
            f"HTTP {r3.status_code}"
        )

    # ── Тест 4.4: Создание нового и удаление напоминания ──
    r_new = client.post("/api/v1/reminders",
                        json={"pet_id": pet_id,
                              "title": "Удалить меня",
                              "remind_at": remind_at},
                        headers=headers)
    if r_new.status_code == 200:
        del_id = r_new.json()["id"]
        r4 = client.delete(f"/api/v1/reminders/{del_id}", headers=headers)
        log_test(
            "4.4 Удаление напоминания",
            r4.status_code == 200,
            f"HTTP {r4.status_code}"
        )


# ════════════════════════════════════════════════════════════
# БЛОК 5: ВЕС ПИТОМЦА
# ════════════════════════════════════════════════════════════

def test_weight(client: httpx.Client, token: str, pet_id: str):
    log_section("БЛОК 5: ЖУРНАЛ ВЕСА ПИТОМЦА")
    headers = {"Authorization": f"Bearer {token}"}

    # ── Тест 5.1: Добавление записи о весе ──
    r = client.post(f"/api/v1/pets/{pet_id}/weight",
                    json={"weight_kg": 28.5},
                    headers=headers)
    log_test(
        "5.1 Добавление записи о весе",
        r.status_code == 200,
        f"HTTP {r.status_code} | вес: 28.5 кг"
    )

    # ── Тест 5.2: Добавление ещё одной записи ──
    r2 = client.post(f"/api/v1/pets/{pet_id}/weight",
                     json={"weight_kg": 29.0},
                     headers=headers)
    log_test(
        "5.2 Добавление второй записи о весе",
        r2.status_code == 200,
        f"HTTP {r2.status_code} | вес: 29.0 кг"
    )

    # ── Тест 5.3: Получение истории веса ──
    r3 = client.get(f"/api/v1/pets/{pet_id}/weight", headers=headers)
    weights = r3.json() if r3.status_code == 200 else []
    log_test(
        "5.3 Получение истории веса питомца",
        r3.status_code == 200 and len(weights) >= 2,
        f"HTTP {r3.status_code} | записей в истории: {len(weights)}"
    )


# ════════════════════════════════════════════════════════════
# БЛОК 6: КАРТА
# ════════════════════════════════════════════════════════════

def test_map(client: httpx.Client, token: str):
    log_section("БЛОК 6: КАРТОГРАФИЧЕСКИЙ СЕРВИС")
    headers = {"Authorization": f"Bearer {token}"}

    # Координаты Москвы
    lat, lon = 55.7558, 37.6173

    categories = [
        ("vets",        "Ветеринарные клиники"),
        ("pet_store",   "Зоомагазины"),
        ("grooming",    "Груминг-салоны"),
        ("dog_park",    "Площадки для выгула"),
    ]

    for place_type, label in categories:
        r = client.get("/api/v1/map/vets",
                       params={"lat": lat, "lon": lon, "place_type": place_type},
                       headers=headers,
                       timeout=30)
        ok = r.status_code == 200 and isinstance(r.json(), list)
        count = len(r.json()) if ok else 0
        log_test(
            f"6.{categories.index((place_type, label))+1} Поиск: {label}",
            ok,
            f"HTTP {r.status_code} | найдено мест: {count}"
        )


# ════════════════════════════════════════════════════════════
# БЛОК 7: ОБРАБОТКА ОШИБОК И ГРАНИЧНЫЕ СЛУЧАИ
# ════════════════════════════════════════════════════════════

def test_errors(client: httpx.Client, token: str):
    log_section("БЛОК 7: ОБРАБОТКА ОШИБОК И ГРАНИЧНЫЕ СЛУЧАИ")
    headers = {"Authorization": f"Bearer {token}"}

    # ── Тест 7.1: Создание питомца с пустым именем ──
    r = client.post("/api/v1/pets",
                    json={"name": "", "breed": "Лабрадор"},
                    headers=headers)
    log_test(
        "7.1 Создание питомца с пустым именем (ожидается ошибка)",
        r.status_code in (400, 422),
        f"HTTP {r.status_code}"
    )

    # ── Тест 7.2: Запрос несуществующего питомца ──
    r2 = client.get("/api/v1/pets/nonexistent-id-12345/health", headers=headers)
    log_test(
        "7.2 Запрос медкарты несуществующего питомца (ожидается ошибка)",
        r2.status_code in (404, 403),
        f"HTTP {r2.status_code}"
    )

    # ── Тест 7.3: Создание напоминания с неверным форматом даты ──
    r3 = client.post("/api/v1/reminders",
                     json={"pet_id": "fake-id",
                           "title": "Тест",
                           "remind_at": "не-дата"},
                     headers=headers)
    log_test(
        "7.3 Создание напоминания с неверным форматом даты (ожидается ошибка)",
        r3.status_code in (400, 422, 404),
        f"HTTP {r3.status_code}"
    )

    # ── Тест 7.4: Удаление несуществующего напоминания ──
    r4 = client.delete("/api/v1/reminders/nonexistent-id", headers=headers)
    log_test(
        "7.4 Удаление несуществующего напоминания (ожидается ошибка)",
        r4.status_code in (404, 403),
        f"HTTP {r4.status_code}"
    )


# ════════════════════════════════════════════════════════════
# БЛОК 8: НАГРУЗОЧНОЕ ТЕСТИРОВАНИЕ
# ════════════════════════════════════════════════════════════

async def test_load():
    log_section("БЛОК 8: НАГРУЗОЧНОЕ ТЕСТИРОВАНИЕ API")
    print(f"  {YELLOW}Отправляем 10 одновременных запросов к /api/v1/auth/me...{RESET}")

    # Сначала получаем токен
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        ts = int(time.time())
        await client.post("/api/v1/auth/register",
                          json={"name": "Load Test",
                                "email": f"load_{ts}@test.com",
                                "password": "Pass123!"})
        r = await client.post("/api/v1/auth/login",
                              json={"email": f"load_{ts}@test.com",
                                    "password": "Pass123!"})
        if r.status_code != 200:
            log_test("8.1 Нагрузочный тест (10 запросов)", False, "Не удалось получить токен")
            return

        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Отправляем 10 запросов одновременно
        start = time.time()
        tasks = [client.get("/api/v1/pets", headers=headers) for _ in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = round(time.time() - start, 2)

        success_count = sum(
            1 for r in responses
            if not isinstance(r, Exception) and r.status_code == 200
        )
        avg_ms = round(elapsed / 10 * 1000)

        log_test(
            "8.1 10 одновременных запросов GET /pets",
            success_count == 10,
            f"Успешных: {success_count}/10 | Общее время: {elapsed}с | Среднее: ~{avg_ms}мс/запрос"
        )

        # Тест времени отклика одного запроса
        start2 = time.time()
        r2 = await client.get("/api/v1/pets", headers=headers)
        single_ms = round((time.time() - start2) * 1000)
        log_test(
            "8.2 Время отклика одного запроса",
            single_ms < 3000,
            f"Время отклика: {single_ms}мс {'(норма < 3000мс)' if single_ms < 3000 else '(превышена норма!)'}"
        )


# ════════════════════════════════════════════════════════════
# ОЧИСТКА ТЕСТОВЫХ ДАННЫХ
# ════════════════════════════════════════════════════════════

def cleanup(client: httpx.Client, token: str, pet_id: str):
    log_section("ОЧИСТКА ТЕСТОВЫХ ДАННЫХ")
    headers = {"Authorization": f"Bearer {token}"}
    if pet_id:
        r = client.delete(f"/api/v1/pets/{pet_id}", headers=headers)
        log_test(
            "Удаление тестового питомца",
            r.status_code == 200,
            f"HTTP {r.status_code}"
        )


# ════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ
# ════════════════════════════════════════════════════════════

async def main():
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  ТЕСТИРОВАНИЕ API СИСТЕМЫ PawCare{RESET}")
    print(f"{BOLD}  Сервер: {BASE_URL}{RESET}")
    print(f"{BOLD}  Время:  {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        # Проверка доступности сервера
        try:
            r = client.get("/docs")
            print(f"\n  {GREEN}Сервер доступен (HTTP {r.status_code}){RESET}")
        except Exception as e:
            print(f"\n  {RED}Сервер недоступен: {e}{RESET}")
            return

        # Запуск всех блоков тестов
        auth_data = test_auth(client)
        token = auth_data["token"]

        if not token:
            print(f"\n{RED}Не удалось получить токен. Дальнейшее тестирование невозможно.{RESET}")
            print_summary()
            return

        pet_id = test_pets(client, token)
        if pet_id:
            test_health(client, token, pet_id)
            test_reminders(client, token, pet_id)
            test_weight(client, token, pet_id)
        test_map(client, token)
        test_errors(client, token)

    # Нагрузочное тестирование (асинхронно)
    await test_load()

    # Очистка
    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        if pet_id:
            cleanup(client, token, pet_id)

    print_summary()


if __name__ == "__main__":
    asyncio.run(main())

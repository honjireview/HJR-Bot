# -*- coding: utf-8 -*-

# Этот модуль отвечает за хранение и управление данными активных апелляций.

# Словарь для хранения всех активных дел. Ключ - case_id.
active_appeals = {}

def create_appeal(case_id, initial_data):
    """Создает новую запись об апелляции."""
    if case_id in active_appeals:
        print(f"[ПРЕДУПРЕЖДЕНИЕ] Дело #{case_id} уже существует. Перезапись.")
    active_appeals[case_id] = initial_data
    print(f"Дело #{case_id} успешно создано.")

def get_appeal(case_id):
    """Возвращает данные по конкретному делу."""
    return active_appeals.get(case_id)

def update_appeal(case_id, key, value):
    """Обновляет поле в существующей апелляции."""
    if case_id in active_appeals:
        active_appeals[case_id][key] = value
    else:
        print(f"[ОШИБКА] Попытка обновить несуществующее дело #{case_id}.")

def add_council_answer(case_id, answer_data):
    """Добавляет ответ от редактора в список ответов."""
    if case_id in active_appeals:
        if 'council_answers' not in active_appeals[case_id]:
            active_appeals[case_id]['council_answers'] = []
        active_appeals[case_id]['council_answers'].append(answer_data)
        print(f"Добавлен ответ от Совета по делу #{case_id}.")
    else:
        print(f"[ОШИБКА] Попытка добавить ответ в несуществующее дело #{case_id}.")

def delete_appeal(case_id):
    """Удаляет дело из списка активных после его завершения."""
    if case_id in active_appeals:
        del active_appeals[case_id]
        print(f"Дело #{case_id} успешно закрыто и удалено.")

def get_all_appeals():
    """Возвращает все активные апелляции (для отладки)."""
    return active_appeals
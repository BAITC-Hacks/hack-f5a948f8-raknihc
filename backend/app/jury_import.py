"""Additive JSON/CSV import. Validate the whole batch before making any writes."""
import csv
import io
import json

from pydantic import ValidationError

from .engine_port import DomainError
from .schemas import Employee, HistoryRecord, JuryImportResult


class ImportProblem(DomainError):
    def __init__(self, issues, status=422):
        super().__init__(status, 'invalid_import', 'Импорт не сохранён. Исправьте указанные ошибки.')
        self.issues = issues[:100]


def import_profiles(store, request, as_of_date):
    issues = []

    def issue(file, row, field, message):
        issues.append(dict(file=file, row=row, field=field, message=message))

    def parse(model, value, file, row):
        try:
            return model.model_validate(value)
        except ValidationError as error:
            for item in error.errors(include_input=False, include_url=False)[:10]:
                field = '.'.join(str(part) for part in item['loc'])
                message = {'missing': 'Обязательное поле отсутствует.', 'extra_forbidden': 'Неизвестное поле.',
                           'int_type': 'Нужно целое число.', 'date_from_datetime_parsing': 'Нужна дата YYYY-MM-DD.'}.get(item['type'],
                           'Неверный тип или значение. Проверьте диапазон и допустимые значения поля.')
                issue(file, row, field, message)
            return None

    for file, content in [('employees.json', request.employees_json), ('history.csv', request.history_csv)]:
        if content is not None and len(content.encode('utf-8')) > 2_000_000:
            issue(file, None, '', 'Размер файла больше 2 МБ.')
    if issues:
        raise ImportProblem(issues)
    employees, history = [], []
    if not request.employees_json and not request.history_csv:
        raise ImportProblem([dict(file='files', row=None, field='', message='Выберите JSON профилей или CSV истории.')])
    if request.employees_json:
        try:
            document = json.loads(request.employees_json.lstrip('\ufeff'))
            if isinstance(document, dict):
                if set(document) - {'employees', 'meta'}:
                    raise ValueError('В обёртке допустимы только employees и meta.')
                meta = document.get('meta', {})
                if not isinstance(meta, dict):
                    raise ValueError('meta должен быть объектом.')
                if meta.get('as_of_date', as_of_date.isoformat()) != as_of_date.isoformat():
                    raise ValueError('Дата meta.as_of_date должна совпадать с датой среза сервера.')
                document = document.get('employees')
            if not isinstance(document, list) or not 1 <= len(document) <= 500:
                raise ValueError('Ожидается массив от 1 до 500 профилей или объект {employees: [...]}.')
            for index, value in enumerate(document, 1):
                employee = parse(Employee, value, 'employees.json', index)
                if employee:
                    employees.append((index, employee))
        except json.JSONDecodeError as error:
            issue('employees.json', error.lineno, '', f'Некорректный JSON, столбец {error.colno}.')
        except (ValueError, RecursionError) as error:
            issue('employees.json', None, '', str(error) if isinstance(error, ValueError) else 'Слишком глубокая вложенность JSON.')
    if request.history_csv:
        try:
            reader = csv.DictReader(io.StringIO(request.history_csv.lstrip('\ufeff')), strict=True)
            expected = set(HistoryRecord.model_fields) - {'completed_at'}
            fields = reader.fieldnames or []
            if set(fields) not in (expected, expected | {'completed_at'}) or len(fields) != len(set(fields)):
                raise ValueError('Неверные колонки CSV. Используйте заголовок из шаблона; разделитель — запятая.')
            for index, row in enumerate(reader, 2):
                if index > 10001:
                    raise ValueError('В одном импорте допускается до 10 000 строк истории.')
                if None in row or any(value is None for value in row.values()):
                    issue('history.csv', index, '', 'Число значений не совпадает с заголовком.')
                    continue
                record = parse(HistoryRecord, {key: value if value != '' else None for key, value in row.items()}, 'history.csv', index)
                if record:
                    history.append((index, record))
        except (ValueError, csv.Error) as error:
            issue('history.csv', None, '', str(error))
    if issues:
        raise ImportProblem(issues)
    # One transaction covers validation against current data and all inserts.
    with store.connect(write=not request.dry_run) as db:
        catalog = store.catalog(db)
        events = {event.event_id: event for event in store.events(db)}
        existing = {row['employee_id']: Employee.model_validate_json(row['payload']) for row in db.execute('SELECT * FROM employees')}
        existing_history = {row['record_id']: HistoryRecord.model_validate_json(row['payload']) for row in db.execute('SELECT record_id,payload FROM history')}
        skill_ids = {skill.skill_id for skill in catalog.skills}
        role_keys = {(row.role, row.grade) for row in catalog.role_profiles}
        employee_ids = set(existing) | {employee.employee_id for _, employee in employees}
        seen, add_employees, skipped_employees = set(), [], 0
        for index, employee in employees:
            def problem(field, message):
                issue('employees.json', index, field, message)
            if employee.employee_id in seen:
                problem('employee_id', 'Повтор ID в файле.')
            seen.add(employee.employee_id)
            if (employee.role, employee.grade) not in role_keys:
                problem('role/grade', 'Роль и грейд не найдены в каталоге требований.')
            for skill_id in set(employee.skills) - skill_ids:
                problem('skills.' + skill_id, 'Неизвестный ID навыка.')
            if employee.manager_id is not None and employee.manager_id not in employee_ids:
                problem('manager_id', 'Руководитель не найден в базе или этом импорте.')
            if employee.manager_id == employee.employee_id:
                problem('manager_id', 'Сотрудник не может быть своим руководителем.')
            if employee.career_goal and (employee.career_goal.target_role, employee.career_goal.target_grade) not in role_keys:
                problem('career_goal', 'Целевая роль и грейд не найдены в каталоге.')
            if not employee.hire_date <= employee.last_review_date <= as_of_date:
                problem('last_review_date', 'Дата оценки должна быть между датой найма и датой среза.')
            if employee.employee_id in existing:
                if employee != existing[employee.employee_id]:
                    problem('employee_id', 'ID уже существует с другими данными. Перезапись профилей запрещена.')
                else:
                    skipped_employees += 1
            else:
                add_employees.append(employee)
        occurrences = set()
        for record in existing_history.values():
            if record.status == 'completed' and not events[record.event_id].mandatory:
                occurrences.add((record.employee_id, record.event_id, record.date if record.event_id == 'EV_036' else None))
        seen, add_history, skipped_history = set(), [], 0
        for index, record in history:
            def problem(field, message):
                issue('history.csv', index, field, message)
            if record.record_id in seen:
                problem('record_id', 'Повтор ID в файле.')
            seen.add(record.record_id)
            if record.employee_id not in employee_ids:
                problem('employee_id', 'Сотрудник не найден в базе или JSON профилей.')
            if record.event_id not in events:
                problem('event_id', 'Мероприятие не найдено в каталоге.')
            if record.date > as_of_date or (record.completed_at and not record.date <= record.completed_at <= as_of_date):
                problem('date/completed_at', 'Дата записи не позже среза; завершение — между датой записи и срезом.')
            if record.record_id in existing_history:
                if record != existing_history[record.record_id]:
                    problem('record_id', 'ID уже существует с другими данными. Перезапись истории запрещена.')
                else:
                    skipped_history += 1
                continue
            event = events.get(record.event_id)
            if record.status == 'completed' and event and not event.mandatory:
                occurrence = (record.employee_id, record.event_id, record.date if record.event_id == 'EV_036' else None)
                if occurrence in occurrences:
                    problem('event_id', 'Это мероприятие или сессия уже завершены. Второе начисление запрещено.')
                occurrences.add(occurrence)
            add_history.append(record)
        if issues:
            raise ImportProblem(issues)
        if not request.dry_run:
            db.executemany('INSERT INTO employees VALUES (?,?)', [(row.employee_id, row.model_dump_json()) for row in add_employees])
            db.executemany('INSERT INTO history VALUES (?,?,?,?,?,?)', [(row.record_id, row.employee_id, row.event_id,
                           row.date.isoformat(), row.status, row.model_dump_json()) for row in add_history])
        return JuryImportResult(dry_run=request.dry_run, employees_added=len(add_employees), employees_skipped=skipped_employees,
            history_added=len(add_history), history_skipped=skipped_history, employee_ids=[row.employee_id for _, row in employees])

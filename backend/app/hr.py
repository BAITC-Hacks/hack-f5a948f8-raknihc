"""HR-only aggregates, with no score or ranking of employees."""
from collections import Counter, defaultdict

from .engine_port import DomainError
from .schemas import Employee, EngineContext, HistoryRecord, HREmployee, HREventStats, HROverview, HRSkillGap


def overview(store, engine, as_of_date):
    with store.connect() as db:
        profiles = [Employee.model_validate_json(row['payload']) for row in db.execute('SELECT payload FROM employees ORDER BY employee_id')]
        events = store.events(db)
        if not profiles:
            return HROverview(as_of_date=as_of_date, mode=engine.mode, employees=[], skill_gaps=[], events=[],
                              no_step_count=0, unavailable_count=0, message='Сначала загрузите стартовый датасет.')
        catalog = store.catalog(db)
        histories = defaultdict(list)
        for row in db.execute('SELECT payload FROM history ORDER BY date,record_id'):
            record = HistoryRecord.model_validate_json(row['payload'])
            if record.date <= as_of_date:
                histories[record.employee_id].append(record)
    engine = engine.for_bulk() if hasattr(engine, "for_bulk") else engine
    employees, gaps, critical = [], Counter(), Counter()
    event_histories = defaultdict(list)
    for history in histories.values():
        for record in history:
            event_histories[record.event_id].append(record)
    for profile in profiles:
        ctx = EngineContext(profile=profile, history=histories[profile.employee_id], events=events, catalog=catalog, as_of_date=as_of_date)
        count = None
        try:
            trajectory = engine.trajectory(ctx)
            count = trajectory.critical_gap_count
            for requirement in trajectory.requirements:
                if requirement.gap > 0:
                    gaps[requirement.skill_id] += 1
                    if requirement.critical:
                        critical[requirement.skill_id] += 1
            result = engine.recommend(ctx)
            status = 'available' if result.items else 'none'
            reason = result.message
        except (DomainError, TimeoutError):
            status, reason = 'unavailable', 'Расчёт временно недоступен. Обновите данные позже.'
        employees.append(HREmployee(employee_id=profile.employee_id, full_name=profile.full_name,
            department=profile.department, role=profile.role, grade=profile.grade,
            recommendation_status=status, reason=reason, critical_gap_count=count))
    names = {skill.skill_id: skill.name for skill in catalog.skills}
    skill_gaps = [HRSkillGap(skill_id=key, name=names[key], employees_count=value, critical_count=critical[key])
                 for key, value in sorted(gaps.items(), key=lambda row: (-row[1], names[row[0]]))]
    stats = []
    for event in events:
        rows = event_histories[event.event_id]
        counts = Counter(row.status for row in rows)
        stats.append(HREventStats(event_id=event.event_id, title=event.title,
            participants=len({row.employee_id for row in rows}), records=len(rows), completed=counts['completed'],
            in_progress=counts['in_progress'], other=len(rows) - counts['completed'] - counts['in_progress']))
    return HROverview(as_of_date=as_of_date, mode=engine.mode, employees=employees, skill_gaps=skill_gaps, events=stats,
        no_step_count=sum(row.recommendation_status == 'none' for row in employees),
        unavailable_count=sum(row.recommendation_status == 'unavailable' for row in employees),
        message='Дефициты относительно заданных целей; участие по записям истории на дату среза. Повторные сессии считаются отдельно. Список сотрудников упорядочен по ID.')

"""Deterministic catalog adapter; assessment plus completed history, no LLM or ranking."""
from .engine_port import DomainError
from .schemas import (ActivityRequest, EngineContext, Event, Recommendation, RecommendationResponse,
                      SimulationResponse, SkillChange, SkillRequirement, TrajectoryResponse)

MESSAGE = "Ожидаемый прирост рассчитан по правилам мероприятия. Общий прогресс к цели пока не рассчитан."


class MockEngine:
    mode = "mock"

    def _current_context(self, context: EngineContext) -> EngineContext:
        ctx = context.model_copy(deep=True)
        events = {event.event_id: event for event in ctx.events}
        seen = set()
        for row in sorted(ctx.history, key=lambda row: (row.completed_at or row.date, row.record_id)):
            if row.status != "completed":
                continue
            completed_on = row.completed_at or row.date
            event = events.get(row.event_id)
            if event is None or completed_on > ctx.as_of_date:
                continue
            # Mandatory training may repeat annually; the club repeats per session.
            occurrence = (row.event_id, row.date if event.mandatory or row.event_id == "EV_036" else None)
            if occurrence in seen:
                continue
            seen.add(occurrence)
            if completed_on <= ctx.profile.last_review_date:
                continue
            for change in self._skill_changes(ctx, event):
                ctx.profile.skills[change.skill_id] = change.after
        return ctx

    def trajectory(self, context: EngineContext) -> TrajectoryResponse:
        context = self._current_context(context)
        profile = context.profile
        target = profile.career_goal
        target_profile = next((r for r in context.catalog.role_profiles if target and
                               (r.role, r.grade) == (target.target_role, target.target_grade)), None)
        skills = {skill.skill_id: skill for skill in context.catalog.skills}
        requirements = []
        if target_profile:
            for skill_id, required_level in target_profile.required_skills.items():
                skill = skills[skill_id]
                current_level = profile.skills.get(skill_id, 0)
                requirements.append(SkillRequirement(
                    skill_id=skill_id, name=skill.name, type=skill.type,
                    current_level=current_level, required_level=required_level,
                    gap=max(0, required_level - current_level),
                    critical=skill_id in target_profile.critical_skills,
                ))
        requirements.sort(key=lambda row: (not (row.critical and row.gap > 0), -row.gap, row.name))
        return TrajectoryResponse(
            employee_id=profile.employee_id, as_of_date=context.as_of_date,
            assessed_on=profile.last_review_date, mode=self.mode, skills_basis="current", current_skills=profile.skills,
            target=target, status="target_set" if target_profile else ("no_goal" if target is None else "target_unavailable"),
            requirements=requirements, met_count=sum(row.gap == 0 for row in requirements),
            critical_gap_count=sum(row.critical and row.gap > 0 for row in requirements),
            progress_pct=None, message="Учтены завершения после оценки. Если дата завершения неизвестна, используется дата записи истории. Общий прогресс не рассчитан.",
        )

    def _eligible(self, ctx: EngineContext, event: Event) -> bool:
        profile = ctx.profile
        return (
            not event.mandatory
            and profile.role in event.target_roles
            and profile.grade in event.target_grades
            and all(profile.skills.get(skill, 0) >= level for skill, level in event.prerequisites.items())
            and any(profile.skills.get(g.skill_id, 0) < g.max_level and g.gain > 0 for g in event.develops_skills)
            and (event.event_id == "EV_036" or not any(
                h.event_id == event.event_id and h.status == "completed" for h in ctx.history))
        )

    def _sessions(self, ctx: EngineContext, event: Event):
        completed = {h.date for h in ctx.history if h.event_id == event.event_id and h.status == "completed"}
        return [day for day in sorted(event.upcoming_sessions) if day >= ctx.as_of_date and day not in completed]

    def _skill_changes(self, context: EngineContext, event: Event) -> list[SkillChange]:
        skills = {skill.skill_id: skill.name for skill in context.catalog.skills}
        changes = []
        for development in event.develops_skills:
            before = context.profile.skills.get(development.skill_id, 0)
            after = max(before, min(development.max_level, before + development.gain))
            changes.append(SkillChange(skill_id=development.skill_id, name=skills[development.skill_id],
                                       before=before, after=after, gain=after - before))
        return changes

    def _reasons(self, context: EngineContext, event: Event, changes: list[SkillChange]) -> list[str]:
        profile = context.profile
        target = next((row for row in context.catalog.role_profiles if profile.career_goal and
                       (row.role, row.grade) == (profile.career_goal.target_role, profile.career_goal.target_grade)), None)
        relevant = next((change for change in changes if change.gain > 0 and target and
                         change.skill_id in target.critical_skills and
                         change.before < target.required_skills[change.skill_id]), None)
        if relevant:
            benefit = f"Развивает критический навык {relevant.name}: {relevant.before} → {relevant.after}; для цели требуется {target.required_skills[relevant.skill_id]}."
        else:
            growing = [change.name for change in changes if change.gain > 0]
            benefit = "Развивает навыки с учётом завершённого обучения: " + ", ".join(growing) + "."
        return [
            f"Подходит вашей роли {profile.role} и грейду {profile.grade}.", benefit,
            "Эта сессия ещё не отмечена завершённой." if event.event_id == "EV_036" else
            "В истории нет завершения этого добровольного мероприятия.",
        ]

    def recommend(self, context: EngineContext) -> RecommendationResponse:
        context = self._current_context(context)
        items = []
        for event in context.events:
            if not self._eligible(context, event):
                continue
            sessions = self._sessions(context, event)
            if event.format != "self_paced" and not sessions:
                continue
            changes = self._skill_changes(context, event)
            items.append(Recommendation(
                event_id=event.event_id, title=event.title, format=event.format,
                duration_hours=event.duration_hours,
                session_date=sessions[0] if event.format != "self_paced" else None,
                reasons=self._reasons(context, event, changes),
                score=None, skill_changes=changes,
            ))
            if len(items) == 3:
                break
        return RecommendationResponse(
            employee_id=context.profile.employee_id, as_of_date=context.as_of_date,
            mode=self.mode, current_skills=context.profile.skills, progress_pct=None,
            items=items, assessed_on=context.profile.last_review_date, skills_basis="current",
            message=MESSAGE if items else "В каталоге нет доступных шагов с приростом навыков для вашего профиля: проверьте цель, требования, расписание и уже завершённое обучение.",
        )

    def simulate(self, context: EngineContext, request: ActivityRequest) -> SimulationResponse:
        context = self._current_context(context)
        event = next((e for e in context.events if e.event_id == request.event_id), None)
        if event is None:
            raise DomainError(404, "event_not_found", "Мероприятие не найдено")
        if not self._eligible(context, event):
            raise DomainError(409, "event_unavailable", "Мероприятие недоступно или уже выполнено")
        if event.format == "self_paced":
            if request.session_date is not None:
                raise DomainError(422, "unexpected_session", "Для self_paced не нужна дата сессии")
        elif request.session_date not in self._sessions(context, event):
            raise DomainError(409, "session_unavailable", "Выберите доступную дату сессии")
        changes = self._skill_changes(context, event)
        before = dict(context.profile.skills)
        before.update({change.skill_id: change.before for change in changes})
        after = before | {change.skill_id: change.after for change in changes}
        return SimulationResponse(
            employee_id=context.profile.employee_id, event_id=event.event_id,
            as_of_date=context.as_of_date, session_date=request.session_date, mode=self.mode,
            skills_before=before, skills_after=after, skill_changes=changes,
            progress_before_pct=None, progress_after_pct=None, message=MESSAGE,
            assessed_on=context.profile.last_review_date, skills_basis="current",
        )

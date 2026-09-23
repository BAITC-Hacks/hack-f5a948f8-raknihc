"""Honest UI stub: no skill reconstruction, gains, scoring, or LLM calls."""
from .engine_port import DomainError
from .schemas import ActivityRequest, EngineContext, Event, Recommendation, RecommendationResponse, SimulationResponse

MESSAGE = "Mock: алгоритм AI ещё не подключён; навыки взяты из последней оценки, прогресс не рассчитан."


class MockEngine:
    mode = "mock"

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

    def recommend(self, context: EngineContext) -> RecommendationResponse:
        items = []
        for event in context.events:
            if not self._eligible(context, event):
                continue
            sessions = self._sessions(context, event)
            if event.format != "self_paced" and not sessions:
                continue
            items.append(Recommendation(
                event_id=event.event_id, title=event.title, format=event.format,
                duration_hours=event.duration_hours,
                session_date=sessions[0] if event.format != "self_paced" else None,
                reasons=["Роль и грейд входят в целевую аудиторию.",
                         "Предварительные требования соблюдены по последней оценке.",
                         "Мероприятие добровольное; выполнение этой активности или сессии не зарегистрировано."],
                score=None,
            ))
            if len(items) == 3:
                break
        return RecommendationResponse(
            employee_id=context.profile.employee_id, as_of_date=context.as_of_date,
            mode=self.mode, current_skills=context.profile.skills, progress_pct=None,
            items=items, message=MESSAGE + (" Нет подходящих mock-кандидатов." if not items else ""),
        )

    def simulate(self, context: EngineContext, request: ActivityRequest) -> SimulationResponse:
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
        return SimulationResponse(
            employee_id=context.profile.employee_id, event_id=event.event_id,
            as_of_date=context.as_of_date, session_date=request.session_date, mode=self.mode,
            skills_before=context.profile.skills, skills_after=context.profile.skills,
            progress_before_pct=None, progress_after_pct=None, message=MESSAGE,
        )

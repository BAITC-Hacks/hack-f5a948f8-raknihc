"""Application boundary for the frozen AI Engine. No persistence or ranking here."""
from .engine import recommend as ai_recommend
from .engine.simulator import digital_twin
from .engine.state_builder import build_state, REPEATABLE
from .engine.gap_analyzer import readiness, next_grade_target
from .engine_port import DomainError
from .schemas import (Recommendation, RecommendationResponse, SimulationResponse,
                      SkillChange, SkillRequirement, TrajectoryResponse, CareerGoal)


class RealAIEngineAdapter:
    mode = "live"

    def __init__(self, *, use_llm=False):
        self.use_llm = use_llm

    def for_bulk(self):
        """A separate instance avoids toggling shared request state during HR calls."""
        return type(self)(use_llm=False)

    @staticmethod
    def _inputs(context):
        data = context.model_dump(mode="json")
        events = {event["event_id"]: event for event in data["events"]}
        own_rows = [row for row in data["history"]
                    if row["employee_id"] == data["profile"]["employee_id"]]
        done_sessions = set()
        for row in own_rows:
            if row["status"] != "completed":
                continue
            event = events.get(row["event_id"])
            if event is None:
                raise DomainError(422, "invalid_engine_context", "Unknown history event")
            completed_at = row.get("completed_at")
            if completed_at and completed_at < row["date"]:
                raise DomainError(422, "invalid_completion_date", "Completion precedes the history date")
            if event["format"] == "self_paced":
                if completed_at:
                    row["date"] = completed_at
            elif completed_at and completed_at != row["date"]:
                # The frozen engine uses one date for both reconstruction and history.
                # Refuse ambiguous scheduled data instead of moving a session silently.
                raise DomainError(422, "scheduled_completion_date_mismatch",
                                  "Scheduled completion date must match its session date for AI calculation")
            if row["event_id"] == REPEATABLE and row["date"] <= data["as_of_date"]:
                done_sessions.add(row["date"])
        if REPEATABLE in events:
            events[REPEATABLE]["upcoming_sessions"] = [
                day for day in events[REPEATABLE]["upcoming_sessions"] if day not in done_sessions]
        return dict(employee=data["profile"], history=own_rows, events=data["events"],
                    catalog=data["catalog"], as_of_date=data["as_of_date"])

    @staticmethod
    def _state(inputs):
        try:
            return build_state(**inputs)
        except (ValueError, KeyError, TypeError) as exc:
            raise DomainError(422, "invalid_engine_context", "Profile/history cannot be evaluated against the catalog") from exc

    @staticmethod
    def _changes(before, after, catalog):
        names = {skill.skill_id: skill.name for skill in catalog.skills}
        return [SkillChange(skill_id=key, name=names[key], before=before.get(key, 0),
                            after=level, gain=level - before.get(key, 0))
                for key, level in after.items() if level != before.get(key, 0)]

    @staticmethod
    def _message(context, warnings):
        # The frozen engine warns for every self-paced completion, even when the
        # adapter supplied a precise date. Suppress only those now-resolved warnings.
        precise = {row.record_id for row in context.history if row.completed_at is not None}
        warnings = [warning for warning in warnings if not any(
            warning == f"Completion date unavailable; enrollment date used: {record}"
            for record in precise)]
        return " ".join(["Readiness is target skill coverage, not a promotion guarantee.", *warnings])

    def recommend(self, context):
        inputs = self._inputs(context)
        levels, _, _, _, warnings = self._state(inputs)
        result = ai_recommend(**inputs, limit=3, use_llm=self.use_llm)
        events = {event["event_id"]: event for event in inputs["events"]}
        names = {skill.skill_id: skill.name for skill in context.catalog.skills}
        items = []
        for item in result["recommendations"]:
            event = events[item["event_id"]]
            session = None if event["format"] == "self_paced" else min(
                day for day in event["upcoming_sessions"] if day >= inputs["as_of_date"])
            items.append(Recommendation(
                event_id=item["event_id"], title=item["title"], format=event["format"],
                duration_hours=event["duration_hours"], session_date=session,
                score=item["final_score"], reasons=[item["why_this"], item["why_not"]],
                skill_changes=[SkillChange(name=names[change["skill_id"]], **change)
                               for change in item["skill_impacts"]],
                readiness_before=result["readiness_before"], readiness_after=item["readiness_after"],
                **{key: item[key] for key in ("explanation", "why_this", "why_not",
                    "expected_career_impact", "caution", "explanation_source")}))
        message = self._message(context, warnings)
        if not items:
            message = "No eligible activity closes a career skill gap at this date. " + message
        return RecommendationResponse(employee_id=result["employee_id"], as_of_date=context.as_of_date,
            mode=self.mode, current_skills=levels, progress_pct=result["readiness_before"],
            readiness_before=result["readiness_before"], items=items, message=message,
            skills_basis="current", assessed_on=context.profile.last_review_date)

    def trajectory(self, context):
        inputs = self._inputs(context)
        levels, target, _, _, warnings = self._state(inputs)
        skills = {skill.skill_id: skill for skill in context.catalog.skills}
        requirements = [SkillRequirement(skill_id=key, name=skills[key].name,
            type=skills[key].type, current_level=levels.get(key, 0), required_level=required,
            gap=max(0, required - levels.get(key, 0)), critical=key in target["critical_skills"])
            for key, required in target["required_skills"].items()]
        requirements.sort(key=lambda row: (not (row.critical and row.gap), -row.gap, row.name))
        explicit = context.profile.career_goal is not None
        source = "explicit" if explicit else "automatic"
        message = ("Employee-selected career target. " if explicit else
                   "Automatically calculated effective target; not selected by the employee. ")
        return TrajectoryResponse(employee_id=context.profile.employee_id,
            as_of_date=context.as_of_date, assessed_on=context.profile.last_review_date,
            mode=self.mode, skills_basis="current", current_skills=levels,
            target=CareerGoal(target_role=target["role"], target_grade=target["grade"]),
            target_source=source, status="target_set", requirements=requirements,
            met_count=sum(row.gap == 0 for row in requirements),
            critical_gap_count=sum(row.critical and row.gap > 0 for row in requirements),
            progress_pct=readiness(levels, target), message=message + self._message(context, warnings))

    def simulate(self, context, request):
        inputs = self._inputs(context)
        event = next((e for e in inputs["events"] if e["event_id"] == request.event_id), None)
        if event is None:
            raise DomainError(404, "event_not_found", "Activity not found")
        if event["format"] == "self_paced":
            if request.session_date is not None:
                raise DomainError(422, "unexpected_session", "Self-paced activities have no session date")
        elif (request.session_date is None or request.session_date < context.as_of_date
              or request.session_date.isoformat() not in event["upcoming_sessions"]):
            raise DomainError(409, "session_unavailable", "Select an available, uncompleted session")
        levels, target, _, completed, warnings = self._state(inputs)
        profile = inputs["employee"]
        if (event["mandatory"] or profile["role"] not in event["target_roles"]
                or profile["grade"] not in event["target_grades"]
                or (event["event_id"] in completed and event["event_id"] != REPEATABLE)
                or any(levels.get(key, 0) < value for key, value in event["prerequisites"].items())
                or not any(levels.get(g["skill_id"], 0) < g["max_level"] and g["gain"] > 0
                           for g in event["develops_skills"])):
            raise DomainError(409, "event_unavailable", "Activity is unavailable for this employee")
        # Completion/simulation may grow a non-target skill even with readiness=100.
        # Recommendation selection is still exclusively owned by ai_recommend.
        result = digital_twin(levels, event, target,
                              next_grade_target(profile, inputs["catalog"]), inputs["catalog"])
        return SimulationResponse(employee_id=context.profile.employee_id,
            event_id=request.event_id, as_of_date=context.as_of_date, session_date=request.session_date,
            mode=self.mode, skills_before=result["skills_before"], skills_after=result["skills_after"],
            skill_changes=self._changes(result["skills_before"], result["skills_after"], context.catalog),
            progress_before_pct=result["readiness_before"], progress_after_pct=result["readiness_after"],
            skills_basis="current", assessed_on=context.profile.last_review_date,
            message=self._message(context, warnings))

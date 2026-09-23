"""Integration boundary; production algorithms belong to app/engine/."""
from typing import Protocol
from .schemas import ActivityRequest, EngineContext, Mode, RecommendationResponse, SimulationResponse


class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Engine(Protocol):
    mode: Mode

    def recommend(self, context: EngineContext) -> RecommendationResponse: ...

    def simulate(self, context: EngineContext, request: ActivityRequest) -> SimulationResponse: ...

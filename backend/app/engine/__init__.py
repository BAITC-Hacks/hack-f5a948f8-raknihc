"""Application entry point: recommend. Legacy calculation imports remain supported."""

from .core import analyze, load_dataset, simulate
from .api import recommend

__all__ = ["recommend", "analyze", "load_dataset", "simulate"]

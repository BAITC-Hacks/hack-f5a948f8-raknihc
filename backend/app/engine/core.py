"""Compatibility imports for the original engine API."""
from .data_loader import load_dataset
from .recommender import analyze, simulate

__all__ = ["load_dataset", "analyze", "simulate"]

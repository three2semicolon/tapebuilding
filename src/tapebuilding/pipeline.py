"""Composable pipeline builder and executor."""

from __future__ import annotations
from typing import Callable, Dict

class Pipeline:
    """A simple composable pipeline."""

    def __init__(self) -> None:
        self.steps: Dict[str, Callable] = {}

    def add_step(self, name: str, func: Callable) -> None:
        """Add a step to the pipeline."""
        self.steps[name] = func

    def run(self, context: Dict) -> Dict:
        """Execute the pipeline steps in insertion order."""
        for name in self.steps:
            step_func = self.steps[name]
            if callable(step_func):
                step_func(context)
        return context
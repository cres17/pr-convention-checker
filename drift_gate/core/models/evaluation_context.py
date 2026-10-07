"""Explicit date input for deterministic expiry decisions; no clock reads."""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EvaluationContext:
    evaluated_on: date

    def __post_init__(self):
        if type(self.evaluated_on) is not date:
            raise ValueError('evaluated_on must be a date')

    def to_dict(self):
        return {'evaluated_on': self.evaluated_on.isoformat(), 'date_basis': 'UTC'}

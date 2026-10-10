"""Whole-inspection resource budget and usage record (design W12).

One budget object is threaded through collection and analysis stages. Each
stage consumes named units; exceeding a limit raises ``ResourceLimit`` with the
observed usage, which callers report as the ``resource_limit`` reason rather
than as a partial success. The defaults below are bounds with headroom over
this repository's measured full-PR capture (125 MB total, 3,688 files); they
are not a service-level guarantee. Time is supplied by the adapter's clock.
"""
from dataclasses import dataclass, field

DEFAULTS = {
    'max_files': 20_000,
    'max_total_bytes': 256_000_000,
    'max_git_calls': 50_000,
    'max_wall_seconds': 1_800,
    'max_graph_edges': 200_000,
    'max_report_bytes': 64_000_000,
    'max_memory_bytes': 2_000_000_000,
}
UNITS = {'files': 'max_files', 'bytes': 'max_total_bytes', 'git_calls': 'max_git_calls',
         'graph_edges': 'max_graph_edges', 'report_bytes': 'max_report_bytes'}


class ResourceLimit(RuntimeError):
    def __init__(self, unit, limit, observed, stage):
        super().__init__(f'resource limit {unit}={limit} exceeded at {stage} (observed {observed})')
        self.unit, self.limit, self.observed, self.stage = unit, limit, observed, stage

    def to_dict(self):
        return {'reason_code': 'resource_limit', 'unit': self.unit, 'limit': self.limit,
                'observed': self.observed, 'stage': self.stage}


@dataclass
class InspectionBudget:
    limits: dict
    clock: object = None          # callable returning monotonic seconds; None disables wall checks
    started: float = 0.0
    usage: dict = field(default_factory=lambda: {unit: 0 for unit in UNITS})
    stages: dict = field(default_factory=dict)

    @classmethod
    def from_policy(cls, budget, *, clock=None):
        limits = dict(DEFAULTS)
        if budget is not None:
            for name in DEFAULTS:
                value = getattr(budget, name, None)
                if value is not None:
                    if type(value) is not int or value < 1:
                        raise ValueError(f'budget.{name} must be a positive integer')
                    limits[name] = value
        started = clock() if clock else 0.0
        return cls(limits, clock, started)

    def consume(self, unit, amount=1, *, stage):
        if unit not in UNITS:
            raise ValueError(f'unknown budget unit {unit}')
        if type(amount) is not int or amount < 0:
            raise ValueError('budget amount must be a nonnegative integer')
        self.usage[unit] += amount
        self.stages.setdefault(stage, {}).setdefault(unit, 0)
        self.stages[stage][unit] += amount
        limit = self.limits[UNITS[unit]]
        if self.usage[unit] > limit:
            raise ResourceLimit(unit, limit, self.usage[unit], stage)
        self.check_time(stage)

    def check_time(self, stage):
        if self.clock is None:
            return
        elapsed = self.clock() - self.started
        if elapsed > self.limits['max_wall_seconds']:
            raise ResourceLimit('wall_seconds', self.limits['max_wall_seconds'], round(elapsed, 3), stage)

    def to_dict(self):
        elapsed = round(self.clock() - self.started, 3) if self.clock else None
        return {'schema': 'inspection-budget-v1', 'limits': dict(self.limits), 'usage': dict(self.usage),
                'elapsed_seconds': elapsed, 'by_stage': {k: dict(v) for k, v in sorted(self.stages.items())},
                'memory_enforcement': 'worker-process-rlimit-where-supported'}

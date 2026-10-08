"""Interval evaluation of document membership (design W08 6.4).

Code changes and document facts are both given as bounds ``lower ⊆ actual ⊆
upper`` (``upper=None`` is top: the set could not be closed). The rules are
sound over a finite, closed identity universe: T and F are returned only when
every admissible interpretation agrees. They ignore correlations between the
bounds, so some decidable cases stay U.

Route R: every added route is documented and no removed route remains.
  T  if  added.upper ⊆ doc.lower  and  removed.upper ∩ doc.upper = ∅
  F  if  added.lower − doc.upper ≠ ∅  or  removed.lower ∩ doc.lower ≠ ∅
Env R: every new key is documented (removal is not an env duty).
  T  if  added.upper ⊆ doc.lower
  F  if  added.lower − doc.upper ≠ ∅
"""
from dataclasses import dataclass

from drift_gate.core.contracts.planner import Truth
from drift_gate.core.models.facts import BoundedDelta, ExactDelta, UnknownDelta


@dataclass(frozen=True)
class Bounds:
    lower: frozenset
    upper: frozenset | None

    def __post_init__(self):
        if not isinstance(self.lower, frozenset) or (self.upper is not None and not isinstance(self.upper, frozenset)):
            raise ValueError('bounds require frozensets (upper None means unbounded)')
        if self.upper is not None and not self.lower <= self.upper:
            raise ValueError('lower bound must be a subset of the upper bound')

    @classmethod
    def exact(cls, values):
        values = frozenset(values)
        return cls(values, values)

    @classmethod
    def unknown(cls, known=()):
        return cls(frozenset(known), None)


def delta_bounds(delta):
    """(added, removed) bounds of a typed identity delta."""
    if isinstance(delta, ExactDelta):
        return Bounds.exact(delta.added), Bounds.exact(delta.removed)
    if isinstance(delta, (BoundedDelta, UnknownDelta)):
        return Bounds(delta.added_must, delta.added_may), Bounds(delta.removed_must, delta.removed_may)
    raise ValueError('expected a typed identity delta')


def route_requirement(added, removed, document):
    for value in (added, removed, document):
        if not isinstance(value, Bounds):
            raise ValueError('route membership requires bounds')
    if document.upper is not None and added.lower - document.upper:
        return Truth.FALSE
    if removed.lower & document.lower:
        return Truth.FALSE
    removed_absent = removed.upper is not None and (
        not removed.upper or document.upper is not None and not (removed.upper & document.upper))
    if added.upper is not None and added.upper <= document.lower and removed_absent:
        return Truth.TRUE
    return Truth.UNKNOWN


def env_requirement(added, document):
    if not isinstance(added, Bounds) or not isinstance(document, Bounds):
        raise ValueError('environment membership requires bounds')
    if document.upper is not None and added.lower - document.upper:
        return Truth.FALSE
    if added.upper is not None and added.upper <= document.lower:
        return Truth.TRUE
    return Truth.UNKNOWN

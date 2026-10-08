"""Pure run lifecycle, latest-result fencing and publication reconciliation.

No clock, filesystem, network or subprocess access: adapters supply time,
identifiers and persistence, and decide nothing these functions reject.
"""

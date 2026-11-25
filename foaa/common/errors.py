from __future__ import annotations


class FoaaError(Exception):
    """Base class for every error raised by FOAA."""


class InvalidPlanError(FoaaError):
    """A center produced a plan that cannot be executed (unknown petal, cycle, empty...)."""


class ModelOutputError(FoaaError):
    """A model answer could not be interpreted according to the expected contract."""

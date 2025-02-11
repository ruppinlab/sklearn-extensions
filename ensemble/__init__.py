"""
The :mod:`sklearn.ensemble` module includes ensemble-based methods for
classification, regression and anomaly detection.
"""

from ._cached import (
    CachedExtraTreesClassifier, CachedGradientBoostingClassifier,
    CachedRandomForestClassifier)


__all__ = ['CachedExtraTreesClassifier',
           'CachedRandomForestClassifier',
           'CachedGradientBoostingClassifier']

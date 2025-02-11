"""
The :mod:`sklearn.metrics` module includes score functions, performance metrics
and pairwise metrics and distance computations.
"""

from ._regression import mean_tweedie_deviance
from ._regression import mean_poisson_deviance
from ._regression import mean_gamma_deviance

from ._scorer import check_scoring
from ._scorer import make_scorer
from ._scorer import SCORERS
from ._scorer import get_scorer


__all__ = ['check_scoring',
           'get_scorer',
           'make_scorer',
           'mean_poisson_deviance',
           'mean_gamma_deviance',
           'mean_tweedie_deviance',
           'SCORERS']

"""
The :mod:`sklearn.metrics.scorer` submodule implements a flexible
interface for model selection and evaluation using
arbitrary score functions.

A scorer object is a callable that can be passed to
:class:`sklearn.model_selection.GridSearchCV` or
:func:`sklearn.model_selection.cross_val_score` as the ``scoring``
parameter, to specify how a model should be evaluated.

The signature of the call is ``(estimator, X, y)`` where ``estimator``
is the model to be evaluated, ``X`` is the test data and ``y`` is the
ground truth labeling (or ``None`` in the case of unsupervised models).
"""

# Authors: Andreas Mueller <amueller@ais.uni-bonn.de>
#          Lars Buitinck
#          Arnaud Joly <arnaud.v.joly@gmail.com>
#          Leandro Hermida <hermidal@cs.umd.edu>
# License: Simplified BSD

from collections.abc import Iterable
from functools import partial
from collections import Counter
import warnings

import numpy as np

from sklearn.metrics import (r2_score, median_absolute_error, max_error,
                             mean_absolute_error, mean_squared_error,
                             mean_squared_log_error, accuracy_score, f1_score,
                             roc_auc_score, average_precision_score,
                             precision_score, recall_score, log_loss,
                             balanced_accuracy_score, explained_variance_score,
                             brier_score_loss, jaccard_score)

from sklearn.metrics.cluster import (adjusted_rand_score, homogeneity_score,
                                     completeness_score, v_measure_score,
                                     mutual_info_score,
                                     adjusted_mutual_info_score,
                                     normalized_mutual_info_score,
                                     fowlkes_mallows_score)

from sklearn.utils.multiclass import type_of_target
from sklearn.base import is_regressor

from . import mean_gamma_deviance, mean_poisson_deviance


def _cached_call(cache, estimator, method, *args, **kwargs):
    """Call estimator with method and args and kwargs."""
    if cache is None:
        return getattr(estimator, method)(*args, **kwargs)

    try:
        return cache[method]
    except KeyError:
        result = getattr(estimator, method)(*args, **kwargs)
        cache[method] = result
        return result


class _MultimetricScorer:
    """Callable for multimetric scoring used to avoid repeated calls
    to `predict_proba`, `predict`, and `decision_function`.

    `_MultimetricScorer` will return a dictionary of scores corresponding to
    the scorers in the dictionary. Note that `_MultimetricScorer` can be
    created with a dictionary with one key  (i.e. only one actual scorer).

    Parameters
    ----------
    scorers : dict
        Dictionary mapping names to callable scorers.
    """
    def __init__(self, **scorers):
        self._scorers = scorers

    def __call__(self, estimator, *args, **kwargs):
        """Evaluate predicted target values."""
        scores = {}
        cache = {} if self._use_cache(estimator) else None
        cached_call = partial(_cached_call, cache)

        for name, scorer in self._scorers.items():
            if isinstance(scorer, _BaseScorer):
                score = scorer._score(cached_call, estimator,
                                      *args, **kwargs)
            else:
                score = scorer(estimator, *args, **kwargs)
            scores[name] = score
        return scores

    def _use_cache(self, estimator):
        """Return True if using a cache is beneficial.

        Caching may be beneficial when one of these conditions holds:
          - `_ProbaScorer` will be called twice.
          - `_PredictScorer` will be called twice.
          - `_ThresholdScorer` will be called twice.
          - `_ThresholdScorer` and `_PredictScorer` are called and
             estimator is a regressor.
          - `_ThresholdScorer` and `_ProbaScorer` are called and
             estimator does not have a `decision_function` attribute.

        """
        if len(self._scorers) == 1:  # Only one scorer
            return False

        counter = Counter([type(v) for v in self._scorers.values()])

        if any(counter[known_type] > 1 for known_type in
               [_PredictScorer, _ProbaScorer, _ThresholdScorer]):
            return True

        if counter[_ThresholdScorer]:
            if is_regressor(estimator) and counter[_PredictScorer]:
                return True
            elif (counter[_ProbaScorer] and
                  not hasattr(estimator, "decision_function")):
                return True
        return False


class _BaseScorer:
    def __init__(self, score_func, sign, kwargs):
        self._kwargs = kwargs
        self._score_func = score_func
        self._sign = sign
        # XXX After removing the deprecated scorers (v0.24) remove the
        # XXX deprecation_msg property again and remove __call__'s body again
        self._deprecation_msg = None

    def __repr__(self):
        kwargs_string = "".join([", %s=%s" % (str(k), str(v))
                                 for k, v in self._kwargs.items()])
        return ("make_scorer(%s%s%s%s)"
                % (self._score_func.__name__,
                   "" if self._sign > 0 else ", greater_is_better=False",
                   self._factory_args(), kwargs_string))

    def __call__(self, estimator, X, y_true, sample_weight=None,
                 **predict_params):
        """Evaluate predicted target values for X relative to y_true.

        Parameters
        ----------
        estimator : object
            Trained estimator to use for scoring. Must have a predict_proba
            method; the output of that is used to compute the score.

        X : array-like or sparse matrix
            Test data that will be fed to estimator.predict.

        y_true : array-like
            Gold standard target values for X.

        sample_weight : array-like, optional (default=None)
            Sample weights.

        Returns
        -------
        score : float
            Score function applied to prediction of estimator on X.
        """
        if self._deprecation_msg is not None:
            warnings.warn(self._deprecation_msg,
                          category=FutureWarning,
                          stacklevel=2)
        return self._score(partial(_cached_call, None), estimator, X, y_true,
                           sample_weight=sample_weight, **predict_params)

    def _factory_args(self):
        """Return non-default make_scorer arguments for repr."""
        return ""


class _PredictScorer(_BaseScorer):
    def _score(self, method_caller, estimator, X, y_true, sample_weight=None,
               **predict_params):
        """Evaluate predicted target values for X relative to y_true.

        Parameters
        ----------
        method_caller : callable
            Returns predictions given an estimator, method name, and other
            arguments, potentially caching results.

        estimator : object
            Trained estimator to use for scoring. Must have a predict_proba
            method; the output of that is used to compute the score.

        X : array-like or sparse matrix
            Test data that will be fed to estimator.predict.

        y_true : array-like
            Gold standard target values for X.

        sample_weight : array-like, optional (default=None)
            Sample weights.

        Returns
        -------
        score : float
            Score function applied to prediction of estimator on X.
        """

        y_pred = method_caller(estimator, "predict", X, **predict_params)
        if sample_weight is not None:
            return self._sign * self._score_func(y_true, y_pred,
                                                 sample_weight=sample_weight,
                                                 **self._kwargs)
        else:
            return self._sign * self._score_func(y_true, y_pred,
                                                 **self._kwargs)


class _ProbaScorer(_BaseScorer):
    def _score(self, method_caller, clf, X, y, sample_weight=None,
               **predict_params):
        """Evaluate predicted probabilities for X relative to y_true.

        Parameters
        ----------
        method_caller : callable
            Returns predictions given an estimator, method name, and other
            arguments, potentially caching results.

        clf : object
            Trained classifier to use for scoring. Must have a predict_proba
            method; the output of that is used to compute the score.

        X : array-like or sparse matrix
            Test data that will be fed to clf.predict_proba.

        y : array-like
            Gold standard target values for X. These must be class labels,
            not probabilities.

        sample_weight : array-like, optional (default=None)
            Sample weights.

        Returns
        -------
        score : float
            Score function applied to prediction of estimator on X.
        """

        y_type = type_of_target(y)
        y_pred = method_caller(clf, "predict_proba", X, **predict_params)
        if y_type == "binary":
            if y_pred.shape[1] == 2:
                y_pred = y_pred[:, 1]
            elif y_pred.shape[1] == 1:  # not multiclass
                raise ValueError('got predict_proba of shape {},'
                                 ' but need classifier with two'
                                 ' classes for {} scoring'.format(
                                     y_pred.shape, self._score_func.__name__))
        if sample_weight is not None:
            return self._sign * self._score_func(y, y_pred,
                                                 sample_weight=sample_weight,
                                                 **self._kwargs)
        else:
            return self._sign * self._score_func(y, y_pred, **self._kwargs)

    def _factory_args(self):
        return ", needs_proba=True"


class _ThresholdScorer(_BaseScorer):
    def _score(self, method_caller, clf, X, y, sample_weight=None,
               **predict_params):
        """Evaluate decision function output for X relative to y_true.

        Parameters
        ----------
        method_caller : callable
            Returns predictions given an estimator, method name, and other
            arguments, potentially caching results.

        clf : object
            Trained classifier to use for scoring. Must have either a
            decision_function method or a predict_proba method; the output of
            that is used to compute the score.

        X : array-like or sparse matrix
            Test data that will be fed to clf.decision_function or
            clf.predict_proba.

        y : array-like
            Gold standard target values for X. These must be class labels,
            not decision function values.

        sample_weight : array-like, optional (default=None)
            Sample weights.

        Returns
        -------
        score : float
            Score function applied to prediction of estimator on X.
        """

        y_type = type_of_target(y)
        if y_type not in ("binary", "multilabel-indicator"):
            raise ValueError("{0} format is not supported".format(y_type))

        if is_regressor(clf):
            y_pred = method_caller(clf, "predict", X, **predict_params)
        else:
            try:
                y_pred = method_caller(clf, "decision_function", X,
                                       **predict_params)

                # For multi-output multi-class estimator
                if isinstance(y_pred, list):
                    y_pred = np.vstack([p for p in y_pred]).T

            except (NotImplementedError, AttributeError):
                y_pred = method_caller(clf, "predict_proba", X,
                                       **predict_params)

                if y_type == "binary":
                    if y_pred.shape[1] == 2:
                        y_pred = y_pred[:, 1]
                    else:
                        raise ValueError('got predict_proba of shape {},'
                                         ' but need classifier with two'
                                         ' classes for {} scoring'.format(
                                             y_pred.shape,
                                             self._score_func.__name__))
                elif isinstance(y_pred, list):
                    y_pred = np.vstack([p[:, -1] for p in y_pred]).T

        if sample_weight is not None:
            return self._sign * self._score_func(y, y_pred,
                                                 sample_weight=sample_weight,
                                                 **self._kwargs)
        else:
            return self._sign * self._score_func(y, y_pred, **self._kwargs)

    def _factory_args(self):
        return ", needs_threshold=True"


def get_scorer(scoring):
    """Get a scorer from string.

    Read more in the :ref:`User Guide <scoring_parameter>`.

    Parameters
    ----------
    scoring : str | callable
        scoring method as string. If callable it is returned as is.

    Returns
    -------
    scorer : callable
        The scorer.
    """
    if isinstance(scoring, str):
        try:
            if scoring == 'brier_score_loss':
                # deprecated
                scorer = brier_score_loss_scorer
            else:
                scorer = SCORERS[scoring]
        except KeyError:
            raise ValueError('%r is not a valid scoring value. '
                             'Use sorted(sklearn.metrics.SCORERS.keys()) '
                             'to get valid options.' % scoring)
    else:
        scorer = scoring
    return scorer


def _passthrough_scorer(estimator, *args, **kwargs):
    """Function that wraps estimator.score"""
    return estimator.score(*args, **kwargs)


def check_scoring(estimator, scoring=None, allow_none=False):
    """Determine scorer from user options.

    A TypeError will be thrown if the estimator cannot be scored.

    Parameters
    ----------
    estimator : estimator object implementing 'fit'
        The object to use to fit the data.

    scoring : string, callable or None, optional, default: None
        A string (see model evaluation documentation) or
        a scorer callable object / function with signature
        ``scorer(estimator, X, y)``.

    allow_none : boolean, optional, default: False
        If no scoring is specified and the estimator has no score function, we
        can either return None or raise an exception.

    Returns
    -------
    scoring : callable
        A scorer callable object / function with signature
        ``scorer(estimator, X, y)``.
    """
    if not hasattr(estimator, 'fit'):
        raise TypeError("estimator should be an estimator implementing "
                        "'fit' method, %r was passed" % estimator)
    if isinstance(scoring, str):
        return get_scorer(scoring)
    elif callable(scoring):
        # Heuristic to ensure user has not passed a metric
        module = getattr(scoring, '__module__', None)
        if hasattr(module, 'startswith') and \
           module.startswith('sklearn.metrics.') and \
           not module.startswith('sklearn.metrics._scorer') and \
           not module.startswith('sklearn.metrics.tests.'):
            raise ValueError('scoring value %r looks like it is a metric '
                             'function rather than a scorer. A scorer should '
                             'require an estimator as its first parameter. '
                             'Please use `make_scorer` to convert a metric '
                             'to a scorer.' % scoring)
        return get_scorer(scoring)
    elif scoring is None:
        if hasattr(estimator, 'score'):
            return _passthrough_scorer
        elif allow_none:
            return None
        else:
            raise TypeError(
                "If no scoring is specified, the estimator passed should "
                "have a 'score' method. The estimator %r does not."
                % estimator)
    elif isinstance(scoring, Iterable):
        raise ValueError("For evaluating multiple scores, use "
                         "sklearn.model_selection.cross_validate instead. "
                         "{0} was passed.".format(scoring))
    else:
        raise ValueError("scoring value should either be a callable, string or"
                         " None. %r was passed" % scoring)


def _check_multimetric_scoring(estimator, scoring=None):
    """Check the scoring parameter in cases when multiple metrics are allowed

    Parameters
    ----------
    estimator : sklearn estimator instance
        The estimator for which the scoring will be applied.

    scoring : string, callable, list/tuple, dict or None, default: None
        A single string (see :ref:`scoring_parameter`) or a callable
        (see :ref:`scoring`) to evaluate the predictions on the test set.

        For evaluating multiple metrics, either give a list of (unique) strings
        or a dict with names as keys and callables as values.

        NOTE that when using custom scorers, each scorer should return a single
        value. Metric functions returning a list/array of values can be wrapped
        into multiple scorers that return one value each.

        See :ref:`multimetric_grid_search` for an example.

        If None the estimator's score method is used.
        The return value in that case will be ``{'score': <default_scorer>}``.
        If the estimator's score method is not available, a ``TypeError``
        is raised.

    Returns
    -------
    scorers_dict : dict
        A dict mapping each scorer name to its validated scorer.

    is_multimetric : bool
        True if scorer is a list/tuple or dict of callables
        False if scorer is None/str/callable
    """
    if callable(scoring) or scoring is None or isinstance(scoring,
                                                          str):
        scorers = {"score": check_scoring(estimator, scoring=scoring)}
        return scorers, False
    else:
        err_msg_generic = ("scoring should either be a single string or "
                           "callable for single metric evaluation or a "
                           "list/tuple of strings or a dict of scorer name "
                           "mapped to the callable for multiple metric "
                           "evaluation. Got %s of type %s"
                           % (repr(scoring), type(scoring)))

        if isinstance(scoring, (list, tuple, set)):
            err_msg = ("The list/tuple elements must be unique "
                       "strings of predefined scorers. ")
            invalid = False
            try:
                keys = set(scoring)
            except TypeError:
                invalid = True
            if invalid:
                raise ValueError(err_msg)

            if len(keys) != len(scoring):
                raise ValueError(err_msg + "Duplicate elements were found in"
                                 " the given list. %r" % repr(scoring))
            elif len(keys) > 0:
                if not all(isinstance(k, str) for k in keys):
                    if any(callable(k) for k in keys):
                        raise ValueError(err_msg +
                                         "One or more of the elements were "
                                         "callables. Use a dict of score name "
                                         "mapped to the scorer callable. "
                                         "Got %r" % repr(scoring))
                    else:
                        raise ValueError(err_msg +
                                         "Non-string types were found in "
                                         "the given list. Got %r"
                                         % repr(scoring))
                scorers = {scorer: check_scoring(estimator, scoring=scorer)
                           for scorer in scoring}
            else:
                raise ValueError(err_msg +
                                 "Empty list was given. %r" % repr(scoring))

        elif isinstance(scoring, dict):
            keys = set(scoring)
            if not all(isinstance(k, str) for k in keys):
                raise ValueError("Non-string types were found in the keys of "
                                 "the given dict. scoring=%r" % repr(scoring))
            if len(keys) == 0:
                raise ValueError("An empty dict was passed. %r"
                                 % repr(scoring))
            scorers = {key: check_scoring(estimator, scoring=scorer)
                       for key, scorer in scoring.items()}
        else:
            raise ValueError(err_msg_generic)
        return scorers, True


def make_scorer(score_func, greater_is_better=True, needs_proba=False,
                needs_threshold=False, **kwargs):
    """Make a scorer from a performance metric or loss function.

    This factory function wraps scoring functions for use in GridSearchCV
    and cross_val_score. It takes a score function, such as ``accuracy_score``,
    ``mean_squared_error``, ``adjusted_rand_index`` or ``average_precision``
    and returns a callable that scores an estimator's output.

    Read more in the :ref:`User Guide <scoring>`.

    Parameters
    ----------
    score_func : callable,
        Score function (or loss function) with signature
        ``score_func(y, y_pred, **kwargs)``.

    greater_is_better : boolean, default=True
        Whether score_func is a score function (default), meaning high is good,
        or a loss function, meaning low is good. In the latter case, the
        scorer object will sign-flip the outcome of the score_func.

    needs_proba : boolean, default=False
        Whether score_func requires predict_proba to get probability estimates
        out of a classifier.

        If True, for binary `y_true`, the score function is supposed to accept
        a 1D `y_pred` (i.e., probability of the positive class, shape
        `(n_samples,)`).

    needs_threshold : boolean, default=False
        Whether score_func takes a continuous decision certainty.
        This only works for binary classification using estimators that
        have either a decision_function or predict_proba method.

        If True, for binary `y_true`, the score function is supposed to accept
        a 1D `y_pred` (i.e., probability of the positive class or the decision
        function, shape `(n_samples,)`).

        For example ``average_precision`` or the area under the roc curve
        can not be computed using discrete predictions alone.

    **kwargs : additional arguments
        Additional parameters to be passed to score_func.

    Returns
    -------
    scorer : callable
        Callable object that returns a scalar score; greater is better.

    Examples
    --------
    >>> from sklearn.metrics import fbeta_score, make_scorer
    >>> ftwo_scorer = make_scorer(fbeta_score, beta=2)
    >>> ftwo_scorer
    make_scorer(fbeta_score, beta=2)
    >>> from sklearn.model_selection import GridSearchCV
    >>> from sklearn.svm import LinearSVC
    >>> grid = GridSearchCV(LinearSVC(), param_grid={'C': [1, 10]},
    ...                     scoring=ftwo_scorer)

    Notes
    -----
    If `needs_proba=False` and `needs_threshold=False`, the score
    function is supposed to accept the output of :term:`predict`. If
    `needs_proba=True`, the score function is supposed to accept the
    output of :term:`predict_proba` (For binary `y_true`, the score function is
    supposed to accept probability of the positive class). If
    `needs_threshold=True`, the score function is supposed to accept the
    output of :term:`decision_function`.
    """
    sign = 1 if greater_is_better else -1
    if needs_proba and needs_threshold:
        raise ValueError("Set either needs_proba or needs_threshold to True,"
                         " but not both.")
    if needs_proba:
        cls = _ProbaScorer
    elif needs_threshold:
        cls = _ThresholdScorer
    else:
        cls = _PredictScorer
    return cls(score_func, sign, kwargs)


# Standard regression scores
explained_variance_scorer = make_scorer(explained_variance_score)
r2_scorer = make_scorer(r2_score)
max_error_scorer = make_scorer(max_error,
                               greater_is_better=False)
neg_mean_squared_error_scorer = make_scorer(mean_squared_error,
                                            greater_is_better=False)
neg_mean_squared_log_error_scorer = make_scorer(mean_squared_log_error,
                                                greater_is_better=False)
neg_mean_absolute_error_scorer = make_scorer(mean_absolute_error,
                                             greater_is_better=False)
neg_median_absolute_error_scorer = make_scorer(median_absolute_error,
                                               greater_is_better=False)
neg_root_mean_squared_error_scorer = make_scorer(mean_squared_error,
                                                 greater_is_better=False,
                                                 squared=False)
neg_mean_poisson_deviance_scorer = make_scorer(
    mean_poisson_deviance, greater_is_better=False
)

neg_mean_gamma_deviance_scorer = make_scorer(
    mean_gamma_deviance, greater_is_better=False
)

# Standard Classification Scores
accuracy_scorer = make_scorer(accuracy_score)
balanced_accuracy_scorer = make_scorer(balanced_accuracy_score)

# Score functions that need decision values
roc_auc_scorer = make_scorer(roc_auc_score, greater_is_better=True,
                             needs_threshold=True)
average_precision_scorer = make_scorer(average_precision_score,
                                       needs_threshold=True)
roc_auc_ovo_scorer = make_scorer(roc_auc_score, needs_proba=True,
                                 multi_class='ovo')
roc_auc_ovo_weighted_scorer = make_scorer(roc_auc_score, needs_proba=True,
                                          multi_class='ovo',
                                          average='weighted')
roc_auc_ovr_scorer = make_scorer(roc_auc_score, needs_proba=True,
                                 multi_class='ovr')
roc_auc_ovr_weighted_scorer = make_scorer(roc_auc_score, needs_proba=True,
                                          multi_class='ovr',
                                          average='weighted')

# Score function for probabilistic classification
neg_log_loss_scorer = make_scorer(log_loss, greater_is_better=False,
                                  needs_proba=True)
neg_brier_score_scorer = make_scorer(brier_score_loss,
                                     greater_is_better=False,
                                     needs_proba=True)
brier_score_loss_scorer = make_scorer(brier_score_loss,
                                      greater_is_better=False,
                                      needs_proba=True)
deprecation_msg = ('Scoring method brier_score_loss was renamed to '
                   'neg_brier_score in version 0.22 and will '
                   'be removed in 0.24.')
brier_score_loss_scorer._deprecation_msg = deprecation_msg


# Clustering scores
adjusted_rand_scorer = make_scorer(adjusted_rand_score)
homogeneity_scorer = make_scorer(homogeneity_score)
completeness_scorer = make_scorer(completeness_score)
v_measure_scorer = make_scorer(v_measure_score)
mutual_info_scorer = make_scorer(mutual_info_score)
adjusted_mutual_info_scorer = make_scorer(adjusted_mutual_info_score)
normalized_mutual_info_scorer = make_scorer(normalized_mutual_info_score)
fowlkes_mallows_scorer = make_scorer(fowlkes_mallows_score)


SCORERS = dict(explained_variance=explained_variance_scorer,
               r2=r2_scorer,
               max_error=max_error_scorer,
               neg_median_absolute_error=neg_median_absolute_error_scorer,
               neg_mean_absolute_error=neg_mean_absolute_error_scorer,
               neg_mean_squared_error=neg_mean_squared_error_scorer,
               neg_mean_squared_log_error=neg_mean_squared_log_error_scorer,
               neg_root_mean_squared_error=neg_root_mean_squared_error_scorer,
               neg_mean_poisson_deviance=neg_mean_poisson_deviance_scorer,
               neg_mean_gamma_deviance=neg_mean_gamma_deviance_scorer,
               accuracy=accuracy_scorer, roc_auc=roc_auc_scorer,
               roc_auc_ovr=roc_auc_ovr_scorer,
               roc_auc_ovo=roc_auc_ovo_scorer,
               roc_auc_ovr_weighted=roc_auc_ovr_weighted_scorer,
               roc_auc_ovo_weighted=roc_auc_ovo_weighted_scorer,
               balanced_accuracy=balanced_accuracy_scorer,
               average_precision=average_precision_scorer,
               neg_log_loss=neg_log_loss_scorer,
               neg_brier_score=neg_brier_score_scorer,
               # Cluster metrics that use supervised evaluation
               adjusted_rand_score=adjusted_rand_scorer,
               homogeneity_score=homogeneity_scorer,
               completeness_score=completeness_scorer,
               v_measure_score=v_measure_scorer,
               mutual_info_score=mutual_info_scorer,
               adjusted_mutual_info_score=adjusted_mutual_info_scorer,
               normalized_mutual_info_score=normalized_mutual_info_scorer,
               fowlkes_mallows_score=fowlkes_mallows_scorer)


for name, metric in [('precision', precision_score),
                     ('recall', recall_score), ('f1', f1_score),
                     ('jaccard', jaccard_score)]:
    SCORERS[name] = make_scorer(metric, average='binary')
    for average in ['macro', 'micro', 'samples', 'weighted']:
        qualified_name = '{0}_{1}'.format(name, average)
        SCORERS[qualified_name] = make_scorer(metric, pos_label=None,
                                              average=average)

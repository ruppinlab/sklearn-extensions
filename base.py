"""Base classes for all estimators."""

# Authors: Gael Varoquaux <gael.varoquaux@normalesup.org>
#          Leandro Hermida <hermidal@cs.umd.edu>
# License: BSD 3 clause

from sklearn.base import TransformerMixin


class ExtendedTransformerMixin(TransformerMixin):
    """Mixin class for all transformers in scikit-learn."""

    def fit_transform(self, X, y=None, **fit_params):
        """Fit to data, then transform it.

        Fits transformer to X and y with optional parameters fit_params
        and returns a transformed version of X.

        Parameters
        ----------
        X : numpy array of shape [n_samples, n_features]
            Training set.

        y : numpy array of shape [n_samples]
            Target values.

        **fit_params : dict
            Additional fit parameters.

        Returns
        -------
        X_new : numpy array of shape [n_samples, n_features_new]
            Transformed array.
        """
        # non-optimized default implementation; override when a better
        # method is possible for a given clustering algorithm
        if y is None:
            # fit method of arity 1 (unsupervised transformation)
            return self.fit(X, **fit_params).transform(X, **fit_params)
        else:
            # fit method of arity 2 (supervised transformation)
            return self.fit(X, y, **fit_params).transform(X, **fit_params)

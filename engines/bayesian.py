import numpy as np
from scipy.stats import norm

class BayesianLayer:
    def __init__(self, hist_std=1.0, sample_size=60):
        self.hist_std = hist_std
        self.sample_size = sample_size

    def distribution(self, pred):
        posterior_std = self.hist_std / max(np.sqrt(self.sample_size), 1)
        return norm(loc=pred, scale=posterior_std)

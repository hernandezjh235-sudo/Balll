import numpy as np

class MonteCarloEngine:
    def __init__(self, simulator, sims=15000):
        self.simulator = simulator
        self.sims = int(sims)

    def simulate(self, distribution):
        results = []
        for _ in range(self.sims):
            sampled_rate = np.clip(
                distribution.rvs() / max(self.simulator.steps, 1),
                0.001,
                0.8
            )
            results.append(self.simulator.run(sampled_rate))
        return np.array(results)

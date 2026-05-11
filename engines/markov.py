import numpy as np

class MarkovSimulator:
    def __init__(self, steps=27):
        self.steps = int(steps)

    def run(self, rate):
        total = 0
        rate = float(np.clip(rate, 0.001, 0.8))
        for _ in range(self.steps):
            if np.random.rand() < rate:
                total += 1
        return total

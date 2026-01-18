class AnimationTimer:
    def __init__(self, duration):
        self.duration = duration
        self.elapsed = duration
        self.direction = 1  # 1 for forward, -1 for backward

    def reset(self):
        self.elapsed = 0

    def tick(self, dt):
        # advance elapsed time but never exceed duration
        self.elapsed += dt * self.direction
        if self.elapsed > self.duration:
            self.elapsed = self.duration
        if self.elapsed < 0:
            self.elapsed = 0

    @property
    def value(self):
        # guard against zero or negative duration
        if self.duration <= 0:
            return 1.0
        # clamp result to [0.0, 1.0]
        v = self.elapsed / self.duration
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v

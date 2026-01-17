"""
Lightweight simulation engine for a differential-drive-ish robot car.
Pygame rendering lives elsewhere; this module only tracks physics/state.
"""

from __future__ import annotations

import dataclasses
import math
import random
from dataclasses import dataclass


@dataclass
class CarState:
    x: float
    y: float
    heading: float  # radians, 0 = +X
    speed: float


class RobotCar:
    def __init__(
        self,
        x: float,
        y: float,
        heading: float = 0.0,
        max_speed: float = 280.0,
        accel: float = 340.0,
        turn_rate: float = 4.6,
        friction: float = 0.88,
    ):
        self.state = CarState(x=x, y=y, heading=heading, speed=0.0)
        self.max_speed = max_speed
        self.accel = accel
        self.turn_rate = turn_rate
        self.friction = friction

    def reset(self, x: float, y: float, heading: float = 0.0):
        self.state = CarState(x=x, y=y, heading=heading, speed=0.0)

    def update(self, throttle: float, steer: float, brake: bool, dt: float):
        # throttle, steer in [-1, 1]
        st = self.state
        target_accel = throttle * self.accel
        st.speed += target_accel * dt
        if brake:
            st.speed *= 0.75

        st.speed *= self.friction  # drag
        st.speed = max(-self.max_speed, min(self.max_speed, st.speed))

        # steer harder at lower speed to keep it responsive; damp at very low speed
        steer_factor = max(0.35, min(1.0, abs(st.speed) / (self.max_speed * 0.35)))
        st.heading += steer * self.turn_rate * steer_factor * dt

        st.x += math.cos(st.heading) * st.speed * dt
        st.y += math.sin(st.heading) * st.speed * dt

    def as_polygon(self):
        # return triangle points for rendering
        st = self.state
        length = 48
        width = 26
        heading = st.heading
        nose = (st.x + math.cos(heading) * length / 2, st.y + math.sin(heading) * length / 2)
        rear_center = (
            st.x - math.cos(heading) * length / 2,
            st.y - math.sin(heading) * length / 2,
        )
        left = (
            rear_center[0] + math.cos(heading + math.pi / 2) * width / 2,
            rear_center[1] + math.sin(heading + math.pi / 2) * width / 2,
        )
        right = (
            rear_center[0] + math.cos(heading - math.pi / 2) * width / 2,
            rear_center[1] + math.sin(heading - math.pi / 2) * width / 2,
        )
        return [nose, left, right]

    def snapshot(self) -> CarState:
        return CarState(**vars(self.state))


@dataclass
class Enemy:
    x: float
    y: float
    heading: float
    speed: float
    hp: int


@dataclass
class Projectile:
    x: float
    y: float
    heading: float
    speed: float
    ttl: float


class GameWorld:
    def __init__(self, width: float, height: float):
        self.width = width
        self.height = height
        self.car = RobotCar(width / 2, height / 2)
        self.enemies: list[Enemy] = []
        self.projectiles: list[Projectile] = []
        self.spawn_cooldown = 0.0
        self.fire_cooldown = 0.0
        self.kills = 0
        self.player_health = 5
        self.level = 1
        self.time_elapsed = 0.0
        self.base_max_enemies = 6
        self.cap_max_enemies = 18
        self.enemy_radius = 18
        self.car_radius = 16
        self.bullet_radius = 6
        self.base_enemy_hp = 1
        self.base_enemy_speed = (55.0, 95.0)

    def wrap(self, x: float, y: float) -> tuple[float, float]:
        x = x % self.width
        y = y % self.height
        return x, y

    def attempt_fire(self):
        if self.fire_cooldown > 0:
            return False
        st = self.car.state
        spawn_x = st.x + math.cos(st.heading) * 26
        spawn_y = st.y + math.sin(st.heading) * 26
        self.projectiles.append(
            Projectile(
                x=spawn_x, y=spawn_y, heading=st.heading, speed=480.0, ttl=1.3
            )
        )
        self.fire_cooldown = 0.18
        return True

    def spawn_enemy(self):
        side = random.choice(["top", "bottom", "left", "right"])
        if side == "top":
            x, y = random.uniform(0, self.width), -20
        elif side == "bottom":
            x, y = random.uniform(0, self.width), self.height + 20
        elif side == "left":
            x, y = -20, random.uniform(0, self.height)
        else:
            x, y = self.width + 20, random.uniform(0, self.height)

        speed_scale = min(1.8, 1.0 + 0.05 * self.level)
        hp = self.base_enemy_hp + self.level // 3
        speed_lo, speed_hi = self.base_enemy_speed
        enemy = Enemy(
            x=x,
            y=y,
            heading=0.0,
            speed=random.uniform(speed_lo, speed_hi) * speed_scale,
            hp=hp,
        )
        self.enemies.append(enemy)

    def update(self, throttle: float, steer: float, brake: bool, dt: float):
        # player
        self.car.update(throttle=throttle, steer=steer, brake=brake, dt=dt)
        self.car.state.x, self.car.state.y = self.wrap(
            self.car.state.x, self.car.state.y
        )

        # timers & difficulty
        self.time_elapsed += dt
        self.level = 1 + self.kills // 5 + int(self.time_elapsed // 45)
        max_enemies = min(
            self.cap_max_enemies, self.base_max_enemies + self.level * 2
        )
        self.spawn_cooldown -= dt
        self.fire_cooldown = max(0.0, self.fire_cooldown - dt)
        if self.spawn_cooldown <= 0 and len(self.enemies) < max_enemies:
            self.spawn_enemy()
            base_min = 1.8
            base_max = 2.8
            interval = max(0.55, base_min - 0.12 * (self.level - 1))
            interval_max = max(0.9, base_max - 0.14 * (self.level - 1))
            self.spawn_cooldown = random.uniform(interval, interval_max)

        # move enemies toward player
        for e in self.enemies:
            target_angle = math.atan2(
                self.car.state.y - e.y, self.car.state.x - e.x
            )
            # smooth turn
            diff = (target_angle - e.heading + math.pi) % (2 * math.pi) - math.pi
            e.heading += diff * 0.12
            e.x += math.cos(e.heading) * e.speed * dt
            e.y += math.sin(e.heading) * e.speed * dt
            e.x, e.y = self.wrap(e.x, e.y)

        # move projectiles
        for p in list(self.projectiles):
            p.ttl -= dt
            if p.ttl <= 0:
                self.projectiles.remove(p)
                continue
            p.x += math.cos(p.heading) * p.speed * dt
            p.y += math.sin(p.heading) * p.speed * dt
            p.x, p.y = self.wrap(p.x, p.y)

        # collisions: bullets vs enemies
        for p in list(self.projectiles):
            hit = False
            for e in list(self.enemies):
                dx = p.x - e.x
                dy = p.y - e.y
                if dx * dx + dy * dy <= (self.enemy_radius + self.bullet_radius) ** 2:
                    e.hp -= 1
                    hit = True
                    if e.hp <= 0:
                        self.enemies.remove(e)
                        self.kills += 1
                    break
            if hit:
                self.projectiles.remove(p)

        # collisions: enemies vs player
        for e in list(self.enemies):
            dx = e.x - self.car.state.x
            dy = e.y - self.car.state.y
            if dx * dx + dy * dy <= (self.enemy_radius + self.car_radius) ** 2:
                self.player_health = max(0, self.player_health - 1)
                self.enemies.remove(e)

    def snapshot(self):
        return {
            "car": self.car.snapshot(),
            "enemies": [dataclasses.asdict(e) for e in self.enemies],
            "projectiles": [dataclasses.asdict(p) for p in self.projectiles],
            "kills": self.kills,
            "player_health": self.player_health,
            "level": self.level,
        }

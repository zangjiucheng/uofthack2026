import math

import pygame
import apps.services.pi.eye_animations_lib.lcd_frame as lcd_frame
import random
from apps.services.pi.eye_animations_lib.timer import AnimationTimer


def ease_in_out_power(t, p=3):
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 0.5 * (2 * t) ** p
    else:
        return 1 - 0.5 * (2 * (1 - t)) ** p


class EyeTransform:
    def __init__(self):
        self.blink_timer = AnimationTimer(0.5)
        self.shake_timer = AnimationTimer(0.4)
        self.curious_timer = AnimationTimer(0.4)
        self.refuse_shake_timer = AnimationTimer(0.6)

        self.shake_amplitude_x = 1  # pixels
        self.shake_frequency_x = 6  # oscillations per second
        self.shake_amplitude_y = 1  # pixels
        self.shake_frequency_y = 13  # oscillations per second

        self.shake_seed_left = random.random() * 2 * math.pi
        self.shake_seed_right = random.random() * 2 * math.pi

        self.time = 0
        self.target_offset_x = 0
        self.target_offset_y = 0

        self.__current_offset_x = 0
        self.__current_offset_y = 0

        self.eye_side_x = 1
        self.curious = False

        self.target_left_corner_height = 0
        self.target_right_corner_height = 0
        self.target_happy_transition = 0.0

        self.__left_corner_height = 0
        self.__right_corner_height = 0
        self.__happy_transition = 0.0

    def tick(self, dt: float):
        self.blink_timer.tick(dt)
        self.shake_timer.tick(dt)
        self.refuse_shake_timer.tick(dt)
        self.curious_timer.tick(dt)
        self.curious_timer.direction = 1 if self.curious else -1
        self.time += dt

        self.__current_offset_x += (self.target_offset_x - self.__current_offset_x) * 6 * dt
        self.__current_offset_y += (self.target_offset_y - self.__current_offset_y) * 8 * dt

        self.__left_corner_height += (self.target_left_corner_height - self.__left_corner_height) * 6 * dt
        self.__right_corner_height += (self.target_right_corner_height - self.__right_corner_height) * 6 * dt
        self.__happy_transition += (self.target_happy_transition - self.__happy_transition) * 4 * dt

    @property
    def happy_transition(self):
        return self.__happy_transition

    @property
    def left_corner_height(self):
        return self.__left_corner_height

    @property
    def right_corner_height(self):
        return self.__right_corner_height

    @property
    def scale_y(self):
        blink_compress = ease_in_out_power(abs(self.blink_timer.value - 0.5) / 0.5, 4) * 0.95 + 0.05

        curious_scale = 1.0 + 0.01 * self.__current_offset_x * self.eye_side_x * self.curious_timer.value

        return blink_compress * curious_scale

    @property
    def scale_x(self):
        blink_scale = 1 + 0.2 * (1 - 4 * (max(self.blink_timer.value - 0.2, 0) / 0.8 - 0.5) ** 2)

        curious_scale = 1.0 + 0.01 * self.__current_offset_x * self.eye_side_x * self.curious_timer.value

        return blink_scale * curious_scale

    @property
    def offset_x(self):
        shake_offset = (self.shake_timer.value - 1) ** 4 * math.sin(
            self.shake_frequency_x * 2 * math.pi * (self.time + self.shake_seed_left)) * self.shake_amplitude_x
        refuse_shake_offset = (1 - ease_in_out_power(abs(self.refuse_shake_timer.value - 0.5) / 0.5,
                                                     2)) * 32 * math.sin(
            10 * 2 * math.pi * self.time)

        return shake_offset + self.__current_offset_x + refuse_shake_offset

    @property
    def offset_y(self):
        shake_offset = (self.shake_timer.value - 1) ** 4 * math.sin(
            self.shake_frequency_y * 2 * math.pi * (self.time + self.shake_seed_right)) * self.shake_amplitude_y
        return shake_offset + self.__current_offset_y


class Eye:
    def __init__(self):
        # create a surface with per-pixel alpha so rounded shapes and transparency work
        self.eye_surf = pygame.Surface((36, 36), pygame.SRCALPHA)
        # default rounded rectangle + pupil
        self.apply_rounded_rectangle(10)
        self.transform = EyeTransform()

    def apply_rounded_rectangle(self, radius: int):
        # clear to fully transparent
        self.eye_surf.fill((0, 0, 0, 0))
        # draw a white rounded rectangle (the sclera) so it shows up on a black LCD background
        pygame.draw.rect(self.eye_surf, (255, 255, 255, 255), self.eye_surf.get_rect(), border_radius=radius)

    def apply_circle(self, radius):
        # clear to fully transparent
        self.eye_surf.fill((0, 0, 0, 0))
        # draw a white circle (the sclera) so it shows up on a black LCD background
        pygame.draw.circle(self.eye_surf, (255, 255, 255, 255), (radius, radius), radius)

    def draw(self, lcd: lcd_frame.LCDDisplay, position: tuple[int, int]):
        lcd.surf.fill((0, 0, 0, 255))

        scaled_surf = pygame.transform.scale(
            self.eye_surf,
            (
                round(self.transform.scale_x * self.eye_surf.get_width()),
                round(self.transform.scale_y * self.eye_surf.get_height())
            )
        )

        pygame.draw.polygon(
            scaled_surf,
            (0, 0, 0, 255),
            [
                # top-left
                (0, 0),
                # top-right
                (scaled_surf.get_width() - 1, 0),
                # bottom-right (uses right corner height)
                (scaled_surf.get_width() - 1, round(self.transform.right_corner_height * scaled_surf.get_height())),
                # bottom-left (uses left corner height)
                (0, round(self.transform.left_corner_height * scaled_surf.get_height())),
            ],

        )

        lcd.surf.blit(scaled_surf, (
            round(position[0] - scaled_surf.get_width() / 2 + self.transform.offset_x),
            round(position[1] - scaled_surf.get_height() / 2 + self.transform.offset_y)
        ))

        # Draw scaled surf from bottom to top for happy expression (controlled by happy_transition)
        happy_height = round(self.transform.happy_transition * scaled_surf.get_height() * 0.2)
        if happy_height > 0:
            # should inverse color and use multiply blend mode
            inverted_surf = pygame.Surface((scaled_surf.get_width(), happy_height), pygame.SRCALPHA)
            for x in range(scaled_surf.get_width()):
                for y in range(happy_height):
                    r, g, b, a = scaled_surf.get_at((x, scaled_surf.get_height() - happy_height + y))
                    inverted_surf.set_at((x, y), (255 - r, 255 - g, 255 - b, a))
            lcd.surf.blit(inverted_surf, (
                round(position[0] - scaled_surf.get_width() / 2 + self.transform.offset_x),
                round(position[
                          1] - scaled_surf.get_height() / 2 + self.transform.offset_y + scaled_surf.get_height() - happy_height)
            ))

    def tick(self, dt: float):
        # advance the transform (blink) timer so blinks animate over time
        self.transform.tick(dt)

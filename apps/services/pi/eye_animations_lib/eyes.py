import pygame

from apps.services.pi.eye_animations_lib.eye import Eye
import  apps.services.pi.eye_animations_lib.lcd_frame as lcd_frame
import random


class Eyes:
    MOOD_DEFAULT = 0
    MOOD_HAPPY = 1
    MOOD_SAD = 2
    MOOD_ANGRY = 3

    def __init__(self, left_display: lcd_frame.LCDDisplay, right_display: lcd_frame.LCDDisplay):
        self.left_eye = Eye()
        self.right_eye = Eye()

        self.left_eye.transform.eye_side_x = -1
        self.right_eye.transform.eye_side_x = 1

        self.left_display = left_display
        self.right_display = right_display

        self.look_at_x = 0.0
        self.look_at_y = 0.0

        self.auto_blink = True

        self.curious = False
        self.mood = Eyes.MOOD_DEFAULT

        self.next_blink_time = random.random() * 5 + 1.5

    def apply_rounded_rectangle(self, width: float, height: float, radius: int):
        self.left_eye.eye_surf = pygame.Surface((width, height), pygame.SRCALPHA)
        self.right_eye.eye_surf = pygame.Surface((width, height), pygame.SRCALPHA)
        self.left_eye.apply_rounded_rectangle(radius)
        self.right_eye.apply_rounded_rectangle(radius)

    def apply_circle(self, radius: int):
        diameter = radius * 2
        self.left_eye.eye_surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        self.right_eye.eye_surf = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        self.left_eye.apply_circle(radius)
        self.right_eye.apply_circle(radius)

    def shake_refuse(self):
        self.left_eye.transform.refuse_shake_timer.reset()
        self.right_eye.transform.refuse_shake_timer.reset()

    def render(self):
        center_x = 128 // 2
        center_y = 64 // 2
        self.left_eye.draw(self.left_display, (center_x, center_y))
        self.right_eye.draw(self.right_display, (center_x, center_y))

    def blink(self):
        self.left_eye.transform.blink_timer.reset()
        self.right_eye.transform.blink_timer.reset()

    def tick(self, dt: float):
        self.left_eye.transform.curious = self.curious
        self.right_eye.transform.curious = self.curious

        self.look_at_x = max(-1.0, min(1.0, self.look_at_x))
        self.look_at_y = max(-1.0, min(1.0, self.look_at_y))

        self.left_eye.transform.target_offset_x = self.look_at_x * 14
        self.left_eye.transform.target_offset_y = self.look_at_y * 10

        self.right_eye.transform.target_offset_x = self.look_at_x * 14
        self.right_eye.transform.target_offset_y = self.look_at_y * 10

        self.left_eye.tick(dt)
        self.right_eye.tick(dt)

        if self.mood == Eyes.MOOD_HAPPY:
            self.left_eye.transform.target_left_corner_height = 0
            self.left_eye.transform.target_right_corner_height = 0
            self.right_eye.transform.target_left_corner_height = 0
            self.right_eye.transform.target_right_corner_height = 0
            self.left_eye.transform.target_happy_transition = 1.0
            self.right_eye.transform.target_happy_transition = 1.0
        else:
            self.left_eye.transform.target_happy_transition = 0.0
            self.right_eye.transform.target_happy_transition = 0.0
            if self.mood == Eyes.MOOD_SAD:
                self.left_eye.transform.target_left_corner_height = 0.35
                self.left_eye.transform.target_right_corner_height = 0
                self.right_eye.transform.target_left_corner_height = 0
                self.right_eye.transform.target_right_corner_height = 0.35
            elif self.mood == Eyes.MOOD_ANGRY:
                self.left_eye.transform.target_left_corner_height = 0
                self.left_eye.transform.target_right_corner_height = 0.5
                self.right_eye.transform.target_left_corner_height = 0.5
                self.right_eye.transform.target_right_corner_height = 0
            else:
                self.left_eye.transform.target_left_corner_height = 0
                self.left_eye.transform.target_right_corner_height = 0
                self.right_eye.transform.target_left_corner_height = 0
                self.right_eye.transform.target_right_corner_height = 0

        if self.auto_blink:
            self.next_blink_time -= dt
            if self.next_blink_time <= 0:
                self.blink()
                self.next_blink_time = random.random() * 5 + 2

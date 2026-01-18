import pygame


class LCDDisplay:
    def __init__(self):
        self.surf = pygame.Surface((128, 64))
        self.surf.fill((0, 0, 0))

    @property
    def framed_surface(self):
        pixel_side_length = 3
        frame_thickness = 6
        framed_width = self.surf.get_width() * pixel_side_length + frame_thickness * 2
        framed_height = self.surf.get_height() * pixel_side_length + frame_thickness * 2
        frame_surface = pygame.Surface((framed_width, framed_height))
        frame_surface.fill((50, 50, 50))  # Frame color
        for y in range(self.surf.get_height()):
            for x in range(self.surf.get_width()):
                color = self.surf.get_at((x, y))
                if color[0] > 32 or color[1] > 32 or color[2] > 32:
                    color = (255, 255, 255)
                else:
                    color = (0, 0, 0)
                rect = pygame.Rect(
                    frame_thickness + x * pixel_side_length,
                    frame_thickness + y * pixel_side_length,
                    pixel_side_length,
                    pixel_side_length,
                )
                pygame.draw.rect(frame_surface, color, rect)
        return frame_surface

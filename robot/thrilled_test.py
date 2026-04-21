from pathlib import Path

import pygame


WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 700
BACKGROUND_COLOR = (227, 227, 227)


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Thrilled Face Test")
    clock = pygame.time.Clock()

    image_path = Path(__file__).resolve().parent / "faces" / "thrilled.png"
    image = pygame.image.load(str(image_path)).convert_alpha()

    w, h = image.get_size()
    scale = min((WINDOW_WIDTH - 80) / w, (WINDOW_HEIGHT - 80) / h)
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    image = pygame.transform.smoothscale(image, size)
    rect = image.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        screen.fill(BACKGROUND_COLOR)
        screen.blit(image, rect)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()

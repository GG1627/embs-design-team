from pathlib import Path

import pygame


WINDOW_WIDTH = 1000
WINDOW_HEIGHT = 700
BACKGROUND_COLOR = (173, 216, 230)  # light blue
CYCLE_SECONDS = 2.5
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def load_faces(faces_dir: Path) -> list[pygame.Surface]:
    image_paths = sorted(
        path for path in faces_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not image_paths:
        raise RuntimeError(f"No images found in: {faces_dir}")

    surfaces: list[pygame.Surface] = []
    for path in image_paths:
        image = pygame.image.load(str(path)).convert_alpha()
        surfaces.append(image)
    return surfaces


def scale_to_fit(image: pygame.Surface, max_width: int, max_height: int) -> pygame.Surface:
    width, height = image.get_size()
    scale = min(max_width / width, max_height / height)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return pygame.transform.smoothscale(image, new_size)


def main() -> None:
    pygame.init()

    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Faces Slideshow")
    clock = pygame.time.Clock()

    faces_dir = Path(__file__).resolve().parent / "faces"
    original_images = load_faces(faces_dir)
    images = [scale_to_fit(img, WINDOW_WIDTH - 250, WINDOW_HEIGHT - 250) for img in original_images]

    index = 0
    last_switch = pygame.time.get_ticks()
    cycle_ms = int(CYCLE_SECONDS * 1000)
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        now = pygame.time.get_ticks()
        if now - last_switch >= cycle_ms:
            index = (index + 1) % len(images)
            last_switch = now

        screen.fill(BACKGROUND_COLOR)
        image = images[index]
        rect = image.get_rect(center=(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2))
        screen.blit(image, rect)
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()

from pathlib import Path
import sys

import pygame


WINDOW_WIDTH = 700
WINDOW_HEIGHT = 400
BACKGROUND_COLOR = (173, 216, 230)  # light blue
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def load_faces(faces_dir: Path) -> dict[str, pygame.Surface]:
    image_paths = sorted(
        path for path in faces_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not image_paths:
        raise RuntimeError(f"No face images found in: {faces_dir}")

    faces: dict[str, pygame.Surface] = {}
    for path in image_paths:
        faces[path.stem.lower()] = pygame.image.load(str(path)).convert_alpha()
    return faces


def scale_to_fit(image: pygame.Surface, max_width: int, max_height: int) -> pygame.Surface:
    width, height = image.get_size()
    scale = min(max_width / width, max_height / height)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return pygame.transform.smoothscale(image, new_size)


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Face Test")
    clock = pygame.time.Clock()

    faces_dir = Path(__file__).resolve().parent / "faces"
    faces = load_faces(faces_dir)

    requested_face = sys.argv[1].lower() if len(sys.argv) > 1 else "sweet"
    if requested_face not in faces:
        requested_face = next(iter(faces))

    image = scale_to_fit(faces[requested_face], WINDOW_WIDTH - 100, WINDOW_HEIGHT - 100)
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

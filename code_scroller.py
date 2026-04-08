from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pygame

from config import Settings


FALLBACK_CODE = """def blend(a, b, t):
    return a * (1.0 - t) + b * t


def ribbon(x, phase, sharpness=9.0):
    wave = math.sin(x * math.pi + phase)
    return math.exp(-(wave * wave) * sharpness)


class Pulse:
    def __init__(self, speed=1.0):
        self.speed = speed
        self.time = 0.0

    def step(self, dt):
        self.time += dt * self.speed
        return 0.5 + 0.5 * math.sin(self.time)
"""


@dataclass(slots=True)
class CodeDocument:
    name: str
    lines: list[str]
    rendered_lines: list[pygame.Surface]
    total_height: int
    seed: float
    anchor_x: int


class CodeScroller:
    def __init__(
        self,
        settings: Settings,
        render_size: tuple[int, int],
        samples_dir: Path,
    ) -> None:
        self.settings = settings
        self.render_width, self.render_height = render_size
        self.scale = self.render_height / 270.0

        self.margin_x = max(10, int(round(settings.code_margin_x * self.scale)))
        self.margin_y = max(8, int(round(settings.code_margin_y * self.scale)))
        self.file_gap = max(12, int(round(settings.code_file_gap * self.scale)))
        self.scroll_speed = settings.code_scroll_speed * self.scale
        self.wobble_px = settings.code_wobble_px * self.scale
        self.edge_fade = max(8, int(round(settings.code_edge_fade * self.scale)))

        font_size = max(10, int(round(settings.code_font_size * self.scale)))
        font_path = self._find_font_path(settings.mono_font_candidates)
        self.font = pygame.font.Font(font_path, font_size)
        self.line_height = self.font.get_linesize() + max(1, int(round(settings.code_line_spacing * self.scale)))
        self.char_width = max(1, self.font.size("M")[0])
        self.max_chars = max(24, (self.render_width - self.margin_x * 2) // self.char_width)

        self.samples_dir = Path(samples_dir)
        self.documents: list[CodeDocument] = []
        self.index = 0
        self.scroll_y = float(self.render_height + self.file_gap)
        self.mask_surface = pygame.Surface(render_size, pygame.SRCALPHA, 32).convert_alpha()
        self.vertical_fade = self._build_vertical_fade(self.render_height, self.edge_fade)

        # ADD YOUR COMMENTS IN THIS LIST!!!!
        self._comment_messages: list[str] = [
            "// Memento mori",
            "# Guess we're doing this now",
            "// I see you",
              "// 💧 Cascade de Code 💧",
            "// L'eau se souvient de chaque ligne de code",
            "// Ici, le temps s'écoule comme une boucle infinie",
            "// Chaque goutte est une variable qui s'évapore",
            "// Le code respire, la cascade répond",
            "// Silence... le programme écoute l'eau tomber",
        
            "/ Et si le bug était juste une goutte hors du flux ?",
            "/ La réalité compile-t-elle sans erreurs ?",
            "/ L'eau ne plante jamais, elle s'adapte",
            "/ Tout s'exécute… même l'invisible",
        
            "// TODO: apprendre à nager avant de déboguer",
            "// Warning: cette cascade est plus stable que ton code",
            "// Si ça crash, blame l'eau 💧",
            "/ 404: goutte introuvable",
            "// Ceci n'est pas un bug, c'est de l'art",
        
            "/ Initialisation du flux aquatique...",
            "// Simulation en cours: gravity = ON",
            "/ Render des particules: mode cascade",
            "// Sync entre eau et syntaxe...",
            "/ Performance: fluide (jeu de mots validé)",
        
            "// Memento mori... même le code s'efface un jour"
            "// The end is never the end is never the end is never the end",
            "// Coding is fun, sometimes",
            "// What is even supposed to be here",
            "// Stressing out, freaking out",
            "// Ran out of ideas"
        ]
        # Each entry: (surface, offset_y, line_index)
        self._comments: list[tuple[pygame.Surface, float, int]] = []
        self._comment_wait: float = random.uniform(8.0, 18.0)

        self.reload_directory()

    def _find_font_path(self, candidates: tuple[str, ...]) -> str | None:
        for name in candidates:
            path = pygame.font.match_font(name)
            if path:
                return path
        return None

    def _build_vertical_fade(self, height: int, fade: int) -> np.ndarray:
        fade = max(1, fade)
        y = np.arange(height, dtype=np.float32)
        top = np.clip(y / fade, 0.0, 1.0)
        bottom = np.clip((height - 1 - y) / fade, 0.0, 1.0)
        return np.minimum(top, bottom)[:, None]

    def _document_seed(self, name: str) -> float:
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 1000000.0

    def _scan_files(self) -> list[Path]:
        if not self.samples_dir.exists():
            return []
        files = [
            path
            for path in sorted(self.samples_dir.iterdir())
            if path.is_file() and path.suffix.lower() in self.settings.supported_extensions
        ]
        return files

    def _sanitize_and_trim(self, line: str) -> str:
        line = line.expandtabs(self.settings.code_tab_size).rstrip("\n\r")
        line = line.rstrip()
        if len(line) <= self.max_chars:
            return line
        if self.max_chars <= 1:
            return ""
        return line[: self.max_chars - 1] + "…"

    def _header_lines(self, name: str) -> list[str]:
        header = f"# file: {name}"
        rule = "# " + "-" * max(4, min(self.max_chars - 2, len(name) + 6))
        return [header[: self.max_chars], rule[: self.max_chars], ""]

    def _build_document(self, name: str, text: str) -> CodeDocument:
        raw_lines = [self._sanitize_and_trim(line) for line in text.splitlines()]
        if not raw_lines:
            raw_lines = ["# empty file"]

        # If a code sample is very short, repeat it with separators so the file has
        # enough visual weight on stage.
        while len(raw_lines) < 28:
            raw_lines.extend(["", "# ---", ""] + raw_lines[: min(10, len(raw_lines))])
            if len(raw_lines) > 80:
                break

        lines = self._header_lines(name) + raw_lines
        rendered_lines: list[pygame.Surface] = []

        for line in lines:
            display_line = line if line else " "
            surface = self.font.render(display_line, True, (255, 255, 255))
            rendered_lines.append(surface)

        total_height = len(rendered_lines) * self.line_height + self.margin_y * 2
        seed = self._document_seed(name)
        max_width = max(surface.get_width() for surface in rendered_lines) if rendered_lines else 0
        available = max(0, self.render_width - (self.margin_x * 2) - max_width)
        anchor_fraction = 0.08 + 0.32 * (seed % 1.0)
        anchor_x = self.margin_x + int(available * anchor_fraction)
        return CodeDocument(
            name=name,
            lines=lines,
            rendered_lines=rendered_lines,
            total_height=total_height,
            seed=seed,
            anchor_x=anchor_x,
        )

    def reload_directory(self) -> None:
        files = self._scan_files()
        documents: list[CodeDocument] = []

        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="latin-1")
            except OSError:
                continue
            documents.append(self._build_document(path.name, text))

        if not documents:
            documents.append(self._build_document("fallback.py", FALLBACK_CODE))

        old_name = self.documents[self.index].name if self.documents else None
        self.documents = documents
        self.index = 0
        if old_name:
            for i, doc in enumerate(documents):
                if doc.name == old_name:
                    self.index = i
                    break
        self.restart_current()

    @property
    def current(self) -> CodeDocument:
        return self.documents[self.index]

    def restart_current(self) -> None:
        self.scroll_y = float(self.render_height + self.file_gap)
        # Clear any active inline comments when restarting a file
        self._comments.clear()
        self._comment_wait = random.uniform(8.0, 18.0)

    def update(self, dt: float) -> None:
        self.scroll_y -= self.scroll_speed * dt
        if self.scroll_y + self.current.total_height < -self.file_gap:
            self.next_file()

        # Drive inline comments that travel with the scrolling code.
        # They spawn just below the visible area and rise up like
        # code lines, with a small horizontal offset so they don't
        # overlap code text.
        if not self._comment_messages:
            return

        # Cull comments that have fully scrolled off the top.
        alive: list[tuple[pygame.Surface, float, int]] = []
        for surf, offset_y, line_index in self._comments:
            y_screen = self.scroll_y + offset_y
            if y_screen + surf.get_height() >= -self.line_height:
                alive.append((surf, offset_y, line_index))
        self._comments = alive

        # Spawn new comments based on a random interval; depending on
        # timing and scroll speed, there may be zero, one, or several
        # visible at once.
        self._comment_wait -= dt
        if self._comment_wait <= 0.0:
            # Find currently visible code lines so we can pin the
            # comment to a real line instead of empty space.
            doc = self.current
            visible_indices: list[int] = []
            for i, _ in enumerate(doc.rendered_lines):
                y = int(round(self.scroll_y + i * self.line_height))
                if y + self.line_height < -2:
                    continue
                if y > self.render_height - self.margin_y:
                    continue
                visible_indices.append(i)

            if not visible_indices:
                # No code on screen yet; try again shortly.
                self._comment_wait = 1.0
                return

            text = random.choice(self._comment_messages)
            safe = self._sanitize_and_trim(text)
            if not safe:
                safe = text
            surf = self.font.render(safe, True, (255, 255, 255))

            # Attach to the lowest visible line for horizontal
            # alignment, but spawn the comment just below the
            # bottom of the screen so it rises up like the code.
            line_index = max(visible_indices)
            target_screen_y = self.render_height + self.margin_y
            offset_y = float(target_screen_y - self.scroll_y)
            self._comments.append((surf, offset_y, line_index))
            self._comment_wait = random.uniform(6.0, 16.0)

    def next_file(self) -> None:
        self.index = (self.index + 1) % len(self.documents)
        self.restart_current()

    def previous_file(self) -> None:
        self.index = (self.index - 1) % len(self.documents)
        self.restart_current()

    def render_mask(self, t: float) -> np.ndarray:
        self.mask_surface.fill((0, 0, 0, 0))
        doc = self.current
        base_x = doc.anchor_x

        for i, line_surface in enumerate(doc.rendered_lines):
            y = int(round(self.scroll_y + i * self.line_height))
            if y + line_surface.get_height() < -2:
                continue
            if y > self.render_height + 2:
                continue

            x_wave = self.wobble_px * math.sin((t * 1.55) + (i * 0.37) + doc.seed)
            x_wave += self.wobble_px * 0.6 * math.sin((t * 3.2) + (y * 0.045))
            x = int(round(base_x + x_wave))
            self.mask_surface.blit(line_surface, (x, y))

        # Render any active inline comments so they travel with the
        # same motion field as the surrounding code, but offset
        # horizontally so they don't sit directly on top of code.
        for surf, offset_y, line_index in self._comments:
            y = int(round(self.scroll_y + offset_y))
            if -self.line_height <= y <= self.render_height + self.line_height:
                if 0 <= line_index < len(doc.rendered_lines):
                    code_line = doc.rendered_lines[line_index]
                    code_width = code_line.get_width()
                else:
                    code_width = 0

                base_comment_x = base_x + code_width + int(self.char_width * 1.5)
                max_x = self.render_width - surf.get_width() - self.margin_x
                base_comment_x = max(self.margin_x, min(max_x, base_comment_x))

                x_wave = self.wobble_px * math.sin((t * 1.55) + (0.37 * 0.5) + doc.seed * 1.3)
                x_wave += self.wobble_px * 0.6 * math.sin((t * 3.2) + (y * 0.045))
                x = int(round(base_comment_x + x_wave))
                self.mask_surface.blit(surf, (x, y))

        alpha = pygame.surfarray.array_alpha(self.mask_surface).swapaxes(0, 1).astype(np.float32)
        alpha *= self.vertical_fade
        alpha /= 255.0
        return alpha

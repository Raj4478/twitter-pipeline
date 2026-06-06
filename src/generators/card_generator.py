"""
Card Generator — creates visual infographic cards for Twitter threads.
Dark theme, code-style design matching dev Twitter aesthetic.
Output: 1200x675 (Twitter recommended) PNG.
"""

import logging
import textwrap
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("tmp/cards")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Twitter card dimensions
CARD_W, CARD_H = 1200, 675

# Dev dark theme palette
BG_DARK    = (13, 17, 23)       # GitHub dark
BG_CARD    = (22, 27, 34)       # Card background
BLUE       = (88, 166, 255)     # Code blue
GREEN      = (63, 185, 80)      # Terminal green
YELLOW     = (255, 212, 0)      # Warning yellow
ORANGE     = (255, 127, 80)     # Accent orange
WHITE      = (230, 237, 243)    # Near white
GREY       = (110, 118, 129)    # Muted
PURPLE     = (188, 140, 255)    # Function purple
RED        = (248, 81, 73)      # Error red


class CardGenerator:
    def generate(self, topic: str, image_text: str, niche: str,
                 facts: list[str] = None) -> Path:
        """Generate a Twitter card for the thread topic."""
        from PIL import Image, ImageDraw
        card_id = uuid.uuid4().hex[:8]
        out_path = OUTPUT_DIR / f"card_{card_id}.png"

        img = Image.new("RGB", (CARD_W, CARD_H), BG_DARK)
        draw = ImageDraw.Draw(img)

        if niche == "system_design":
            self._draw_system_design_card(draw, img, topic, image_text, facts or [])
        else:
            self._draw_code_card(draw, img, topic, image_text, facts or [])

        img.save(str(out_path), "PNG")
        logger.info("Card saved: %s", out_path)
        return out_path

    def _draw_system_design_card(self, draw, img, topic, image_text, facts):
        from PIL import ImageDraw

        # Top bar — terminal style
        draw.rectangle([0, 0, CARD_W, 45], fill=BG_CARD)
        # Terminal dots
        for i, color in enumerate([(RED), (YELLOW), (GREEN)]):
            x = 20 + i * 22
            draw.ellipse([x, 15, x + 14, 29], fill=color)
        draw.text((70, 22), f"system-design/{topic[:40].replace(' ', '-')}.md",
                  font=self._font(16), fill=GREY, anchor="lm")

        # Main title
        title_lines = textwrap.wrap(topic.upper(), width=35)
        y = 90
        for line in title_lines:
            draw.text((CARD_W // 2, y), line, font=self._font(52),
                      fill=WHITE, anchor="mm")
            y += 65

        # Divider
        draw.rectangle([60, y + 10, CARD_W - 60, y + 14], fill=BLUE)
        y += 35

        # Facts list
        for i, fact in enumerate(facts[:4]):
            fact_clean = fact[:70]
            draw.text((80, y), f"→", font=self._font(26), fill=GREEN)
            draw.text((110, y), fact_clean, font=self._font(24), fill=WHITE)
            y += 40

        # Bottom brand bar
        draw.rectangle([0, CARD_H - 55, CARD_W, CARD_H], fill=BG_CARD)
        draw.text((40, CARD_H - 27), "🧵 THREAD",
                  font=self._font(22), fill=BLUE, anchor="lm")
        draw.text((CARD_W - 40, CARD_H - 27), "@your_handle | #SystemDesign",
                  font=self._font(20), fill=GREY, anchor="rm")

    def _draw_code_card(self, draw, img, topic, image_text, facts):
        # Terminal header
        draw.rectangle([0, 0, CARD_W, 50], fill=BG_CARD)
        for i, color in enumerate([RED, YELLOW, GREEN]):
            x = 20 + i * 22
            draw.ellipse([x, 16, x + 16, 32], fill=color)
        draw.text((75, 25), "~/dev/tips $ node explain.js",
                  font=self._font(18), fill=GREY, anchor="lm")

        # Title
        title_lines = textwrap.wrap(topic, width=40)
        y = 100
        for line in title_lines:
            draw.text((CARD_W // 2, y), line, font=self._font(46),
                      fill=YELLOW, anchor="mm")
            y += 58

        # Code block style box
        box_y = y + 20
        draw.rounded_rectangle([50, box_y, CARD_W - 50, box_y + 200],
                               radius=8, fill=BG_CARD)
        draw.rounded_rectangle([50, box_y, 56, box_y + 200],
                               radius=0, fill=GREEN)

        ty = box_y + 20
        for i, fact in enumerate(facts[:4]):
            color = [GREEN, BLUE, PURPLE, ORANGE][i % 4]
            draw.text((75, ty), f"// {fact[:65]}",
                      font=self._font(22), fill=color)
            ty += 42

        # Footer
        draw.rectangle([0, CARD_H - 50, CARD_W, CARD_H], fill=BG_CARD)
        draw.text((40, CARD_H - 25), "💻 WebDev Tips",
                  font=self._font(20), fill=GREEN, anchor="lm")
        draw.text((CARD_W - 40, CARD_H - 25), "#WebDev #JavaScript #NodeJS",
                  font=self._font(18), fill=GREY, anchor="rm")

    def _font(self, size: int):
        from PIL import ImageFont
        # Try monospace fonts first for dev aesthetic
        candidates = [
            "C:/Windows/Fonts/consola.ttf",    # Consolas — best for code
            "C:/Windows/Fonts/cour.ttf",        # Courier New
            "C:/Windows/Fonts/lucon.ttf",       # Lucida Console
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for fp in candidates:
            try:
                return ImageFont.truetype(fp, size)
            except (IOError, OSError):
                continue
        from PIL import ImageFont
        return ImageFont.load_default()

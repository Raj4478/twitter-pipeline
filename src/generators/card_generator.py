"""
Smart Card Generator — generates architecture diagrams + infographic cards.

Flow:
  1. Ask Gemini to generate Mermaid diagram code for the topic
  2. Render Mermaid → PNG via mmdc (Mermaid CLI)
  3. Composite: diagram (top 70%) + title/facts bar (bottom 30%)
  4. Fallback to pure Pillow card if mmdc fails

Output: 1200x675 PNG (Twitter/Telegram optimal)
"""

import logging
import textwrap
import uuid
import subprocess
import json
import tempfile
import os
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("tmp/cards")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CARD_W, CARD_H = 1200, 675

# Dark theme palette
BG_DARK   = (13, 17, 23)
BG_CARD   = (22, 27, 34)
BG_PANEL  = (30, 35, 45)
BLUE      = (88, 166, 255)
GREEN     = (63, 185, 80)
YELLOW    = (255, 212, 0)
ORANGE    = (255, 127, 80)
WHITE     = (230, 237, 243)
GREY      = (110, 118, 129)
PURPLE    = (188, 140, 255)
RED       = (248, 81, 73)
CYAN      = (79, 201, 197)

# ── Mermaid prompts per topic type ────────────────────────────────────────────

MERMAID_SYSTEM = """You are a system design expert. Generate clean Mermaid diagram code
for architecture visualizations. Keep diagrams simple, readable, and accurate.
Respond ONLY with valid JSON. No markdown fences."""

MERMAID_PROMPTS = {
    "system_design": """Generate a Mermaid flowchart or sequence diagram for: "{topic}"

Rules:
- Use flowchart LR or TD direction
- Include 6-10 nodes max (keep it readable)
- Use real component names (Producer, Broker, Consumer, Cache, DB, CDN, LB etc.)
- Add meaningful edge labels
- Use subgraphs to group related components
- Dark theme compatible (no light colors)

Return JSON: {{"mermaid": "your mermaid code here", "diagram_type": "architecture|flow|sequence"}}""",

    "webdev": """Generate a Mermaid diagram for: "{topic}"

Rules:
- Use flowchart LR or sequence diagram as appropriate
- Show the actual technical flow (request → processing → response)
- Include code-level components (middleware, handler, DB query etc.)
- 6-8 nodes max

Return JSON: {{"mermaid": "your mermaid code here", "diagram_type": "architecture|flow|sequence"}}""",

    "career": None  # Career topics use the enhanced Pillow card
}

MERMAID_CONFIG = """{
  "theme": "dark",
  "themeVariables": {
    "darkMode": true,
    "background": "#0d1117",
    "primaryColor": "#1f2937",
    "primaryTextColor": "#e6edf3",
    "primaryBorderColor": "#58a6ff",
    "lineColor": "#58a6ff",
    "secondaryColor": "#161b22",
    "tertiaryColor": "#21262d",
    "edgeLabelBackground": "#0d1117",
    "clusterBkg": "#161b22",
    "clusterBorder": "#30363d",
    "titleColor": "#e6edf3",
    "nodeTextColor": "#e6edf3",
    "fontFamily": "monospace"
  },
  "flowchart": {
    "curve": "basis",
    "padding": 20,
    "nodeSpacing": 50,
    "rankSpacing": 60
  }
}"""


class SmartCardGenerator:

    def __init__(self, settings=None):
        self.settings = settings
        self._mmdc_available = self._check_mmdc()

    def _check_mmdc(self) -> bool:
        try:
            result = subprocess.run(
                ["mmdc", "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                logger.info("mmdc available: %s", result.stdout.strip())
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        logger.warning("mmdc not available — will use Pillow fallback")
        return False

    def generate(self, topic: str, image_text: str, niche: str,
                 facts: list[str] = None) -> Path:
        """Main entry point — generates best possible card for topic."""
        card_id = uuid.uuid4().hex[:8]
        out_path = OUTPUT_DIR / f"card_{card_id}.png"

        # Try architecture diagram for system_design and webdev
        logger.info("Card path: mmdc=%s niche=%s settings=%s", self._mmdc_available, niche, bool(self.settings))
        if self._mmdc_available and niche in ("system_design", "webdev") and self.settings:
            try:
                return self._generate_architecture_card(
                    topic, image_text, niche, facts or [], out_path
                )
            except Exception as e:
                import traceback
                logger.error("Architecture card FAILED (full trace):\n%s", traceback.format_exc())
                logger.warning("Falling back to Pillow card")

        # Fallback: enhanced Pillow card
        return self._generate_pillow_card(topic, image_text, niche, facts or [], out_path)

    def _generate_architecture_card(self, topic: str, image_text: str,
                                     niche: str, facts: list[str],
                                     out_path: Path) -> Path:
        """Generate diagram via Gemini → Mermaid → PNG composite."""
        # 1. Generate Mermaid code via Gemini (sync — avoids nested event loop)
        mermaid_data = self._generate_mermaid_sync(topic, niche)

        mermaid_code = mermaid_data.get("mermaid", "")
        if not mermaid_code:
            raise ValueError("Empty mermaid code from Gemini")

        logger.info("Mermaid code generated (%d chars)", len(mermaid_code))

        # 2. Render Mermaid → PNG
        diagram_png = self._render_mermaid(mermaid_code)
        logger.info("Mermaid rendered: %s", diagram_png)

        # 3. Composite diagram + info panel
        self._composite_card(diagram_png, topic, niche, facts, out_path)
        logger.info("Architecture card saved: %s", out_path)
        return out_path

    def _generate_mermaid_sync(self, topic: str, niche: str) -> dict:
        """Ask Gemini to generate Mermaid diagram code (synchronous)."""
        prompt_template = MERMAID_PROMPTS.get(niche, MERMAID_PROMPTS["system_design"])
        prompt = prompt_template.format(topic=topic)

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": MERMAID_SYSTEM}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 800,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw)

    def _render_mermaid(self, mermaid_code: str) -> Path:
        """Render Mermaid code to PNG using mmdc CLI."""
        tmp_dir = Path(tempfile.mkdtemp())
        input_file = tmp_dir / "diagram.mmd"
        output_file = tmp_dir / "diagram.png"
        config_file = tmp_dir / "config.json"

        input_file.write_text(mermaid_code, encoding="utf-8")
        config_file.write_text(MERMAID_CONFIG, encoding="utf-8")

        result = subprocess.run(
            [
                "mmdc",
                "-i", str(input_file),
                "-o", str(output_file),
                "-c", str(config_file),
                "-w", "1200",
                "-H", "450",
                "-b", "transparent",
                "--quiet",
            ],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            raise RuntimeError(f"mmdc failed: {result.stderr[:200]}")

        if not output_file.exists():
            raise RuntimeError("mmdc produced no output file")

        return output_file

    def _composite_card(self, diagram_png: Path, topic: str, niche: str,
                         facts: list[str], out_path: Path):
        """Composite: diagram (top 70%) + info panel (bottom 30%)."""
        from PIL import Image, ImageDraw

        DIAGRAM_H = 460
        PANEL_H = CARD_H - DIAGRAM_H  # 215px

        # ── Base canvas ───────────────────────────────────────────────
        canvas = Image.new("RGB", (CARD_W, CARD_H), BG_DARK)
        draw = ImageDraw.Draw(canvas)

        # ── Diagram section ───────────────────────────────────────────
        diagram = Image.open(diagram_png).convert("RGBA")

        # Handle transparent background
        bg = Image.new("RGB", diagram.size, BG_DARK)
        if diagram.mode == "RGBA":
            bg.paste(diagram, mask=diagram.split()[3])
        else:
            bg.paste(diagram)

        # Fit diagram into top area preserving aspect ratio
        diagram_ratio = bg.width / bg.height
        target_ratio = CARD_W / DIAGRAM_H

        if diagram_ratio > target_ratio:
            new_w = CARD_W
            new_h = int(CARD_W / diagram_ratio)
        else:
            new_h = DIAGRAM_H
            new_w = int(DIAGRAM_H * diagram_ratio)

        bg = bg.resize((new_w, new_h), Image.LANCZOS)

        # Center horizontally
        x_offset = (CARD_W - new_w) // 2
        y_offset = (DIAGRAM_H - new_h) // 2
        canvas.paste(bg, (x_offset, y_offset))

        # Gradient overlay at bottom of diagram for smooth transition
        for i in range(60):
            alpha = int(255 * (i / 60) ** 2)
            draw.rectangle(
                [0, DIAGRAM_H - 60 + i, CARD_W, DIAGRAM_H - 59 + i],
                fill=(*BG_DARK, alpha)
            )

        # ── Info panel ─────────────────────────────────────────────────
        panel_y = DIAGRAM_H
        draw.rectangle([0, panel_y, CARD_W, CARD_H], fill=BG_CARD)

        # Top border accent
        accent_color = {
            "system_design": BLUE,
            "webdev": GREEN,
            "career": PURPLE,
        }.get(niche, BLUE)
        draw.rectangle([0, panel_y, CARD_W, panel_y + 3], fill=accent_color)

        # Topic title
        title = topic.upper()
        title_wrapped = textwrap.wrap(title, width=55)
        ty = panel_y + 18
        for line in title_wrapped[:1]:  # Max 1 line
            draw.text((CARD_W // 2, ty), line,
                      font=self._font(28), fill=WHITE, anchor="mm")

        # Key facts as inline chips
        chip_x = 40
        chip_y = panel_y + 58
        for i, fact in enumerate(facts[:4]):
            fact_short = fact[:50].strip()
            text_w = len(fact_short) * 13 + 24

            # Wrap to next line if needed
            if chip_x + text_w > CARD_W - 40:
                chip_x = 40
                chip_y += 42

            draw.rounded_rectangle(
                [chip_x, chip_y, chip_x + text_w, chip_y + 30],
                radius=6,
                fill=BG_PANEL,
                outline=accent_color,
                width=1,
            )
            colors = [GREEN, CYAN, YELLOW, ORANGE]
            draw.text(
                (chip_x + 12, chip_y + 15),
                fact_short,
                font=self._font(16),
                fill=colors[i % 4],
                anchor="lm",
            )
            chip_x += text_w + 12

        # Bottom branding bar
        bar_y = CARD_H - 38
        draw.rectangle([0, bar_y, CARD_W, CARD_H], fill=BG_DARK)
        draw.text((40, bar_y + 19), "🧵 THREAD",
                  font=self._font(18), fill=accent_color, anchor="lm")

        niche_tags = {
            "system_design": "#SystemDesign #HLD #SoftwareEngineering",
            "webdev": "#WebDev #Backend #Programming",
            "career": "#CareerAdvice #SoftwareEngineering",
        }.get(niche, "#Tech")
        draw.text((CARD_W - 40, bar_y + 19), niche_tags,
                  font=self._font(16), fill=GREY, anchor="rm")

        canvas.save(str(out_path), "PNG", quality=95)

    def _generate_pillow_card(self, topic: str, image_text: str, niche: str,
                               facts: list[str], out_path: Path) -> Path:
        """Enhanced Pillow fallback card."""
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (CARD_W, CARD_H), BG_DARK)
        draw = ImageDraw.Draw(img)

        accent = {
            "system_design": BLUE,
            "webdev": GREEN,
            "career": PURPLE,
        }.get(niche, BLUE)

        # Top terminal bar
        draw.rectangle([0, 0, CARD_W, 48], fill=BG_CARD)
        for i, color in enumerate([RED, YELLOW, GREEN]):
            x = 20 + i * 22
            draw.ellipse([x, 16, x + 16, 32], fill=color)
        draw.text((72, 24), f"~/dev/{niche} — {topic[:45]}",
                  font=self._font(16), fill=GREY, anchor="lm")

        # Side accent bar
        draw.rectangle([0, 48, 5, CARD_H - 48], fill=accent)

        # Big topic title
        title_lines = textwrap.wrap(topic.upper(), width=32)
        y = 110
        for line in title_lines[:2]:
            draw.text((CARD_W // 2, y), line,
                      font=self._font(58), fill=WHITE, anchor="mm")
            y += 72

        # Divider
        draw.rectangle([60, y + 10, CARD_W - 60, y + 14], fill=accent)
        y += 30

        # Facts
        for i, fact in enumerate(facts[:4]):
            colors = [GREEN, CYAN, YELLOW, ORANGE]
            draw.text((85, y + 5), "▶",
                      font=self._font(22), fill=colors[i % 4])
            draw.text((115, y + 5), fact[:72],
                      font=self._font(23), fill=WHITE)
            y += 44

        # Bottom bar
        draw.rectangle([0, CARD_H - 52, CARD_W, CARD_H], fill=BG_CARD)
        draw.rectangle([0, CARD_H - 52, CARD_W, CARD_H - 49], fill=accent)
        draw.text((40, CARD_H - 26), "🧵 THREAD",
                  font=self._font(20), fill=accent, anchor="lm")
        niche_tags = {
            "system_design": "#SystemDesign #HLD #SoftwareEngineering",
            "webdev": "#WebDev #Backend #Programming",
            "career": "#CareerAdvice #IndianDev",
        }.get(niche, "#Tech")
        draw.text((CARD_W - 40, CARD_H - 26), niche_tags,
                  font=self._font(18), fill=GREY, anchor="rm")

        img.save(str(out_path), "PNG")
        logger.info("Pillow card saved: %s", out_path)
        return out_path

    def _font(self, size: int):
        from PIL import ImageFont
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
        ]
        for fp in candidates:
            try:
                return ImageFont.truetype(fp, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()


# Backward-compatible alias
CardGenerator = SmartCardGenerator

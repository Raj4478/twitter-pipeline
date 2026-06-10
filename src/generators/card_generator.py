"""
Smart Card Generator — sky blue workflow pipeline diagrams.

Flow:
  1. Ask Gemini for structured pipeline stages JSON
  2. Render with Pillow — sky blue bg, white stage cards, colored headers
  3. Fallback to text card for career niche
"""

import logging
import textwrap
import uuid
import json
import math
import os
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("tmp/cards")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CARD_W, CARD_H = 1280, 780

# ── Colors ─────────────────────────────────────────────────────────────────────
SKY_LIGHT  = (224, 242, 254)
SKY_MID    = (186, 230, 253)
SKY_DEEP   = (14,  165, 233)
SKY_DEEPER = (2,   132, 199)
NAVY       = (12,  40,  80)
WHITE      = (255, 255, 255)
GREY       = (100, 130, 160)

# Stage color palettes [header, card_bg]
STAGE_PALETTES = [
    {"header": (234, 88,  12),  "light": (255, 237, 213)},  # Orange
    {"header": (14,  165, 233), "light": (186, 230, 253)},  # Sky blue
    {"header": (22,  163, 74),  "light": (220, 252, 231)},  # Green
    {"header": (109, 40,  217), "light": (237, 233, 254)},  # Purple
    {"header": (220, 38,  38),  "light": (254, 226, 226)},  # Red
]

# PIL fallbacks
BG_DARK_PIL  = (13,  17,  23)
BG_CARD_PIL  = (22,  27,  34)
BLUE_PIL     = (88,  166, 255)
GREEN_PIL    = (63,  185, 80)
YELLOW_PIL   = (255, 212, 0)
ORANGE_PIL   = (255, 127, 80)
WHITE_PIL    = (230, 237, 243)
GREY_PIL     = (110, 118, 129)
PURPLE_PIL   = (188, 140, 255)
CYAN_PIL     = (79,  201, 197)
RED_PIL      = (248, 81,  73)
MUTED_PIL    = (90,  110, 150)

# ── Gemini prompts ──────────────────────────────────────────────────────────────

PIPELINE_SYSTEM = """You are a system design expert. Return ONLY valid JSON. No markdown."""

PIPELINE_PROMPT = '''Generate a workflow pipeline diagram for: "{topic}"

Map each node to one of these icon values:
  server, kafka, rabbitmq, redis, postgresql, mysql, mongodb, nginx,
  haproxy, zookeeper, prometheus, grafana, spark, hadoop, users, user,
  mlflow, pytorch

Return JSON with 3-5 stages, each stage has 2-3 nodes:
{{
  "title": "HOW {topic_upper} WORKS",
  "stages": [
    {{
      "title": "PRODUCERS",
      "subtitle": "Event Sources",
      "nodes": [
        {{"label": "Order\\nService", "icon": "server"}},
        {{"label": "Payment\\nService", "icon": "server"}}
      ]
    }},
    {{
      "title": "KAFKA CLUSTER",
      "subtitle": "Message Broker",
      "nodes": [
        {{"label": "Broker 1\\nLeader", "icon": "kafka"}},
        {{"label": "ZooKeeper\\nCoord", "icon": "zookeeper"}}
      ]
    }},
    {{
      "title": "CONSUMERS",
      "subtitle": "Processing",
      "nodes": [
        {{"label": "Notification\\nService", "icon": "server"}},
        {{"label": "Analytics\\nEngine", "icon": "spark"}}
      ]
    }},
    {{
      "title": "STORAGE",
      "subtitle": "Persistence",
      "nodes": [
        {{"label": "PostgreSQL\\nEvents", "icon": "postgresql"}},
        {{"label": "Redis\\nCache", "icon": "redis"}}
      ]
    }}
  ],
  "flow_labels": ["publish events", "distribute", "consume & process"]
}}

Rules:
- 3-5 stages total, each 2-3 nodes
- Stage titles and flow labels must reflect actual {topic} architecture
- Use specific component names, not generic ones
- flow_labels array length = stages count - 1'''

# ── Icon mapping ────────────────────────────────────────────────────────────────

ICON_MAP = {
    "kafka":      "onprem/queue/kafka.png",
    "rabbitmq":   "onprem/queue/rabbitmq.png",
    "redis":      "onprem/inmemory/redis.png",
    "postgresql": "onprem/database/postgresql.png",
    "mysql":      "onprem/database/mysql.png",
    "mongodb":    "onprem/database/mongodb.png",
    "nginx":      "onprem/network/nginx.png",
    "haproxy":    "onprem/network/haproxy.png",
    "zookeeper":  "onprem/network/zookeeper.png",
    "prometheus": "onprem/monitoring/prometheus.png",
    "grafana":    "onprem/monitoring/grafana.png",
    "spark":      "onprem/analytics/spark.png",
    "hadoop":     "onprem/analytics/hadoop.png",
    "server":     "onprem/compute/server.png",
    "users":      "onprem/client/users.png",
    "user":       "onprem/client/user.png",
    "mlflow":     "onprem/mlops/mlflow.png",
    "pytorch":    "onprem/mlops/pytorch.png",
}


class SmartCardGenerator:

    def __init__(self, settings=None):
        self.settings = settings
        try:
            import diagrams as _d
            self._resources = Path(_d.__file__).parent / "resources"
            self._has_icons = (self._resources / "onprem/queue/kafka.png").exists()
        except Exception:
            self._has_icons = False
        logger.info("Icons available: %s", self._has_icons)

    def generate(self, topic: str, image_text: str, niche: str,
                 facts: list[str] = None) -> Path:
        card_id = uuid.uuid4().hex[:8]
        out_path = OUTPUT_DIR / f"card_{card_id}.png"

        if niche in ("system_design", "webdev") and self.settings:
            try:
                return self._generate_pipeline_card(
                    topic, niche, facts or [], out_path
                )
            except Exception:
                import traceback
                logger.error("Pipeline card failed:\n%s", traceback.format_exc())
                logger.warning("Falling back to text card")

        return self._generate_text_card(topic, image_text, niche, facts or [], out_path)

    # ── Pipeline card ──────────────────────────────────────────────────────────

    def _generate_pipeline_card(self, topic: str, niche: str,
                                  facts: list[str], out_path: Path) -> Path:
        pipeline = self._get_pipeline(topic, niche)
        logger.info("Pipeline: %d stages", len(pipeline.get("stages", [])))
        self._render_pipeline(pipeline, topic, niche, out_path)
        logger.info("Pipeline card saved: %s", out_path)
        return out_path

    def _get_pipeline(self, topic: str, niche: str) -> dict:
        prompt = PIPELINE_PROMPT.format(
            topic=topic,
            topic_upper=topic.upper()
        )
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": PIPELINE_SYSTEM}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 900,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(raw)

    def _load_icon(self, icon_name: str, size: int = 52) -> object:
        from PIL import Image, ImageDraw
        if self._has_icons:
            rel = ICON_MAP.get(icon_name.lower(), "onprem/compute/server.png")
            full = self._resources / rel
            if full.exists():
                img = Image.open(full).convert("RGBA")
                return img.resize((size, size), Image.LANCZOS)
        # Placeholder circle
        ph = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d  = ImageDraw.Draw(ph)
        d.ellipse([4, 4, size - 4, size - 4], fill=(14, 165, 233, 200))
        return ph

    def _render_pipeline(self, pipeline: dict, topic: str,
                          niche: str, out_path: Path):
        from PIL import Image, ImageDraw

        stages = pipeline.get("stages", [])
        flow_labels = pipeline.get("flow_labels", [])
        title = pipeline.get("title", topic.upper())

        if not stages:
            raise ValueError("No stages returned")

        # ── Canvas: sky blue gradient ──────────────────────────────────
        canvas = Image.new("RGB", (CARD_W, CARD_H), SKY_LIGHT)
        draw   = ImageDraw.Draw(canvas)

        for y in range(CARD_H):
            t = y / CARD_H
            r = int(224 - t * 32)
            g = int(242 - t * 22)
            b = int(254 - t * 12)
            draw.line([(0, y), (CARD_W, y)], fill=(r, g, b))

        # Subtle cloud blobs
        cloud_positions = [
            (180, 90, 160, 16), (980, 55, 200, 12),
            (1150, 320, 140, 10), (120, 620, 180, 9),
            (680, 700, 220, 9),
        ]
        for cx, cy, rc, al in cloud_positions:
            overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.ellipse([cx-rc, cy-rc, cx+rc, cy+rc], fill=(255, 255, 255, al))
            canvas = Image.alpha_composite(
                canvas.convert("RGBA"), overlay
            ).convert("RGB")

        draw = ImageDraw.Draw(canvas)

        # ── Title bar ──────────────────────────────────────────────────
        draw.rectangle([0, 0, CARD_W, 66], fill=SKY_DEEPER)
        draw.rectangle([0, 63, CARD_W, 66], fill=(*WHITE, 60))
        draw.text((CARD_W // 2, 33), title,
                  font=self._font(22, bold=True),
                  fill=WHITE, anchor="mm")

        # ── Layout ─────────────────────────────────────────────────────
        MARGIN_X   = 52
        MARGIN_TOP = 82
        BOTTOM_BAR = 52
        STEP_ROW   = 38
        CONTENT_H  = CARD_H - MARGIN_TOP - BOTTOM_BAR - STEP_ROW
        STAGE_COUNT = len(stages)
        STAGE_W    = (CARD_W - 2 * MARGIN_X) // STAGE_COUNT
        NODE_W     = STAGE_W - 28
        ICON_SZ    = 50
        HEADER_H   = 54
        CORNER_R   = 12
        ARROW_Y    = MARGIN_TOP + HEADER_H + (CONTENT_H - HEADER_H) // 2

        stage_cx = []

        for si, stage in enumerate(stages):
            pal   = STAGE_PALETTES[si % len(STAGE_PALETTES)]
            col   = pal["header"]
            light = pal["light"]
            sx    = MARGIN_X + si * STAGE_W
            sy    = MARGIN_TOP
            cx_s  = sx + STAGE_W // 2
            stage_cx.append(cx_s)

            # Card shadow
            draw.rounded_rectangle(
                [sx + 10, sy + 4, sx + STAGE_W - 6, sy + CONTENT_H + 4],
                radius=CORNER_R, fill=(*col, 22)
            )
            # Card body
            draw.rounded_rectangle(
                [sx + 8, sy, sx + STAGE_W - 8, sy + CONTENT_H],
                radius=CORNER_R, fill=WHITE
            )
            draw.rounded_rectangle(
                [sx + 8, sy, sx + STAGE_W - 8, sy + CONTENT_H],
                radius=CORNER_R, outline=col, width=2
            )

            # Header
            draw.rounded_rectangle(
                [sx + 8, sy, sx + STAGE_W - 8, sy + HEADER_H],
                radius=CORNER_R, fill=col
            )
            draw.rectangle(
                [sx + 8, sy + HEADER_H - CORNER_R,
                 sx + STAGE_W - 8, sy + HEADER_H],
                fill=col
            )
            draw.text((cx_s, sy + 18), stage.get("title", ""),
                      font=self._font(15, bold=True),
                      fill=WHITE, anchor="mm")
            draw.text((cx_s, sy + 38), stage.get("subtitle", ""),
                      font=self._font(11, bold=False),
                      fill=WHITE, anchor="mm")

            # Nodes
            nodes = stage.get("nodes", [])
            node_count = max(len(nodes), 1)
            NODE_H = min(114, (CONTENT_H - HEADER_H - 20) // node_count - 12)
            total_h = node_count * NODE_H + (node_count - 1) * 12
            start_y = sy + HEADER_H + (CONTENT_H - HEADER_H - total_h) // 2

            for ni, node in enumerate(nodes):
                ny   = start_y + ni * (NODE_H + 12)
                nx   = sx + 8 + (STAGE_W - 16 - NODE_W) // 2
                icon = self._load_icon(node.get("icon", "server"), ICON_SZ)

                # Node card
                draw.rounded_rectangle(
                    [nx, ny, nx + NODE_W, ny + NODE_H],
                    radius=9, fill=light
                )
                draw.rounded_rectangle(
                    [nx, ny, nx + NODE_W, ny + NODE_H],
                    radius=9, outline=col, width=1
                )

                # Icon
                ix = nx + (NODE_W - ICON_SZ) // 2
                iy = ny + 8
                canvas.paste(icon, (ix, iy), mask=icon.split()[3])

                # Label
                label_y = ny + ICON_SZ + 14
                for li, line in enumerate(
                    node.get("label", "").split("\\n")
                ):
                    draw.text((nx + NODE_W // 2, label_y + li * 16),
                              line,
                              font=self._font(12, bold=True),
                              fill=NAVY, anchor="mm")

        # ── Arrows between stages ──────────────────────────────────────
        for i in range(STAGE_COUNT - 1):
            pal_from = STAGE_PALETTES[i % len(STAGE_PALETTES)]
            x1 = stage_cx[i] + STAGE_W // 2 - 14
            x2 = stage_cx[i + 1] - STAGE_W // 2 + 14
            ay = ARROW_Y

            # Line
            draw.line([(x1, ay), (x2 - 16, ay)],
                      fill=SKY_DEEPER, width=4)
            # Arrowhead
            draw.polygon([
                (x2 - 16, ay - 10),
                (x2,      ay),
                (x2 - 16, ay + 10),
            ], fill=SKY_DEEPER)

            # Label pill
            mx = (x1 + x2) // 2
            label = flow_labels[i] if i < len(flow_labels) else ""
            if label:
                pw = len(label) * 8 + 28
                ph = 26
                draw.rounded_rectangle(
                    [mx - pw//2, ay - ph//2 - 22,
                     mx + pw//2, ay - ph//2 - 22 + ph],
                    radius=7, fill=SKY_DEEPER
                )
                draw.text((mx, ay - 22),
                          label,
                          font=self._font(11, bold=False),
                          fill=WHITE, anchor="mm")

        # ── Step number circles ────────────────────────────────────────
        step_y = MARGIN_TOP + CONTENT_H + 10
        for si, stage in enumerate(stages):
            pal = STAGE_PALETTES[si % len(STAGE_PALETTES)]
            cx_s = stage_cx[si]
            draw.ellipse(
                [cx_s - 14, step_y, cx_s + 14, step_y + 28],
                fill=pal["header"], outline=WHITE, width=2
            )
            draw.text((cx_s, step_y + 14), str(si + 1),
                      font=self._font(14, bold=True),
                      fill=WHITE, anchor="mm")

        # ── Bottom bar ─────────────────────────────────────────────────
        bar_y = CARD_H - BOTTOM_BAR
        draw.rectangle([0, bar_y, CARD_W, CARD_H], fill=SKY_DEEPER)
        draw.rectangle([0, bar_y, CARD_W, bar_y + 2], fill=WHITE)

        draw.text((30, bar_y + BOTTOM_BAR // 2),
                  "⚡ @byte_blueprint",
                  font=self._font(17, bold=True),
                  fill=WHITE, anchor="lm")

        niche_label = {
            "system_design": "SYSTEM DESIGN SERIES",
            "webdev":        "WEB DEV SERIES",
            "career":        "CAREER SERIES",
        }.get(niche, "TECH SERIES")
        draw.text((CARD_W // 2, bar_y + BOTTOM_BAR // 2),
                  niche_label,
                  font=self._font(14, bold=False),
                  fill=WHITE, anchor="mm")

        tags = {
            "system_design": "#SystemDesign  #HLD  #SoftwareEngineering",
            "webdev":        "#WebDev  #Backend  #Programming",
            "career":        "#CareerAdvice  #IndianDev",
        }.get(niche, "#Tech")
        draw.text((CARD_W - 30, bar_y + BOTTOM_BAR // 2),
                  tags,
                  font=self._font(13, bold=False),
                  fill=WHITE, anchor="rm")

        canvas.save(str(out_path), "PNG", quality=95)

    # ── Text fallback card ─────────────────────────────────────────────────────

    def _generate_text_card(self, topic: str, image_text: str, niche: str,
                             facts: list[str], out_path: Path) -> Path:
        from PIL import Image, ImageDraw

        img  = Image.new("RGB", (CARD_W, CARD_H), BG_DARK_PIL)
        draw = ImageDraw.Draw(img)
        accent = {
            "system_design": BLUE_PIL,
            "webdev":        GREEN_PIL,
            "career":        PURPLE_PIL,
        }.get(niche, BLUE_PIL)

        draw.rectangle([0, 0, CARD_W, 48], fill=BG_CARD_PIL)
        for i, color in enumerate([RED_PIL, YELLOW_PIL, GREEN_PIL]):
            x = 20 + i * 22
            draw.ellipse([x, 16, x + 16, 32], fill=color)
        draw.text((72, 24), f"~/dev/{niche} — {topic[:45]}",
                  font=self._font(16), fill=GREY_PIL, anchor="lm")
        draw.rectangle([0, 48, 5, CARD_H - 48], fill=accent)

        title_lines = textwrap.wrap(topic.upper(), width=32)
        y = 120
        for line in title_lines[:2]:
            draw.text((CARD_W // 2, y), line,
                      font=self._font(58), fill=WHITE_PIL, anchor="mm")
            y += 72

        draw.rectangle([60, y + 10, CARD_W - 60, y + 14], fill=accent)
        y += 34

        for i, fact in enumerate(facts[:4]):
            colors = [GREEN_PIL, CYAN_PIL, YELLOW_PIL, ORANGE_PIL]
            draw.text((85, y + 5), "▶", font=self._font(22), fill=colors[i % 4])
            draw.text((115, y + 5), fact[:72], font=self._font(23), fill=WHITE_PIL)
            y += 48

        draw.rectangle([0, CARD_H - 52, CARD_W, CARD_H], fill=BG_CARD_PIL)
        draw.rectangle([0, CARD_H - 52, CARD_W, CARD_H - 49], fill=accent)
        draw.text((40, CARD_H - 26), "🧵 THREAD",
                  font=self._font(20), fill=accent, anchor="lm")
        tags = {
            "system_design": "#SystemDesign #HLD #SoftwareEngineering",
            "webdev":        "#WebDev #Backend #Programming",
            "career":        "#CareerAdvice #IndianDev",
        }.get(niche, "#Tech")
        draw.text((CARD_W - 40, CARD_H - 26), tags,
                  font=self._font(18), fill=GREY_PIL, anchor="rm")

        img.save(str(out_path), "PNG")
        logger.info("Text card saved: %s", out_path)
        return out_path

    def _font(self, size: int, bold: bool = True):
        from PIL import ImageFont
        candidates = [
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'Bold' if bold else ''}.ttf",
            f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        ]
        for fp in candidates:
            try:
                return ImageFont.truetype(fp, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()


CardGenerator = SmartCardGenerator

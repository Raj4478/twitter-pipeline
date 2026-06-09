"""
Smart Card Generator — uses `diagrams` library (Graphviz-based) for
professional architecture diagrams with real component icons.

Flow:
  1. Ask Gemini for structured graph JSON (nodes with types + edges)
  2. Map node types to real diagrams library components
  3. Render with Graphviz → PNG
  4. Composite: diagram + bottom info panel via Pillow
  5. Fallback to pure Pillow card if anything fails
"""

import logging
import textwrap
import uuid
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("tmp/cards")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CARD_W, CARD_H = 1280, 760

# PIL palette
BG_DARK_PIL  = (13,  17,  23)
BG_CARD_PIL  = (22,  27,  34)
BG_PANEL_PIL = (30,  35,  45)
BLUE_PIL     = (88,  166, 255)
GREEN_PIL    = (63,  185, 80)
YELLOW_PIL   = (255, 212, 0)
ORANGE_PIL   = (255, 127, 80)
WHITE_PIL    = (230, 237, 243)
GREY_PIL     = (110, 118, 129)
PURPLE_PIL   = (188, 140, 255)
CYAN_PIL     = (79,  201, 197)
MUTED_PIL    = (90,  110, 150)
RED_PIL      = (248, 81,  73)

# ── Gemini prompt for graph structure ─────────────────────────────────────────

GRAPH_SYSTEM = """You are a system design expert. Return ONLY valid JSON. No markdown, no explanation."""

GRAPH_PROMPT = '''Generate an architecture diagram for: "{topic}"

Map each component to one of these node_type values:
  server, kafka, rabbitmq, redis, postgresql, mysql, mongodb, nginx, 
  haproxy, zookeeper, prometheus, grafana, elasticsearch, user, internet,
  cdn, loadbalancer, apigateway, cache, queue, database, service

Return JSON:
{{
  "title": "Short diagram title",
  "direction": "LR",
  "clusters": [
    {{
      "name": "Cluster Name",
      "color": "#161b22",
      "border": "#58a6ff",
      "nodes": [
        {{"id": "A", "label": "Kafka\\nBroker", "node_type": "kafka"}},
        {{"id": "B", "label": "ZooKeeper", "node_type": "zookeeper"}}
      ]
    }}
  ],
  "standalone_nodes": [
    {{"id": "P", "label": "Producer\\nApp", "node_type": "server"}},
    {{"id": "DB", "label": "PostgreSQL", "node_type": "postgresql"}}
  ],
  "edges": [
    {{"from": "P", "to": "A", "label": "publish", "style": "solid"}},
    {{"from": "A", "to": "DB", "label": "persist", "style": "solid"}},
    {{"from": "B", "to": "A", "label": "coordinate", "style": "dashed"}}
  ]
}}

Rules:
- 5-10 nodes total (readable on mobile)
- Use real component names specific to {topic}
- Group related components in clusters
- direction: LR for pipelines, TB for layered architectures
- dashed edges for control/management flows'''


# ── Node type → diagrams class mapping ────────────────────────────────────────

def get_node_class(node_type: str):
    """Map node_type string to diagrams library class."""
    mapping = {
        # Queues & Messaging
        "kafka":       ("diagrams.onprem.queue",    "Kafka"),
        "rabbitmq":    ("diagrams.onprem.queue",    "RabbitMQ"),
        "queue":       ("diagrams.onprem.queue",    "Kafka"),
        # Databases
        "postgresql":  ("diagrams.onprem.database", "PostgreSQL"),
        "mysql":       ("diagrams.onprem.database", "MySQL"),
        "mongodb":     ("diagrams.onprem.database", "MongoDB"),
        "cassandra":   ("diagrams.onprem.database", "Cassandra"),
        "database":    ("diagrams.onprem.database", "PostgreSQL"),
        # In-memory / Cache
        "redis":       ("diagrams.onprem.inmemory", "Redis"),
        "memcached":   ("diagrams.onprem.inmemory", "Memcached"),
        "cache":       ("diagrams.onprem.inmemory", "Redis"),
        # Network
        "nginx":       ("diagrams.onprem.network",  "Nginx"),
        "haproxy":     ("diagrams.onprem.network",  "HAProxy"),
        "zookeeper":   ("diagrams.onprem.network",  "Zookeeper"),
        "internet":    ("diagrams.onprem.network",  "Internet"),
        "loadbalancer":("diagrams.onprem.network",  "HAProxy"),
        "apigateway":  ("diagrams.onprem.network",  "Kong"),
        "cdn":         ("diagrams.onprem.network",  "Nginx"),
        # Compute
        "server":      ("diagrams.onprem.compute",  "Server"),
        "service":     ("diagrams.onprem.compute",  "Server"),
        # Monitoring
        "prometheus":  ("diagrams.onprem.monitoring","Prometheus"),
        "grafana":     ("diagrams.onprem.monitoring","Grafana"),
        # Client
        "user":        ("diagrams.onprem.client",   "User"),
        "users":       ("diagrams.onprem.client",   "Users"),
        # Search
        "elasticsearch":("diagrams.onprem.search",  "Elasticsearch"),
    }
    mod_path, class_name = mapping.get(node_type.lower(), ("diagrams.onprem.compute", "Server"))
    import importlib
    mod = importlib.import_module(mod_path)
    return getattr(mod, class_name)


# ── Main generator ─────────────────────────────────────────────────────────────

class SmartCardGenerator:

    def __init__(self, settings=None):
        self.settings = settings

    def generate(self, topic: str, image_text: str, niche: str,
                 facts: list[str] = None) -> Path:
        card_id = uuid.uuid4().hex[:8]
        out_path = OUTPUT_DIR / f"card_{card_id}.png"

        logger.info("Generating card | niche=%s settings=%s", niche, bool(self.settings))

        if niche in ("system_design", "webdev") and self.settings:
            try:
                return self._generate_architecture_card(
                    topic, niche, facts or [], out_path
                )
            except Exception as e:
                import traceback
                logger.error("Architecture card FAILED:\n%s", traceback.format_exc())
                logger.warning("Falling back to Pillow card")

        return self._generate_pillow_card(topic, image_text, niche, facts or [], out_path)

    def _generate_architecture_card(self, topic: str, niche: str,
                                     facts: list[str], out_path: Path) -> Path:
        # 1. Get graph structure from Gemini
        graph = self._get_graph_data(topic, niche)
        logger.info("Graph: %d clusters, %d standalone, %d edges",
                    len(graph.get("clusters", [])),
                    len(graph.get("standalone_nodes", [])),
                    len(graph.get("edges", [])))

        # 2. Render diagram to temp PNG
        diagram_png = self._render_diagram(graph, topic)
        logger.info("Diagram rendered: %s", diagram_png)

        # 3. Composite with info panel
        self._composite(diagram_png, topic, niche, facts, out_path)
        logger.info("Architecture card saved: %s", out_path)
        return out_path

    def _get_graph_data(self, topic: str, niche: str) -> dict:
        prompt = GRAPH_PROMPT.format(topic=topic)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": GRAPH_SYSTEM}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 800,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(raw)

    def _render_diagram(self, graph: dict, topic: str) -> Path:
        from diagrams import Diagram, Cluster, Edge

        tmp_dir = Path(tempfile.mkdtemp())
        diagram_file = tmp_dir / "diagram"  # diagrams adds .png

        title = graph.get("title", topic).upper()
        direction = graph.get("direction", "LR")

        graph_attrs = {
            "fontsize": "22",
            "bgcolor": "#0d1117",
            "fontcolor": "#e6edf3",
            "fontname": "DejaVu Sans Mono Bold",
            "pad": "0.9",
            "splines": "curved",
            "nodesep": "0.9",
            "ranksep": "1.3",
            "dpi": "150",
            "labelloc": "t",
        }
        node_attrs = {
            "fontsize": "13",
            "fontcolor": "#e6edf3",
            "fontname": "DejaVu Sans Mono",
            "style": "filled",
            "fillcolor": "#161b22",
            "color": "#58a6ff",
            "penwidth": "2.5",
            "margin": "0.3",
        }
        edge_attrs = {
            "color": "#58a6ff",
            "fontcolor": "#8b949e",
            "fontsize": "11",
            "fontname": "DejaVu Sans Mono",
            "penwidth": "2",
        }

        # Build node registry
        node_registry = {}

        with Diagram(
            title,
            filename=str(diagram_file),
            outformat="png",
            show=False,
            direction=direction,
            graph_attr=graph_attrs,
            node_attr=node_attrs,
            edge_attr=edge_attrs,
        ):
            # Create standalone nodes
            for n in graph.get("standalone_nodes", []):
                NodeClass = get_node_class(n.get("node_type", "server"))
                node_registry[n["id"]] = NodeClass(n.get("label", n["id"]))

            # Create clustered nodes
            for cluster in graph.get("clusters", []):
                c_attrs = {
                    "bgcolor": cluster.get("color", "#161b22"),
                    "fontcolor": "#e6edf3",
                    "color": cluster.get("border", "#58a6ff"),
                    "fontname": "DejaVu Sans Mono Bold",
                    "penwidth": "2",
                    "margin": "20",
                }
                with Cluster(cluster.get("name", ""), graph_attr=c_attrs):
                    for n in cluster.get("nodes", []):
                        NodeClass = get_node_class(n.get("node_type", "server"))
                        node_registry[n["id"]] = NodeClass(n.get("label", n["id"]))

            # Draw edges
            for edge in graph.get("edges", []):
                src_id = edge.get("from")
                dst_id = edge.get("to")
                if src_id not in node_registry or dst_id not in node_registry:
                    continue

                style = edge.get("style", "solid")
                label = edge.get("label", "")
                color = "#8b949e" if style == "dashed" else "#58a6ff"

                edge_obj = Edge(
                    label=label,
                    color=color,
                    style=style,
                    fontcolor="#8b949e",
                    fontsize="11",
                )
                node_registry[src_id] >> edge_obj >> node_registry[dst_id]

        return Path(str(diagram_file) + ".png")

    def _composite(self, diagram_png: Path, topic: str, niche: str,
                   facts: list[str], out_path: Path):
        """Composite: diagram (top 74%) + styled info panel (bottom 26%)."""
        from PIL import Image, ImageDraw

        DIAGRAM_H = 565
        PANEL_H   = CARD_H - DIAGRAM_H   # 155px

        # ── Canvas with dot-grid background ───────────────────────────
        canvas = Image.new("RGB", (CARD_W, CARD_H), BG_DARK_PIL)
        draw   = ImageDraw.Draw(canvas)

        for x in range(0, CARD_W, 40):
            for y in range(0, DIAGRAM_H, 40):
                draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=(22, 32, 55))

        # ── Paste diagram ──────────────────────────────────────────────
        diagram = Image.open(diagram_png).convert("RGBA")
        bg_diag = Image.new("RGB", diagram.size, BG_DARK_PIL)
        bg_diag.paste(diagram, mask=diagram.split()[3])

        ratio = bg_diag.width / bg_diag.height
        if ratio > CARD_W / DIAGRAM_H:
            nw, nh = CARD_W, int(CARD_W / ratio)
        else:
            nh, nw = DIAGRAM_H, int(DIAGRAM_H * ratio)

        bg_diag = bg_diag.resize((nw, nh), Image.LANCZOS)
        xo = (CARD_W - nw) // 2
        yo = (DIAGRAM_H - nh) // 2
        canvas.paste(bg_diag, (xo, yo))

        # ── Gradient fade at bottom of diagram ────────────────────────
        grad = Image.new("RGBA", (CARD_W, 120), (0, 0, 0, 0))
        gd   = ImageDraw.Draw(grad)
        for i in range(120):
            alpha = int(255 * (i / 120) ** 2)
            gd.rectangle([0, i, CARD_W, i + 1], fill=(*BG_DARK_PIL, alpha))
        canvas.paste(Image.new("RGB", (CARD_W, 120), BG_DARK_PIL),
                     (0, DIAGRAM_H - 120), mask=grad.split()[3])

        # ── Glowing side accent bars ───────────────────────────────────
        accent = {
            "system_design": BLUE_PIL,
            "webdev":        GREEN_PIL,
            "career":        PURPLE_PIL,
        }.get(niche, BLUE_PIL)
        accent2 = PURPLE_PIL if niche == "system_design" else BLUE_PIL

        for i in range(5):
            a = int(180 * (1 - i / 5))
            draw.rectangle([i, 0, i + 1, DIAGRAM_H], fill=(*accent, a))
            draw.rectangle([CARD_W - i - 1, 0, CARD_W - i, DIAGRAM_H],
                           fill=(*accent2, a))

        # ── Corner glow blobs ──────────────────────────────────────────
        for cx, cy, col in [(0, 0, accent), (CARD_W, 0, accent2)]:
            for r, a in [(80, 12), (50, 20), (25, 30)]:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                             fill=(*col, a))

        # ── Info panel ─────────────────────────────────────────────────
        panel_y = DIAGRAM_H
        draw.rectangle([0, panel_y, CARD_W, CARD_H], fill=BG_CARD_PIL)

        # Glowing top border
        for i in range(3):
            a = int(255 * (1 - i / 3))
            draw.rectangle([0, panel_y + i, CARD_W, panel_y + i + 1],
                           fill=(*accent, a))

        # Topic title
        title = topic.upper()
        draw.text((CARD_W // 2, panel_y + 32), title,
                  font=self._font(28), fill=WHITE_PIL, anchor="mm")

        # Underline
        tw = min(len(title) * 17, CARD_W - 80)
        draw.rectangle(
            [CARD_W // 2 - tw // 2, panel_y + 50,
             CARD_W // 2 + tw // 2, panel_y + 52],
            fill=(*accent, 100)
        )

        # Fact chips
        chip_colors = [BLUE_PIL, CYAN_PIL, GREEN_PIL, ORANGE_PIL]
        chip_x, chip_y = 30, panel_y + 64
        for i, fact in enumerate(facts[:4]):
            fact_s = fact[:55].strip()
            fact_w = len(fact_s) * 11 + 32
            if chip_x + fact_w > CARD_W - 30:
                chip_x, chip_y = 30, chip_y + 40

            # Chip glow fill
            canvas.paste(
                Image.new("RGB", (fact_w, 30), chip_colors[i % 4]),
                (chip_x, chip_y),
                mask=Image.new("L", (fact_w, 30), 28)
            )
            draw.rounded_rectangle(
                [chip_x, chip_y, chip_x + fact_w, chip_y + 30],
                radius=6, outline=chip_colors[i % 4], width=1
            )
            draw.text((chip_x + 16, chip_y + 15), fact_s,
                      font=self._font(14),
                      fill=chip_colors[i % 4], anchor="lm")
            chip_x += fact_w + 12

        # ── Bottom branding bar ────────────────────────────────────────
        bar_y = CARD_H - 44
        draw.rectangle([0, bar_y, CARD_W, CARD_H], fill=(10, 14, 24))
        draw.rectangle([0, bar_y, CARD_W, bar_y + 1], fill=(*accent, 60))

        draw.text((30, bar_y + 22), "⚡ @byte_blueprint",
                  font=self._font(17), fill=accent, anchor="lm")

        niche_label = {
            "system_design": "SYSTEM DESIGN",
            "webdev":        "WEB DEV",
            "career":        "CAREER",
        }.get(niche, "TECH")
        draw.text((CARD_W // 2, bar_y + 22), niche_label,
                  font=self._font(16), fill=MUTED_PIL, anchor="mm")

        tags = {
            "system_design": "#SystemDesign  #HLD  #SoftwareEngineering",
            "webdev":        "#WebDev  #Backend  #Programming",
            "career":        "#CareerAdvice  #IndianDev",
        }.get(niche, "#Tech")
        draw.text((CARD_W - 30, bar_y + 22), tags,
                  font=self._font(14), fill=MUTED_PIL, anchor="rm")

        canvas.save(str(out_path), "PNG", quality=95)

    def _generate_pillow_card(self, topic: str, image_text: str, niche: str,
                               facts: list[str], out_path: Path) -> Path:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (CARD_W, CARD_H), BG_DARK_PIL)
        draw = ImageDraw.Draw(img)
        accent = {"system_design": BLUE_PIL, "webdev": GREEN_PIL,
                  "career": PURPLE_PIL}.get(niche, BLUE_PIL)

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
            draw.text((CARD_W // 2, y), line, font=self._font(58),
                      fill=WHITE_PIL, anchor="mm")
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
        draw.text((40, CARD_H - 26), "🧵 THREAD", font=self._font(20),
                  fill=accent, anchor="lm")
        tags = {"system_design": "#SystemDesign #HLD #SoftwareEngineering",
                "webdev": "#WebDev #Backend #Programming",
                "career": "#CareerAdvice #IndianDev"}.get(niche, "#Tech")
        draw.text((CARD_W - 40, CARD_H - 26), tags, font=self._font(18),
                  fill=GREY_PIL, anchor="rm")

        img.save(str(out_path), "PNG")
        logger.info("Pillow card saved: %s", out_path)
        return out_path

    def _font(self, size: int):
        from PIL import ImageFont
        for fp in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]:
            try:
                return ImageFont.truetype(fp, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()


CardGenerator = SmartCardGenerator

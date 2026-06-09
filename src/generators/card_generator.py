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

CARD_W, CARD_H = 1200, 720

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
        """Composite: diagram (top 75%) + info panel (bottom 25%)."""
        from PIL import Image, ImageDraw

        DIAGRAM_H = 540
        PANEL_H   = CARD_H - DIAGRAM_H  # 180px

        canvas = Image.new("RGB", (CARD_W, CARD_H), BG_DARK_PIL)
        draw = ImageDraw.Draw(canvas)

        # ── Diagram section ───────────────────────────────────────────
        diagram = Image.open(diagram_png).convert("RGBA")
        bg = Image.new("RGB", diagram.size, BG_DARK_PIL)
        bg.paste(diagram, mask=diagram.split()[3])

        # Scale to fit keeping aspect ratio
        ratio = bg.width / bg.height
        if ratio > CARD_W / DIAGRAM_H:
            new_w, new_h = CARD_W, int(CARD_W / ratio)
        else:
            new_h, new_w = DIAGRAM_H, int(DIAGRAM_H * ratio)

        bg = bg.resize((new_w, new_h), Image.LANCZOS)
        x_off = (CARD_W - new_w) // 2
        y_off = (DIAGRAM_H - new_h) // 2
        canvas.paste(bg, (x_off, y_off))

        # Gradient fade at bottom of diagram
        for i in range(80):
            alpha = int(255 * (i / 80) ** 1.5)
            draw.rectangle([0, DIAGRAM_H - 80 + i, CARD_W, DIAGRAM_H - 79 + i],
                           fill=(*BG_DARK_PIL, alpha))

        # ── Info panel ─────────────────────────────────────────────────
        panel_y = DIAGRAM_H
        draw.rectangle([0, panel_y, CARD_W, CARD_H], fill=BG_CARD_PIL)

        accent = {
            "system_design": BLUE_PIL,
            "webdev": GREEN_PIL,
            "career": PURPLE_PIL,
        }.get(niche, BLUE_PIL)

        # Top accent border
        draw.rectangle([0, panel_y, CARD_W, panel_y + 3], fill=accent)

        # Facts as inline chips
        chip_x = 30
        chip_y = panel_y + 18
        chip_colors = [GREEN_PIL, CYAN_PIL, YELLOW_PIL, ORANGE_PIL]
        for i, fact in enumerate(facts[:4]):
            fact_short = fact[:55].strip()
            text_w = len(fact_short) * 11 + 28

            if chip_x + text_w > CARD_W - 30:
                chip_x = 30
                chip_y += 38

            draw.rounded_rectangle(
                [chip_x, chip_y, chip_x + text_w, chip_y + 28],
                radius=5, fill=BG_PANEL_PIL,
                outline=chip_colors[i % 4], width=1,
            )
            draw.text((chip_x + 14, chip_y + 14), fact_short,
                      font=self._font(14),
                      fill=chip_colors[i % 4], anchor="lm")
            chip_x += text_w + 10

        # Bottom branding bar
        bar_y = CARD_H - 36
        draw.rectangle([0, bar_y, CARD_W, CARD_H], fill=BG_DARK_PIL)
        draw.text((30, bar_y + 18), "🧵 THREAD",
                  font=self._font(17), fill=accent, anchor="lm")
        tags = {
            "system_design": "#SystemDesign #HLD #SoftwareEngineering",
            "webdev": "#WebDev #Backend #Programming",
            "career": "#CareerAdvice #IndianDev",
        }.get(niche, "#Tech")
        draw.text((CARD_W - 30, bar_y + 18), tags,
                  font=self._font(15), fill=GREY_PIL, anchor="rm")

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

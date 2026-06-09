"""
Smart Card Generator — generates architecture diagrams using matplotlib + networkx.
No mmdc, no Puppeteer, no Chrome. Pure Python, works everywhere.

Flow:
  1. Ask Gemini for nodes/edges JSON describing the architecture
  2. Draw graph using networkx + matplotlib with dark theme
  3. Composite: diagram (top 68%) + title/facts panel (bottom 32%)

Output: 1200x675 PNG
"""

import logging
import textwrap
import uuid
import json
import subprocess
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("tmp/cards")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CARD_W, CARD_H = 1200, 675

# Dark theme palette
BG_DARK   = (13/255,  17/255,  23/255)
BG_CARD   = (22/255,  27/255,  34/255)
BG_PANEL  = (30/255,  35/255,  45/255)
BLUE      = (88/255,  166/255, 255/255)
GREEN     = (63/255,  185/255, 80/255)
YELLOW    = (255/255, 212/255, 0/255)
ORANGE    = (255/255, 127/255, 80/255)
WHITE     = (230/255, 237/255, 243/255)
GREY      = (110/255, 118/255, 129/255)
PURPLE    = (188/255, 140/255, 255/255)
RED       = (248/255, 81/255,  73/255)
CYAN      = (79/255,  201/255, 197/255)

# PIL versions (0-255)
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

GRAPH_SYSTEM = """You are a system design expert. Return ONLY valid JSON describing an architecture graph.
No markdown, no explanation, just raw JSON."""

GRAPH_PROMPT = """For the topic "{topic}", generate a directed architecture diagram.

Return JSON with this exact structure:
{{
  "nodes": [
    {{"id": "A", "label": "Producer\\nApp", "type": "client"}},
    {{"id": "B", "label": "Kafka\\nBroker", "type": "core"}},
    {{"id": "C", "label": "Consumer\\nService", "type": "service"}},
    {{"id": "D", "label": "PostgreSQL", "type": "storage"}}
  ],
  "edges": [
    {{"from": "A", "to": "B", "label": "publish"}},
    {{"from": "B", "to": "C", "label": "consume"}},
    {{"from": "C", "to": "D", "label": "persist"}}
  ],
  "layout": "LR"
}}

Node types: client, core, service, storage, cache, queue, gateway, external
Layout: LR (left-right) or TB (top-bottom)
Keep it 5-9 nodes max. Labels max 2 lines with \\n separator.
Make it specific to {topic} — use real component names."""


NODE_COLORS = {
    "client":   {"face": (30, 60, 100),  "edge": (88, 166, 255),  "text": (230, 237, 243)},
    "core":     {"face": (60, 30, 80),   "edge": (188, 140, 255), "text": (230, 237, 243)},
    "service":  {"face": (20, 70, 40),   "edge": (63, 185, 80),   "text": (230, 237, 243)},
    "storage":  {"face": (80, 50, 10),   "edge": (255, 212, 0),   "text": (230, 237, 243)},
    "cache":    {"face": (80, 30, 10),   "edge": (255, 127, 80),  "text": (230, 237, 243)},
    "queue":    {"face": (60, 30, 80),   "edge": (188, 140, 255), "text": (230, 237, 243)},
    "gateway":  {"face": (20, 60, 70),   "edge": (79, 201, 197),  "text": (230, 237, 243)},
    "external": {"face": (50, 50, 50),   "edge": (110, 118, 129), "text": (230, 237, 243)},
}


class SmartCardGenerator:

    def __init__(self, settings=None):
        self.settings = settings

    def generate(self, topic: str, image_text: str, niche: str,
                 facts: list[str] = None) -> Path:
        card_id = uuid.uuid4().hex[:8]
        out_path = OUTPUT_DIR / f"card_{card_id}.png"

        logger.info("Card path: niche=%s settings=%s", niche, bool(self.settings))

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
        # 1. Get graph data from Gemini
        graph_data = self._get_graph_data(topic, niche)
        logger.info("Graph: %d nodes, %d edges",
                    len(graph_data.get("nodes", [])),
                    len(graph_data.get("edges", [])))

        # 2. Draw diagram with matplotlib
        diagram_path = self._draw_diagram(graph_data, topic, out_path)
        logger.info("Architecture card saved: %s", diagram_path)
        return diagram_path

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
                "maxOutputTokens": 600,
                "responseMimeType": "application/json",
            },
        }
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            # Strip markdown fences if present
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(raw)

    def _draw_diagram(self, graph_data: dict, topic: str, out_path: Path) -> Path:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
        import numpy as np

        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        layout = graph_data.get("layout", "LR")

        if not nodes:
            raise ValueError("No nodes in graph data")

        # ── Compute layout positions ───────────────────────────────────
        positions = self._compute_positions(nodes, edges, layout)

        # ── Figure setup ───────────────────────────────────────────────
        fig_w, fig_h = 12, 4.5  # inches → 1200x450 at 100dpi
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        fig.patch.set_facecolor(BG_DARK)
        ax.set_facecolor(BG_DARK)
        ax.set_xlim(-0.5, fig_w - 0.5)
        ax.set_ylim(-0.5, fig_h - 0.5)
        ax.axis("off")

        # ── Draw edges first (behind nodes) ───────────────────────────
        for edge in edges:
            src = next((n for n in nodes if n["id"] == edge["from"]), None)
            dst = next((n for n in nodes if n["id"] == edge["to"]), None)
            if not src or not dst:
                continue

            x1, y1 = positions[src["id"]]
            x2, y2 = positions[dst["id"]]

            # Arrow
            ax.annotate(
                "", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(
                    arrowstyle="-|>",
                    color=(88/255, 166/255, 255/255),
                    lw=1.8,
                    mutation_scale=18,
                    connectionstyle="arc3,rad=0.08",
                )
            )

            # Edge label
            if edge.get("label"):
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                ax.text(mx, my + 0.15, edge["label"],
                        ha="center", va="bottom", fontsize=8,
                        color=(110/255, 118/255, 129/255),
                        fontfamily="monospace",
                        bbox=dict(boxstyle="round,pad=0.2",
                                  facecolor=BG_DARK, edgecolor="none", alpha=0.8))

        # ── Draw nodes ─────────────────────────────────────────────────
        NODE_W, NODE_H = 1.6, 0.7
        for node in nodes:
            x, y = positions[node["id"]]
            ntype = node.get("type", "service")
            colors = NODE_COLORS.get(ntype, NODE_COLORS["service"])

            face = tuple(c/255 for c in colors["face"])
            edge_c = tuple(c/255 for c in colors["edge"])
            text_c = tuple(c/255 for c in colors["text"])

            # Node box
            rect = FancyBboxPatch(
                (x - NODE_W/2, y - NODE_H/2), NODE_W, NODE_H,
                boxstyle="round,pad=0.05",
                facecolor=face, edgecolor=edge_c, linewidth=2,
                zorder=3
            )
            ax.add_patch(rect)

            # Node label
            label = node.get("label", node["id"])
            ax.text(x, y, label,
                    ha="center", va="center", fontsize=9.5,
                    color=text_c, fontfamily="monospace", fontweight="bold",
                    zorder=4, multialignment="center",
                    linespacing=1.3)

        # ── Title bar at top of diagram ────────────────────────────────
        ax.text(fig_w / 2, fig_h - 0.25,
                topic.upper(),
                ha="center", va="center", fontsize=13, fontweight="bold",
                color=WHITE, fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.3",
                          facecolor=BG_CARD, edgecolor=BLUE, linewidth=1.5))

        plt.tight_layout(pad=0)
        fig.savefig(str(out_path), dpi=100, bbox_inches="tight",
                    facecolor=BG_DARK, edgecolor="none")
        plt.close(fig)
        return out_path

    def _compute_positions(self, nodes: list, edges: list, layout: str) -> dict:
        """Simple layered layout — groups nodes into columns (LR) or rows (TB)."""
        n = len(nodes)
        if n == 0:
            return {}

        # Build adjacency for topological layering
        in_degree = {node["id"]: 0 for node in nodes}
        out_edges = {node["id"]: [] for node in nodes}
        for edge in edges:
            if edge["from"] in in_degree and edge["to"] in in_degree:
                in_degree[edge["to"]] += 1
                out_edges[edge["from"]].append(edge["to"])

        # BFS layering
        layers = {}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        if not queue:
            queue = [nodes[0]["id"]]
        for nid in queue:
            layers[nid] = 0

        visited = set(queue)
        while queue:
            next_q = []
            for nid in queue:
                for neighbor in out_edges[nid]:
                    if neighbor not in visited:
                        layers[neighbor] = layers[nid] + 1
                        visited.add(neighbor)
                        next_q.append(neighbor)
            queue = next_q

        # Assign remaining nodes
        for node in nodes:
            if node["id"] not in layers:
                layers[node["id"]] = 0

        max_layer = max(layers.values()) if layers else 0
        layer_nodes = {}
        for nid, layer in layers.items():
            layer_nodes.setdefault(layer, []).append(nid)

        # Convert layers to x,y positions
        positions = {}
        fig_w, fig_h = 12.0, 4.5

        if layout == "LR":
            x_step = (fig_w - 2.0) / max(max_layer, 1)
            for layer, nids in layer_nodes.items():
                x = 1.0 + layer * x_step
                y_step = (fig_h - 1.5) / max(len(nids), 1)
                for i, nid in enumerate(nids):
                    y = 0.75 + i * y_step + y_step / 2
                    positions[nid] = (x, y)
        else:  # TB
            y_step = (fig_h - 1.5) / max(max_layer, 1)
            for layer, nids in layer_nodes.items():
                y = fig_h - 1.0 - layer * y_step
                x_step = (fig_w - 2.0) / max(len(nids), 1)
                for i, nid in enumerate(nids):
                    x = 1.0 + i * x_step + x_step / 2
                    positions[nid] = (x, y)

        return positions

    def _generate_pillow_card(self, topic: str, image_text: str, niche: str,
                               facts: list[str], out_path: Path) -> Path:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (CARD_W, CARD_H), BG_DARK_PIL)
        draw = ImageDraw.Draw(img)

        accent = {
            "system_design": BLUE_PIL,
            "webdev": GREEN_PIL,
            "career": PURPLE_PIL,
        }.get(niche, BLUE_PIL)

        # Terminal bar
        draw.rectangle([0, 0, CARD_W, 48], fill=BG_CARD_PIL)
        for i, color in enumerate([RED_PIL, YELLOW_PIL, GREEN_PIL]):
            x = 20 + i * 22
            draw.ellipse([x, 16, x + 16, 32], fill=color)
        draw.text((72, 24), f"~/dev/{niche} — {topic[:45]}",
                  font=self._font(16), fill=GREY_PIL, anchor="lm")

        draw.rectangle([0, 48, 5, CARD_H - 48], fill=accent)

        title_lines = textwrap.wrap(topic.upper(), width=32)
        y = 110
        for line in title_lines[:2]:
            draw.text((CARD_W // 2, y), line,
                      font=self._font(58), fill=WHITE_PIL, anchor="mm")
            y += 72

        draw.rectangle([60, y + 10, CARD_W - 60, y + 14], fill=accent)
        y += 30

        for i, fact in enumerate(facts[:4]):
            colors = [GREEN_PIL, CYAN_PIL, YELLOW_PIL, ORANGE_PIL]
            draw.text((85, y + 5), "▶", font=self._font(22), fill=colors[i % 4])
            draw.text((115, y + 5), fact[:72], font=self._font(23), fill=WHITE_PIL)
            y += 44

        draw.rectangle([0, CARD_H - 52, CARD_W, CARD_H], fill=BG_CARD_PIL)
        draw.rectangle([0, CARD_H - 52, CARD_W, CARD_H - 49], fill=accent)
        draw.text((40, CARD_H - 26), "🧵 THREAD",
                  font=self._font(20), fill=accent, anchor="lm")
        tags = {
            "system_design": "#SystemDesign #HLD #SoftwareEngineering",
            "webdev": "#WebDev #Backend #Programming",
            "career": "#CareerAdvice #IndianDev",
        }.get(niche, "#Tech")
        draw.text((CARD_W - 40, CARD_H - 26), tags,
                  font=self._font(18), fill=GREY_PIL, anchor="rm")

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

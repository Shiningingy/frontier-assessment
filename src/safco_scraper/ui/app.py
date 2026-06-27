"""Gradio web UI: a chat panel wired to the ConductorAgent + a live catalog view.

The chat is the entry point — tell it to scrape any site or ask about the catalog.
The Catalog tab shows the current database (refreshable) plus a deterministic
summary. Launched via `safco ui`.
"""
from __future__ import annotations

import logging

from ..agents.conductor import ConductorAgent
from ..config import Settings
from ..llm.factory import build_llm_client
from ..tools.query import deterministic_summary, load_catalog
from ..tools.store import Store

INTRO = (
    "### 🦷 Safco Catalog Conductor\n"
    "Tell me what to scrape, or ask about the catalog. Examples:\n"
    "- *Crawl gloves and sutures from safcodental and show me the cheapest nitrile glove*\n"
    "- *Discover https://www.safcodental.com/catalog/gloves*\n"
    "- *What brands are in the catalog and what's the price range?*"
)


def _catalog_frame(store: Store):
    import pandas as pd

    rows = load_catalog(store)
    if not rows:
        return pd.DataFrame(columns=["name", "sku", "brand", "price", "availability"])
    return pd.DataFrame(rows)


def build_demo(settings: Settings, logger: logging.Logger):
    """Build the Gradio Blocks app (without launching a server)."""
    import gradio as gr

    conductor = ConductorAgent(build_llm_client(settings, logger), settings, logger)

    def respond(message, history):
        final, steps = conductor.run_turn(message, history or [])
        prefix = ("> " + "  \n> ".join(steps) + "\n\n") if steps else ""
        return prefix + final

    def refresh_catalog():
        store = Store(settings.db_path)
        return _catalog_frame(store), deterministic_summary(store)

    with gr.Blocks(title="Safco Catalog Conductor") as demo:
        gr.Markdown(INTRO)
        with gr.Tab("Chat"):
            gr.ChatInterface(fn=respond)
        with gr.Tab("Catalog"):
            refresh = gr.Button("Refresh catalog", variant="primary")
            table = gr.Dataframe(label="Stored products", wrap=True)
            summ = gr.JSON(label="Summary")
            refresh.click(refresh_catalog, outputs=[table, summ])
            demo.load(refresh_catalog, outputs=[table, summ])
    return demo


def launch(settings: Settings, logger: logging.Logger, host: str = "127.0.0.1",
           port: int = 7860, share: bool = False) -> None:
    # Silence a harmless third-party deprecation warning emitted from inside Gradio
    # (gradio/routes.py uses Starlette's renamed HTTP_422_* constant). Not our code,
    # no functional impact — just keeps the demo terminal clean.
    import warnings
    warnings.filterwarnings("ignore", message=r".*HTTP_422_UNPROCESSABLE_ENTITY.*")

    demo = build_demo(settings, logger)
    logger.info(f"Launching Gradio UI on http://{host}:{port}")
    demo.launch(server_name=host, server_port=port, share=share, inbrowser=True)

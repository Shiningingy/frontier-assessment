"""Render docs/presentation.html to a PDF using headless Chromium (Playwright).

Usage: python scripts/render_presentation.py
Requires: pip install -e .[browser] && playwright install chromium
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "presentation.html"
OUT = ROOT / "Frontier_Dental_POC_Presentation.pdf"


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(SRC.as_uri(), wait_until="networkidle")
        page.pdf(path=str(OUT), format="A4", print_background=True,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

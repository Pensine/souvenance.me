#!/usr/bin/env python3
"""Renders the site's share card: marketing/og/og.html → marketing/site/assets/og.png.

The card is an HTML page (same fonts and logo as the site) captured at
1200×630 by Chromium via Playwright. Usage: scripts/make_og.py [chromium_path]
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "marketing" / "og" / "og.html"
OUT = ROOT / "marketing" / "site" / "assets" / "og.png"

with sync_playwright() as p:
    browser = p.chromium.launch(**({"executable_path": sys.argv[1]} if len(sys.argv) > 1 else {}))
    page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
    page.goto(SRC.as_uri())
    # the site's fonts, with local file paths (fonts.css serves them from /assets/)
    css = (ROOT / "marketing" / "site" / "assets" / "fonts.css").read_text()
    page.add_style_tag(content=css.replace("url(/assets/", "url(" + (ROOT / "marketing" / "site" / "assets").as_uri() + "/"))
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT))
    browser.close()
print(f"{OUT.relative_to(ROOT)} {OUT.stat().st_size / 1024:.1f} KB")

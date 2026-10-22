"""Isolated, time-bounded Chromium rendering entry point."""

import sys
from playwright.sync_api import sync_playwright


def main():
    html = sys.stdin.buffer.read(32 * 1024 * 1024 + 1)
    if len(html) > 32 * 1024 * 1024:
        raise SystemExit(2)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(java_script_enabled=False)
        context.route("**/*", lambda route: route.abort())
        page = context.new_page()
        page.set_content(html.decode(), wait_until="load", timeout=30000)
        result = page.pdf(format="A4", print_background=True)
        browser.close()
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()

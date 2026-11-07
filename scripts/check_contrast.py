"""Check the text/background pairs used by the app against WCAG AA."""


def luminance(color):
    values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))


pairs = [
    ("body", "#24332d", "#f5f6f2"),
    ("muted", "#59675f", "#ffffff"),
    ("library", "#566559", "#e9eee7"),
    ("project metadata", "#5c6b60", "#e9eee7"),
    ("primary", "#ffffff", "#245c48"),
    ("timestamp", "#245c48", "#ffffff"),
    ("review", "#78491a", "#f6edde"),
    ("error", "#8b3022", "#fff0ec"),
    ("footer", "#5e6d60", "#f5f6f2"),
    ("source label", "#596c60", "#f5f6f2"),
    ("domain chip", "#24332d", "#e9eee7"),
    ("unverified badge", "#78491a", "#f6edde"),
    ("not-tutorial heading", "#704518", "#faf0df"),
    ("not-tutorial body", "#24332d", "#faf0df"),
    ("not-tutorial muted", "#5b4a38", "#faf0df"),
]
for name, fg, bg in pairs:
    high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
    ratio = (high + 0.05) / (low + 0.05)
    print(f"{name}: {ratio:.2f}:1")
    assert ratio >= 4.5, name

"""Design tokens and the application stylesheet.

One coherent palette/typography scale used everywhere, rather than colors
and sizes scattered through widget code -- see project rule "use a
coherent design system." Built around a near-black surface with a single
cyan-violet accent, inspired by the restrained, high-contrast look of
modern professional creative/ML tools, without copying any specific
product's branding.
"""

from __future__ import annotations


class Tokens:
    # Surfaces
    bg_base = "#0b0d12"
    bg_elevated = "#12151c"
    bg_card = "#171b24"
    bg_hover = "#1f2430"
    bg_pressed = "#252b3a"
    border = "#262b38"
    border_subtle = "#1c202a"

    # Text
    text_primary = "#eef1f7"
    text_secondary = "#9aa3b5"
    text_tertiary = "#5f6779"

    # Accent
    accent = "#5ec8ff"
    accent_strong = "#7ad9ff"
    accent_soft = "#274a5e"
    violet = "#a78bfa"

    # Semantic
    success = "#4ade80"
    warning = "#fbbf24"
    danger = "#f87171"

    # Type scale
    font_family = "'Inter', 'Segoe UI', 'SF Pro Display', -apple-system, sans-serif"
    size_xs = 11
    size_sm = 12
    size_md = 13
    size_lg = 15
    size_xl = 18
    size_xxl = 24

    radius_sm = 6
    radius_md = 10
    radius_lg = 14


def build_stylesheet() -> str:
    t = Tokens
    return f"""
    * {{
        font-family: {t.font_family};
        color: {t.text_primary};
        outline: none;
    }}

    QMainWindow, QDialog {{
        background-color: {t.bg_base};
    }}

    QWidget#RootSurface {{
        background-color: {t.bg_base};
    }}

    QWidget#Card {{
        background-color: {t.bg_card};
        border: 1px solid {t.border};
        border-radius: {t.radius_lg}px;
    }}

    QLabel {{
        background: transparent;
    }}

    QLabel#SectionTitle {{
        color: {t.text_primary};
        font-size: {t.size_lg}px;
        font-weight: 600;
    }}

    QLabel#Caption {{
        color: {t.text_secondary};
        font-size: {t.size_sm}px;
    }}

    QLabel#Micro {{
        color: {t.text_tertiary};
        font-size: {t.size_xs}px;
    }}

    QPushButton {{
        background-color: {t.bg_elevated};
        border: 1px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 7px 14px;
        font-size: {t.size_md}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {t.bg_hover};
        border-color: {t.accent_soft};
    }}
    QPushButton:pressed {{
        background-color: {t.bg_pressed};
    }}
    QPushButton:disabled {{
        color: {t.text_tertiary};
    }}

    QPushButton#PrimaryButton {{
        background-color: {t.accent};
        color: #06131c;
        border: none;
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: {t.accent_strong};
    }}

    QPushButton#IconButton {{
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: {t.radius_sm}px;
        padding: 6px;
    }}
    QPushButton#IconButton:hover {{
        background-color: {t.bg_hover};
        border-color: {t.border};
    }}
    QPushButton#IconButton:checked {{
        background-color: {t.accent_soft};
        border-color: {t.accent};
    }}

    QTabWidget::pane {{
        border: 1px solid {t.border};
        border-radius: {t.radius_md}px;
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {t.text_secondary};
        padding: 8px 14px;
        margin-right: 4px;
        border-top-left-radius: {t.radius_sm}px;
        border-top-right-radius: {t.radius_sm}px;
        font-size: {t.size_sm}px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        color: {t.text_primary};
        background: {t.bg_card};
        border: 1px solid {t.border};
        border-bottom: none;
    }}
    QTabBar::tab:hover:!selected {{
        color: {t.text_primary};
    }}

    QSlider::groove:horizontal {{
        height: 4px;
        background: {t.border};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {t.accent};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -6px 0;
        background: {t.text_primary};
        border-radius: 7px;
    }}

    QComboBox {{
        background-color: {t.bg_elevated};
        border: 1px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 6px 10px;
        font-size: {t.size_sm}px;
    }}
    QComboBox:hover {{
        border-color: {t.accent_soft};
    }}
    QComboBox QAbstractItemView {{
        background-color: {t.bg_elevated};
        border: 1px solid {t.border};
        selection-background-color: {t.accent_soft};
        outline: none;
    }}

    QCheckBox {{
        font-size: {t.size_sm}px;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {t.border};
        background: {t.bg_elevated};
    }}
    QCheckBox::indicator:checked {{
        background: {t.accent};
        border-color: {t.accent};
    }}

    QTableWidget {{
        background-color: {t.bg_card};
        border: 1px solid {t.border};
        border-radius: {t.radius_md}px;
        gridline-color: {t.border_subtle};
        font-size: {t.size_sm}px;
        selection-background-color: {t.accent_soft};
    }}
    QHeaderView::section {{
        background-color: {t.bg_elevated};
        color: {t.text_secondary};
        border: none;
        border-bottom: 1px solid {t.border};
        padding: 6px 8px;
        font-size: {t.size_xs}px;
        font-weight: 600;
        text-transform: uppercase;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.border};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.text_tertiary};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QListWidget {{
        background-color: {t.bg_card};
        border: 1px solid {t.border};
        border-radius: {t.radius_md}px;
        font-size: {t.size_sm}px;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: {t.radius_sm}px;
    }}
    QListWidget::item:selected {{
        background-color: {t.accent_soft};
    }}

    QSpinBox, QDoubleSpinBox {{
        background-color: {t.bg_elevated};
        border: 1px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 4px 8px;
        font-size: {t.size_sm}px;
    }}

    QLineEdit {{
        background-color: {t.bg_elevated};
        border: 1px solid {t.border};
        border-radius: {t.radius_sm}px;
        padding: 7px 10px;
        font-size: {t.size_sm}px;
        color: {t.text_primary};
        selection-background-color: {t.accent_soft};
    }}
    QLineEdit:focus {{
        border-color: {t.accent};
    }}
    QLineEdit:disabled {{
        color: {t.text_tertiary};
    }}

    QProgressBar {{
        background-color: {t.bg_elevated};
        border: none;
        border-radius: 3px;
    }}
    QProgressBar::chunk {{
        background-color: {t.accent};
        border-radius: 3px;
    }}
    """

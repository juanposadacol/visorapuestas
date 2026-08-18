"""Estilo visual del panel (requisito 17).

Tema oscuro compacto, pensado para vivir encima del navegador sin estorbar.
La jerarquia visual es la que pide el requisito: "faltan para perder" y
"ritmo necesario para perder" son los datos mas grandes de la pantalla.
"""

from __future__ import annotations

COLOR_BG = "#11151c"
COLOR_PANEL = "#1a1f29"
COLOR_PANEL_ALT = "#212836"
COLOR_TEXT = "#e6ebf2"
COLOR_MUTED = "#8b97a8"
COLOR_ACCENT = "#3fa7ff"
COLOR_OK = "#3ddc84"
COLOR_WARN = "#ffbf3f"
COLOR_DANGER = "#ff5c5c"
COLOR_BORDER = "#2b3444"

STYLESHEET = f"""
QWidget {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
    font-family: "Segoe UI", "Inter", "DejaVu Sans", sans-serif;
    font-size: 12px;
}}
QFrame#card {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
}}
QFrame#cardHighlight {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_ACCENT};
    border-radius: 8px;
}}
QLabel#sectionTitle {{
    color: {COLOR_MUTED};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#teamName {{ font-size: 15px; font-weight: 600; }}
QLabel#teamScore {{ font-size: 22px; font-weight: 700; }}
QLabel#bigValue {{ font-size: 34px; font-weight: 800; }}
QLabel#hugeValue {{ font-size: 44px; font-weight: 800; color: {COLOR_WARN}; }}
QLabel#paceValue {{ font-size: 26px; font-weight: 700; color: {COLOR_ACCENT}; }}
QLabel#metricValue {{ font-size: 15px; font-weight: 600; }}
QLabel#metricLabel {{ color: {COLOR_MUTED}; font-size: 11px; }}
QLabel#betLine {{ font-size: 18px; font-weight: 700; color: {COLOR_OK}; }}
QLabel#danger {{ color: {COLOR_DANGER}; font-weight: 700; }}
QLabel#status {{ color: {COLOR_MUTED}; font-size: 11px; }}

QPushButton {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {COLOR_ACCENT}; }}
QPushButton:disabled {{ color: {COLOR_MUTED}; border-color: {COLOR_BORDER}; }}
QPushButton#primary {{ background-color: {COLOR_ACCENT}; color: #06101c; border: none; }}
QPushButton#danger {{ background-color: {COLOR_DANGER}; color: #1a0000; border: none; }}

QTableWidget {{
    background-color: {COLOR_PANEL};
    gridline-color: {COLOR_BORDER};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: #06101c;
}}
QHeaderView::section {{
    background-color: {COLOR_PANEL_ALT};
    color: {COLOR_MUTED};
    border: none;
    padding: 4px;
    font-size: 10px;
    font-weight: 600;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background-color: {COLOR_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 5px;
    padding: 4px 6px;
}}
QGroupBox {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    color: {COLOR_MUTED};
    font-size: 10px;
    font-weight: 700;
}}
QTabBar::tab {{
    background: {COLOR_PANEL};
    padding: 6px 14px;
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{ background: {COLOR_PANEL_ALT}; color: {COLOR_ACCENT}; }}
QTabWidget::pane {{ border: 1px solid {COLOR_BORDER}; border-radius: 6px; }}
"""

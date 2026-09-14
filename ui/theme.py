"""Thème (QSS) de l'application — sombre, moderne, accent teal/bleu."""

# Palette
BG = "#0d1117"          # fond général
SURFACE = "#161b22"     # panneaux / cartes
SURFACE_2 = "#1c2230"   # champs
BORDER = "#2a3038"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#1f6feb"
ACCENT_HOVER = "#388bfd"
GREEN = "#2ea043"
GREEN_HOVER = "#3fb950"
RED = "#da3633"
RED_HOVER = "#f85149"
AMBER = "#d29922"

STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 11pt;
    color: {TEXT};
}}

QMainWindow, QWidget#root {{
    background: {BG};
}}

/* ----- Barre latérale ----- */
QWidget#sidebar {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}

QLabel#brand {{
    font-size: 16pt;
    font-weight: 800;
    color: {TEXT};
    padding: 4px 2px;
}}
QLabel#brandSub {{
    color: {MUTED};
    font-size: 9pt;
}}
QLabel#sectionLabel {{
    color: {MUTED};
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 10px 12px 2px;
}}

QListWidget#nav {{
    background: transparent;
    border: none;
    outline: 0;
}}
QListWidget#nav::item {{
    padding: 10px 12px;
    margin: 2px 0;
    border-radius: 8px;
    color: {MUTED};
    font-size: 10.5pt;
}}
QListWidget#nav::item:hover {{
    background: {SURFACE_2};
    color: {TEXT};
}}
QListWidget#nav::item:selected {{
    background: {ACCENT};
    color: white;
    font-weight: 600;
}}

/* ----- Pastille d'état de connexion ----- */
QLabel#statusPill {{
    border-radius: 11px;
    padding: 6px 12px;
    font-size: 9.5pt;
    font-weight: 600;
}}

/* ----- Titres de page ----- */
QLabel#pageTitle {{
    font-size: 20pt;
    font-weight: 800;
}}
QLabel#pageSubtitle {{
    color: {MUTED};
    font-size: 10.5pt;
}}
QLabel#groupTitle {{
    font-size: 20pt;
    font-weight: 800;
}}
QLabel#groupSubtitle {{
    color: {MUTED};
    font-size: 10.5pt;
    padding-bottom: 2px;
}}
QLabel#subtleHint {{
    color: {MUTED};
    font-size: 9pt;
}}
QLabel#updateStatus {{
    color: {ACCENT_HOVER};
    font-size: 9.5pt;
    font-weight: 600;
}}

/* ----- Panneaux & cartes ----- */
QFrame#panel, QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#cardTitle {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#cardValue {{ font-size: 16pt; font-weight: 800; }}

/* ----- Boutons ----- */
QPushButton {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 14px;
    color: {TEXT};
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BG}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}

QPushButton#primary {{ background: {ACCENT}; border: none; color: white; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}

QPushButton#success {{ background: {GREEN}; border: none; color: white; }}
QPushButton#success:hover {{ background: {GREEN_HOVER}; }}

QPushButton#danger {{ background: {RED}; border: none; color: white; }}
QPushButton#danger:hover {{ background: {RED_HOVER}; }}

/* ----- Champs ----- */
QLineEdit, QComboBox, QSpinBox {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit::placeholder {{ color: {MUTED}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    outline: 0;
}}

/* ----- Listes ----- */
QListWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{ padding: 9px 8px; border-radius: 7px; }}
QListWidget::item:hover {{ background: {SURFACE_2}; }}
QListWidget::item:selected {{ background: {ACCENT}; color: white; }}

/* ----- Zones de texte / console ----- */
QTextEdit, QPlainTextEdit {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {TEXT};
}}

/* ----- Onglets ----- */
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; top: -1px; }}
QTabWidget#sectionTabs::pane {{
    background: {BG};
    border-color: transparent;
}}
QTabBar::tab {{
    background: {SURFACE_2};
    color: {MUTED};
    padding: 9px 16px;
    border-radius: 7px;
    margin: 4px 3px 8px 0;
}}
QTabBar::tab:selected {{ background: {ACCENT}; color: white; }}
QTabBar::tab:hover {{ color: {TEXT}; background: {BORDER}; }}

/* ----- Barre de statut (toasts) ----- */
QLabel#toast {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 14px;
    color: {MUTED};
}}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid {BORDER};
    background: {SURFACE_2};
}}
QCheckBox::indicator:checked {{ background: {GREEN}; border-color: {GREEN}; }}

/* ----- Scrollbars ----- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}
"""

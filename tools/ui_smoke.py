"""Offline UI navigation and rendering without reading user credentials."""

import argparse
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtTest import QTest
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication
from managers.config_manager import DEFAULTS
from ui.dashboard import Dashboard, NAV
from ui.mission_dialog import MissionImportDialog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('build/ui-audit'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = {**DEFAULTS, 'auto_refresh': False, 'github_repository': ''}
    app = QApplication.instance() or QApplication([])
    # The offscreen Qt plugin on Windows does not discover system fonts.
    font_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisym.ttf', 'seguiemj.ttf'):
        if (font_dir / name).is_file():
            QFontDatabase.addApplicationFont(str(font_dir / name))
    with patch('ui.dashboard.ConfigManager.load', side_effect=lambda: dict(config)), \
            patch('ui.dashboard.profiles.load_profiles', return_value={}), \
            patch.object(Dashboard, '_auto_check_for_updates'):
        window = Dashboard()
        window.resize(1280, 860)
        window.show()
        QTest.qWait(100)
        window.grab().save(str(args.output / 'accueil.png'))
        for i, (_, builder) in enumerate(NAV):
            window.nav.setCurrentRow(i)
            app.processEvents()
            assert window.pages.currentIndex() == i, builder
        for builder in window._tab_targets:
            window._nav_to(builder)
            app.processEvents()
            assert window._active_builder(window.nav.currentRow()) == builder, builder
        window._nav_to('build_diagnostics_page')
        window.grab().save(str(args.output / 'diagnostic.png'))
        window.resize(1040, 680)
        window._nav_to('build_dashboard_page')
        app.processEvents()
        window.grab().save(str(args.output / 'accueil-compact.png'))
        dialog = MissionImportDialog(config, window)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(args.output / 'import-mission.png'))
        dialog.reject()
        window.close()
        app.processEvents()
        assert not window.workers
    print('UI_SMOKE_OK navigation, 16 destinations, compact layout, mission dialog')


if __name__ == '__main__':
    main()

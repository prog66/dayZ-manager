import os
import subprocess
import sys
from pathlib import Path


def _use_project_python():
    """Relance le mode source avec l'environnement verrouillé du projet."""
    if getattr(sys, "frozen", False) or sys.platform != "win32":
        return
    root = Path(__file__).resolve().parent
    expected = (root / ".venv" / "Scripts" / "python.exe").resolve()
    current = Path(sys.executable).resolve()
    if expected.is_file() and current != expected:
        code = subprocess.call(
            [str(expected), str(Path(__file__).resolve()), *sys.argv[1:]],
            cwd=str(root),
        )
        raise SystemExit(code)


def _prepare_bundled_qt():
    """Rend les DLL Qt embarquées prioritaires dans l'exécutable Windows."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", "")
    if not meipass:
        return
    qt_bin = Path(meipass) / "PyQt6" / "Qt6" / "bin"
    if not qt_bin.is_dir():
        return
    qt_bin_text = str(qt_bin.resolve())
    current_path = os.environ.get("PATH", "")
    if not current_path.startswith(qt_bin_text + os.pathsep):
        os.environ["PATH"] = qt_bin_text + os.pathsep + current_path
    try:
        os.add_dll_directory(qt_bin_text)
    except (AttributeError, OSError):
        # Les anciennes versions de Windows/Python n'exposent pas toujours
        # add_dll_directory ; le PATH reste alors le filet de sécurité.
        pass


_use_project_python()
_prepare_bundled_qt()

from PyQt6.QtWidgets import QApplication

from ui.dashboard import Dashboard


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DayZ Manager")

    window = Dashboard()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

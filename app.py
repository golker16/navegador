import sys, os, time, subprocess
from pathlib import Path
from configparser import ConfigParser

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QLineEdit, QStackedWidget, QToolBar, QMessageBox, QSplitter
)

APP_NAME = "Python Projects Launcher - Embedded"
IS_WINDOWS = sys.platform.startswith("win")


# ---------- Utilidades de rutas (PyInstaller-friendly) ----------
def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent

APP_DIR = get_app_dir()
ASSETS_DIR = APP_DIR / "assets"
INI_PATH = APP_DIR / "projects.ini"


# ---------- Modelo ----------
class Project:
    def __init__(self, title: str, desc: str, exe: str, args: str):
        self.title = title
        self.desc = desc
        self.exe = exe
        self.args = args or ""


# ---------- Embebido de aplicaciones (solo Windows) ----------
if IS_WINDOWS:
    import win32gui, win32con, win32process

    def find_main_window_for_pid(pid: int, timeout_s: float = 5.0):
        end = time.time() + timeout_s
        found_hwnd = None

        def callback(hwnd, _):
            nonlocal found_hwnd
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, wpid = win32process.GetWindowThreadProcessId(hwnd)
            if wpid == pid:
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                if style & win32con.WS_OVERLAPPEDWINDOW or style & win32con.WS_CAPTION:
                    found_hwnd = hwnd
                    return False
            return True

        while time.time() < end and not found_hwnd:
            win32gui.EnumWindows(callback, None)
            if found_hwnd:
                break
            time.sleep(0.1)
        return found_hwnd

class EmbeddedAppWidget(QWidget):
    """Lanza un .exe y embece su ventana dentro de este widget (Windows)."""
    def __init__(self, exe_path: str, args: str):
        super().__init__()
        self.setObjectName("EmbeddedAppWidget")
        self.exe_path = exe_path
        self.args = args or ""
        self.proc = None
        self.hwnd = None
        self.setMinimumSize(QSize(300, 200))

        lay = QVBoxLayout(self)
        self.info = QLabel("Cargando aplicación…")
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        if not IS_WINDOWS:
            self.info.setText("Embedding solo disponible en Windows.\nSe abrirá externo.")
            self.launch_external()
            return

        self.launch_and_embed()

    def launch_external(self):
        try:
            cmd = [self.exe_path] + ([a for a in self.args.split(" ") if a] if self.args else [])
            subprocess.Popen(cmd, shell=False, cwd=os.path.dirname(self.exe_path) or None)
            self.info.setText("Aplicación abierta externamente.")
        except Exception as e:
            self.info.setText(f"Error lanzando app externa:\n{e}")

    def launch_and_embed(self):
        if not os.path.isfile(self.exe_path):
            self.info.setText(f"No se encontró el ejecutable:\n{self.exe_path}")
            return
        try:
            cmd = [self.exe_path] + ([a for a in self.args.split(" ") if a] if self.args else [])
            self.proc = subprocess.Popen(cmd, shell=False, cwd=os.path.dirname(self.exe_path) or None)
        except Exception as e:
            self.info.setText(f"No se pudo lanzar el proceso:\n{e}")
            return

        def try_embed():
            if not IS_WINDOWS or not self.proc:
                return
            hwnd = find_main_window_for_pid(self.proc.pid, timeout_s=0.1)
            if hwnd:
                self.hwnd = hwnd
                try:
                    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                    style = style & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME |
                                      win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX | win32con.WS_SYSMENU)
                    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
                    win32gui.SetParent(hwnd, int(self.winId()))
                    self._resize_embedded()
                    self.info.setVisible(False)
                    timer.stop()
                except Exception as e:
                    self.info.setText(f"No se pudo embeber la ventana:\n{e}")

        timer = QTimer(self)
        timer.timeout.connect(try_embed)
        timer.start(100)

    def _resize_embedded(self):
        if IS_WINDOWS and self.hwnd:
            w = max(1, self.width())
            h = max(1, self.height())
            import win32gui  # seguro en Windows
            win32gui.MoveWindow(self.hwnd, 0, 0, w, h, True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if IS_WINDOWS and self.hwnd:
            self._resize_embedded()

    def closeEvent(self, e):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                for _ in range(20):
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if self.proc.poll() is None:
                    self.proc.kill()
        except Exception:
            pass
        super().closeEvent(e)


# ---------- UI: Home y ProjectPage ----------
class HomePage(QWidget):
    def __init__(self, projects: list[Project], on_open, header_title: str = "Accesos directos"):
        super().__init__()
        self.on_open = on_open
        self.all_projects = projects
        self.header_title = header_title or "Accesos directos"

        layout = QVBoxLayout(self)

        # Encabezado configurable
        header = QLabel(f"<h2>{self.header_title}</h2>")
        header.setTextFormat(Qt.RichText)
        layout.addWidget(header)

        # Buscador en tiempo real
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por título o descripción…")
        self.search.textChanged.connect(self._apply_filter)
        search_row.addWidget(QLabel("Buscar:"))
        search_row.addWidget(self.search)
        layout.addLayout(search_row)

        # Lista de proyectos (doble click para abrir)
        self.listw = QListWidget()
        self.listw.itemDoubleClicked.connect(self._open_selected)
        layout.addWidget(self.listw)

        self._populate(self.all_projects)

    def _populate(self, projects: list[Project]):
        self.listw.clear()
        for p in projects:
            item = QListWidgetItem(f"{p.title}\n{p.desc}")
            item.setData(Qt.UserRole, p)
            item.setToolTip((p.title or "") + (" — " if p.title and p.desc else "") + (p.desc or ""))
            self.listw.addItem(item)

    def _apply_filter(self, text: str):
        q = (text or "").strip().lower()
        if not q:
            self._populate(self.all_projects)
            return
        filtered = []
        for p in self.all_projects:
            haystack = f"{p.title} {p.desc}".lower()
            if q in haystack:
                filtered.append(p)
        self._populate(filtered)

    def _open_selected(self):
        item = self.listw.currentItem()
        if not item:
            return
        p: Project = item.data(Qt.UserRole)
        self.on_open(p)


class ProjectPage(QWidget):
    def __init__(self, project: Project):
        super().__init__()
        self.project = project
        layout = QVBoxLayout(self)

        # Solo título y descripción (sin ruta del exe)
        title = QLabel(f"<h2>{project.title}</h2>")
        title.setTextFormat(Qt.RichText)
        subtitle = QLabel(project.desc or "")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Contenedor para embeber la app
        self.splitter = QSplitter(Qt.Vertical)
        self.embed = EmbeddedAppWidget(project.exe, project.args)
        self.splitter.addWidget(self.embed)
        layout.addWidget(self.splitter)


# ---------- Ventana principal ----------
class MainWindow(QWidget):
    def __init__(self, projects: list[Project], header_title: str):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1050, 700)

        # Icono
        ico_path = ASSETS_DIR / "app.ico"
        png_path = ASSETS_DIR / "app.png"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))
        elif png_path.exists():
            self.setWindowIcon(QIcon(str(png_path)))

        self.back_stack: list[int] = []
        self.forward_stack: list[int] = []

        root = QVBoxLayout(self)

        # Toolbar navegación (sin texto/botón a la derecha)
        toolbar = QToolBar()
        self.act_back = QAction("← Atrás", self)
        self.act_forward = QAction("Adelante →", self)
        self.act_back.triggered.connect(self.go_back)
        self.act_forward.triggered.connect(self.go_forward)
        toolbar.addAction(self.act_back)
        toolbar.addAction(self.act_forward)
        root.addWidget(toolbar)

        # Stack de páginas
        self.stack = QStackedWidget()
        self.home = HomePage(projects, on_open=self.open_project, header_title=header_title)
        self.stack.addWidget(self.home)
        root.addWidget(self.stack)

        # Footer
        footer = QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(Qt.AlignCenter)
        root.addWidget(footer)

        self._update_nav_buttons()

    def open_project(self, project: Project):
        page = ProjectPage(project)
        self.stack.addWidget(page)
        self.back_stack.append(self.stack.currentIndex())
        self.stack.setCurrentWidget(page)
        self.forward_stack.clear()
        self._update_nav_buttons()

    def go_back(self):
        if not self.back_stack:
            return
        current = self.stack.currentIndex()
        prev = self.back_stack.pop()
        # cerrar página actual (para matar el exe embebido)
        widget = self.stack.widget(current)
        self.stack.removeWidget(widget)
        widget.deleteLater()
        self.stack.setCurrentIndex(prev)
        self._update_nav_buttons()

    def go_forward(self):
        # Mantengo esqueleto por si más adelante guardamos páginas futuras.
        pass

    def _update_nav_buttons(self):
        self.act_back.setEnabled(bool(self.back_stack))
        self.act_forward.setEnabled(False)  # no guardamos pila hacia adelante por ahora


# ---------- Config / Autogeneración ----------
def ensure_projects_ini(ini_path: Path) -> None:
    if ini_path.exists():
        return
    # ejemplos seguros en Windows
    notepad = r"C:\Windows\System32\notepad.exe"
    calc = r"C:\Windows\System32\calc.exe"
    mspaint = r"C:\Windows\System32\mspaint.exe"

    example_ini = f"""[General]
header_title=Accesos directos

[Proyecto1]
title=Bloc de notas (ejemplo)
desc=Ejemplo de app Win32 sencilla embebida.
exe={notepad}
args=

[Proyecto2]
title=Calculadora (ejemplo)
desc=Según versión puede abrir externo.
exe={calc}
args=

[Proyecto3]
title=Paint (ejemplo)
desc=Otro ejemplo Win32 clásico.
exe={mspaint}
args=
"""
    ini_path.write_text(example_ini, encoding="utf-8")


def load_projects_from_ini(ini_path: Path):
    cfg = ConfigParser()
    if not ini_path.exists():
        raise FileNotFoundError(f"No se encontró {ini_path.name}.")
    cfg.read(ini_path, encoding="utf-8")

    header_title = cfg.get("General", "header_title", fallback="Accesos directos")

    projects = []
    for section in cfg.sections():
        if section == "General":
            continue
        title = cfg.get(section, "title", fallback=section)
        desc = cfg.get(section, "desc", fallback="")
        exe = cfg.get(section, "exe", fallback="")
        args = cfg.get(section, "args", fallback="")
        if not exe:
            continue
        projects.append(Project(title, desc, exe, args))
    return header_title, projects


def ensure_dark_theme(app: QApplication):
    try:
        import qdarkstyle
        try:
            app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))
        except TypeError:
            app.setStyleSheet(qdarkstyle.load_stylesheet())
    except Exception:
        pass


# ---------- main ----------
def main():
    app = QApplication(sys.argv)
    ensure_dark_theme(app)

    ensure_projects_ini(INI_PATH)

    try:
        header_title, projects = load_projects_from_ini(INI_PATH)
        if not projects:
            raise RuntimeError("projects.ini no contiene proyectos válidos (faltan 'exe=').")
    except Exception as e:
        QMessageBox.critical(None, "Error", f"No se pudo cargar {INI_PATH.name}:\n{e}")
        return 1

    w = MainWindow(projects, header_title=header_title)
    w.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())





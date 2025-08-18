import sys, os, subprocess, shutil
from pathlib import Path
from configparser import ConfigParser

from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QStackedWidget, QFileSystemModel, QTreeView, QToolBar,
    QMessageBox, QSplitter
)

APP_NAME = "Python Projects Launcher"


# ---------- Utilidades de rutas (soporta PyInstaller) ----------
def get_app_dir() -> Path:
    """
    Devuelve la carpeta donde está el ejecutable (si está congelado con PyInstaller)
    o donde está este archivo .py si se ejecuta como script.
    """
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).parent
    return Path(__file__).parent


APP_DIR = get_app_dir()
ASSETS_DIR = APP_DIR / "assets"
INI_PATH = APP_DIR / "projects.ini"


# ---------- Helpers del sistema ----------
def open_folder(path: str):
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_terminal(path: str):
    if sys.platform.startswith("win"):
        wt = shutil.which("wt.exe")
        if wt:
            subprocess.Popen([wt, "-d", path])
        else:
            subprocess.Popen(["cmd.exe", "/K", f'cd /d "{path}"'])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Terminal", path])
    else:
        term = shutil.which("gnome-terminal") or shutil.which("konsole") or shutil.which("xterm")
        if term and "gnome-terminal" in term:
            subprocess.Popen([term, "--working-directory", path])
        elif term and "konsole" in term:
            subprocess.Popen([term, "--workdir", path])
        elif term and "xterm" in term:
            subprocess.Popen([term], cwd=path)
        else:
            subprocess.Popen(["bash"], cwd=path)


# ---------- Modelo ----------
class Project:
    def __init__(self, title: str, desc: str, path: str, editor_cmd: str):
        self.title = title
        self.desc = desc
        self.path = path
        self.editor_cmd = editor_cmd


# ---------- Vistas ----------
class HomePage(QWidget):
    def __init__(self, projects: list[Project], on_open):
        super().__init__()
        self.on_open = on_open
        layout = QVBoxLayout(self)

        header = QLabel("<h2>Proyectos de Python</h2>")
        header.setTextFormat(Qt.RichText)
        layout.addWidget(header)

        self.listw = QListWidget()
        for p in projects:
            item = QListWidgetItem(f"{p.title}\n{p.desc}")
            item.setData(Qt.UserRole, p)
            item.setToolTip(p.path)
            self.listw.addItem(item)

        self.listw.itemDoubleClicked.connect(self._open_selected)
        layout.addWidget(self.listw)

        row = QHBoxLayout()
        open_btn = QPushButton("Abrir seleccionado")
        open_btn.clicked.connect(self._open_selected)
        row.addWidget(open_btn)
        row.addStretch(1)
        layout.addLayout(row)

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

        title = QLabel(f"<h2>{project.title}</h2>")
        title.setTextFormat(Qt.RichText)
        subtitle = QLabel(project.desc)
        pathlbl = QLabel(f"<code>{project.path}</code>")
        pathlbl.setTextFormat(Qt.RichText)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(pathlbl)

        # Acciones rápidas
        actions = QHBoxLayout()
        btn_edit = QPushButton("Abrir en editor")
        btn_edit.clicked.connect(self.open_in_editor)
        btn_folder = QPushButton("Abrir carpeta")
        btn_folder.clicked.connect(lambda: open_folder(project.path))
        btn_term = QPushButton("Abrir terminal")
        btn_term.clicked.connect(lambda: open_terminal(project.path))
        actions.addWidget(btn_edit)
        actions.addWidget(btn_folder)
        actions.addWidget(btn_term)
        actions.addStretch(1)
        layout.addLayout(actions)

        # Explorador de archivos del proyecto
        splitter = QSplitter(Qt.Vertical)
        self.model = QFileSystemModel()
        self.model.setRootPath(project.path)
        self.model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(project.path))
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setHeaderHidden(False)
        self.tree.doubleClicked.connect(self._on_double_click)

        splitter.addWidget(self.tree)
        layout.addWidget(splitter)

    def open_in_editor(self):
        cmd = self.project.editor_cmd or ""
        if not cmd:
            QMessageBox.warning(self, "Editor", "No hay comando de editor configurado.")
            return
        cmd_fmt = cmd.replace("{path}", self.project.path)
        try:
            subprocess.Popen(cmd_fmt, shell=True, cwd=self.project.path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo abrir el editor:\n{e}")

    def _on_double_click(self, index):
        path = self.model.filePath(index)
        if os.path.isfile(path):
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])


class MainWindow(QWidget):
    def __init__(self, projects: list[Project]):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(950, 650)

        # Icono de ventana (assets/app.ico o assets/app.png)
        ico_path = ASSETS_DIR / "app.ico"
        png_path = ASSETS_DIR / "app.png"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))
        elif png_path.exists():
            self.setWindowIcon(QIcon(str(png_path)))

        self.back_stack: list[int] = []
        self.forward_stack: list[int] = []

        root = QVBoxLayout(self)

        # Toolbar con flechas tipo navegador
        toolbar = QToolBar()
        self.act_back = QAction("← Atrás", self)
        self.act_forward = QAction("Adelante →", self)
        self.act_back.triggered.connect(self.go_back)
        self.act_forward.triggered.connect(self.go_forward)
        toolbar.addAction(self.act_back)
        toolbar.addAction(self.act_forward)
        toolbar.addSeparator()
        title_lbl = QLabel(f"<b>{APP_NAME}</b>")
        title_lbl.setTextFormat(Qt.RichText)
        toolbar.addWidget(title_lbl)
        root.addWidget(toolbar)

        # Páginas
        self.stack = QStackedWidget()
        self.home = HomePage(projects, on_open=self.open_project)
        self.stack.addWidget(self.home)
        root.addWidget(self.stack)

        # Footer centrado
        footer = QLabel("© 2025 Gabriel Golker")
        footer.setAlignment(Qt.AlignCenter)
        footer.setObjectName("footerLabel")
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
        self.forward_stack.append(current)
        self.stack.setCurrentIndex(prev)
        self._update_nav_buttons()

    def go_forward(self):
        if not self.forward_stack:
            return
        current = self.stack.currentIndex()
        nxt = self.forward_stack.pop()
        self.back_stack.append(current)
        self.stack.setCurrentIndex(nxt)
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        self.act_back.setEnabled(bool(self.back_stack))
        self.act_forward.setEnabled(bool(self.forward_stack))


# ---------- Config: crear projects.ini de ejemplo si falta ----------
def ensure_projects_ini(ini_path: Path) -> None:
    if ini_path.exists():
        return

    # Carpeta base de ejemplos dentro de la carpeta del usuario
    home = Path.home()
    base = home / "PythonProjects_Examples"
    proj1 = base / "Example_BPM_Converter"
    proj2 = base / "Example_VST_Envelope_Tools"
    proj3 = base / "Example_Data_ETL"

    # Crea directorios de ejemplo (no pasa nada si ya existen)
    for p in [proj1, proj2, proj3]:
        p.mkdir(parents=True, exist_ok=True)

    # Contenido de ejemplo
    example_ini = f"""[General]
editor_default=code "{{path}}"

[Proyecto1]
title=Batch BPM Converter (Ejemplo)
desc=GUI PySide6 de ejemplo. Edita 'projects.ini' para tus rutas reales.
path={proj1.as_posix()}
editor=code "{{path}}"

[Proyecto2]
title=VST Envelope Tools (Ejemplo)
desc=Proyecto de ejemplo para experimentar.
path={proj2.as_posix()}

[Proyecto3]
title=Data ETL Scripts (Ejemplo)
desc=Scripts y pruebas con pandas.
path={proj3.as_posix()}
editor=pycharm64.exe "{{path}}"
"""
    try:
        ini_path.write_text(example_ini, encoding="utf-8")
    except Exception as e:
        # Si falla por permisos, avisa pero no detiene la app: se intentará cargar igual
        QMessageBox.warning(None, "Aviso",
                            f"No se pudo crear {ini_path.name} automáticamente:\n{e}\n"
                            f"Créalo manualmente junto al ejecutable.")


def load_projects_from_ini(ini_path: Path) -> list[Project]:
    cfg = ConfigParser()
    if not ini_path.exists():
        raise FileNotFoundError(f"No se encontró {ini_path.name}.")
    cfg.read(ini_path, encoding="utf-8")

    default_editor = cfg.get("General", "editor_default", fallback='code "{path}"')
    projects: list[Project] = []
    for section in cfg.sections():
        if section == "General":
            continue
        title = cfg.get(section, "title", fallback=section)
        desc = cfg.get(section, "desc", fallback="")
        path = cfg.get(section, "path", fallback="")
        editor = cfg.get(section, "editor", fallback=default_editor)
        if not path:
            continue
        projects.append(Project(title, desc, path, editor))
    return projects


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

    # Si no existe projects.ini, lo generamos con ejemplos
    ensure_projects_ini(INI_PATH)

    try:
        projects = load_projects_from_ini(INI_PATH)
    except Exception as e:
        QMessageBox.critical(None, "Error",
                             f"No se pudo cargar {INI_PATH.name}:\n{e}\n"
                             f"Revisa permisos o crea el archivo manualmente.")
        return 1

    w = MainWindow(projects)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())


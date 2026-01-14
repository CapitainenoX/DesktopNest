#!/usr/bin/env python3
# Main.py - DesktopNest (PySide6) - Full-featured file manager
# Requirements: PySide6
# Run: python Main.py

import subprocess
import sys
import os
import shutil
import json
import threading
from pathlib import Path
from functools import partial

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeView, QListView, QFileSystemModel,
    QSplitter, QVBoxLayout, QWidget, QLineEdit, QToolBar, QMenu, QMessageBox,
    QInputDialog, QFileDialog, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QStyle, QHBoxLayout, QSizePolicy, QFrame, QProgressBar, QAbstractItemView
)
from PySide6.QtGui import QAction, QIcon, QDrag, QCursor
from PySide6.QtCore import Qt, QMimeData, QUrl, QSize, Signal, QObject

# -----------------------------
# Helpers
# -----------------------------
APP_NAME = "DesktopNest"
FAVS_FILE = Path.home() / ".desktopnest_favorites.json"

def load_favs():
    try:
        if FAVS_FILE.exists():
            return json.loads(FAVS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def save_favs(favs):
    try:
        FAVS_FILE.write_text(json.dumps(favs, indent=2), encoding="utf-8")
    except Exception:
        pass

def safe_move(src, dst_folder):
    """Déplace src (path) dans dst_folder. Gère collisions en ajoutant suffixe."""
    name = os.path.basename(src)
    dst = os.path.join(dst_folder, name)
    base, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(dst):
        dst = os.path.join(dst_folder, f"{base} ({i}){ext}")
        i += 1
    shutil.move(src, dst)
    return dst

def readable_size(n):
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"

# -----------------------------
# Custom Views with Drag/Drop
# -----------------------------
class FileListView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setIconSize(QSize(64,64))
        self.setSpacing(12)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def startDrag(self, supportedActions):
        indexes = self.selectedIndexes()
        if not indexes: 
            return
        mime = QMimeData()
        urls = []
        for idx in indexes:
            model = self.model()
            src_path = model.filePath(idx)
            urls.append(QUrl.fromLocalFile(src_path))
        mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            target_index = self.indexAt(e.position().toPoint()) if hasattr(e, 'position') else self.indexAt(e.pos())
            model = self.model()
            # destination folder: if drop on an item and it's a directory use it, else use the view root path
            dest_folder = model.filePath(self.rootIndex())
            if target_index.isValid():
                p = model.filePath(target_index)
                if os.path.isdir(p):
                    dest_folder = p
                else:
                    dest_folder = os.path.dirname(p)
            moved = []
            for url in e.mimeData().urls():
                src = url.toLocalFile()
                try:
                    new = safe_move(src, dest_folder)
                    moved.append(new)
                except Exception as ex:
                    QMessageBox.warning(self, "Erreur déplacement", f"Impossible de déplacer {src}:\n{ex}")
            e.acceptProposedAction()
            # Refresh views by emitting a custom signal through parent
            self.parent().on_fs_changed()
        else:
            super().dropEvent(e)

class FileTreeView(QTreeView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def startDrag(self, supportedActions):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        mime = QMimeData()
        urls = []
        # unique paths
        paths = set()
        for idx in indexes:
            if idx.column() != 0: continue
            src_path = self.model().filePath(self.model().index(idx.row(), 0, idx.parent()))
            # above approach may duplicate; simpler:
        # instead use selectedIndexes and for each get filePath
        for idx in self.selectedIndexes():
            if idx.column() == 0:
                p = self.model().filePath(idx)
                paths.add(p)
        for p in paths:
            urls.append(QUrl.fromLocalFile(p))
        mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            idx = self.indexAt(e.position().toPoint()) if hasattr(e, 'position') else self.indexAt(e.pos())
            model = self.model()
            dest_folder = model.filePath(self.rootIndex())
            if idx.isValid():
                p = model.filePath(idx)
                if os.path.isdir(p):
                    dest_folder = p
                else:
                    dest_folder = os.path.dirname(p)
            for url in e.mimeData().urls():
                src = url.toLocalFile()
                try:
                    new = safe_move(src, dest_folder)
                except Exception as ex:
                    QMessageBox.warning(self, "Erreur déplacement", f"Impossible de déplacer {src}:\n{ex}")
            e.acceptProposedAction()
            self.parent().on_fs_changed()
        else:
            super().dropEvent(e)

# -----------------------------
# Worker for search (thread)
# -----------------------------
class SearchWorker(QObject):
    finished = Signal(list)
    progress = Signal(int)

    def __init__(self, root, query, limit=1000):
        super().__init__()
        self.root = root
        self.query = query.lower()
        self.limit = limit
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        results = []
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            if self._stop: break
            # search in dirs
            for d in dirnames:
                if self._stop: break
                if self.query in d.lower():
                    results.append(os.path.join(dirpath, d))
                    count += 1
                    if count % 20 == 0:
                        self.progress.emit(count)
                if count >= self.limit: break
            # search in files
            for f in filenames:
                if self._stop: break
                if self.query in f.lower():
                    results.append(os.path.join(dirpath, f))
                    count += 1
                    if count % 20 == 0:
                        self.progress.emit(count)
                if count >= self.limit: break
            if count >= self.limit: break
        self.finished.emit(results)

# -----------------------------
# Main Window
# -----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.favs = load_favs()

        # Root default: home
        self.root_path = str(Path.home())

        # Toolbar
        tb = QToolBar()
        self.addToolBar(tb)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Recherche (nom de fichier / dossier)...")
        self.search_input.returnPressed.connect(self.on_search)
        tb.addWidget(self.search_input)

        act_search = QAction("Search", self)
        act_search.triggered.connect(self.on_search)
        tb.addAction(act_search)

        tb.addSeparator()

        self.dark_action = QAction("Dark", self)
        self.dark_action.setCheckable(True)
        self.dark_action.triggered.connect(self.toggle_dark)
        tb.addAction(self.dark_action)

        tb.addSeparator()

        act_new = QAction("Nouveau dossier", self)
        act_new.triggered.connect(self.create_folder)
        tb.addAction(act_new)

        act_refresh = QAction("Refresh", self)
        act_refresh.triggered.connect(self.refresh_views)
        tb.addAction(act_refresh)

        act_root = QAction("Changer racine", self)
        act_root.triggered.connect(self.change_root)
        tb.addAction(act_root)

        # Central split
        central = QWidget()
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Left: Tree
        self.model = QFileSystemModel()
        self.model.setRootPath(self.root_path)

        self.tree = FileTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(self.root_path))
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(self.on_tree_clicked)
        self.tree.setExpandsOnDoubleClick(True)
        splitter.addWidget(self.tree)

        # Center: Icon list
        self.list = FileListView(self)
        self.list.setModel(self.model)
        self.list.setRootIndex(self.model.index(self.root_path))
        self.list.doubleClicked.connect(self.on_list_doubleclicked)
        splitter.addWidget(self.list)

        # Right: Meta + favorites
        right = QFrame()
        right.setMinimumWidth(280)
        right.setMaximumWidth(420)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8,8,8,8)

        lbl = QLabel("<b>Détails</b>")
        right_layout.addWidget(lbl)

        self.details = QLabel("Sélectionnez un élément")
        self.details.setWordWrap(True)
        self.details.setMinimumHeight(120)
        right_layout.addWidget(self.details)

        btns = QHBoxLayout()
        self.btn_open = QPushButton("Ouvrir")
        self.btn_open.clicked.connect(self.open_selected)
        btns.addWidget(self.btn_open)
        self.btn_rename = QPushButton("Renommer")
        self.btn_rename.clicked.connect(self.rename_selected)
        btns.addWidget(self.btn_rename)
        self.btn_delete = QPushButton("Supprimer")
        self.btn_delete.clicked.connect(self.delete_selected)
        btns.addWidget(self.btn_delete)
        right_layout.addLayout(btns)

        right_layout.addSpacing(8)
        fav_label = QLabel("<b>Favoris</b>")
        right_layout.addWidget(fav_label)
        self.fav_list = QListWidget()
        self.fav_list.itemDoubleClicked.connect(self.on_fav_open)
        right_layout.addWidget(self.fav_list)

        self.btn_add_fav = QPushButton("Ajouter aux favoris")
        self.btn_add_fav.clicked.connect(self.add_favorite_current)
        right_layout.addWidget(self.btn_add_fav)

        right_layout.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([300, 600, 300])

        # Context menus
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_list)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_tree)

        # Keep track of selection
        self.list.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.tree.selectionModel().selectionChanged.connect(self.on_selection_changed)

        # Load favorites
        self.load_favorites()

        # Simple style
        self.apply_light_style()

    # -----------------------------
    # UI / Style
    # -----------------------------
    def apply_dark_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #0f1720; color: #e6eef6; }
            QTreeView, QListView, QLabel, QLineEdit, QListWidget { background: #0b1220; color: #dfe9f2; }
            QToolBar { background: #071226; }
            QPushButton { background: #12263a; color: #e6eef6; border-radius:6px; padding:6px; }
            QPushButton:hover { background: #1b3550; }
        """)
    def apply_light_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #f8fafc; color: #0f1720; }
            QTreeView, QListView, QLabel, QLineEdit, QListWidget { background: #ffffff; color: #0f1720; }
            QToolBar { background: #ffffff; }
            QPushButton { background: #f1f5f9; color: #0f1720; border-radius:6px; padding:6px; }
            QPushButton:hover { background: #e2e8f0; }
        """)
    def toggle_dark(self, checked):
        if checked:
            self.apply_dark_style()
        else:
            self.apply_light_style()

    # -----------------------------
    # Actions: tree/list interactions
    # -----------------------------
    def on_tree_clicked(self, index):
        path = self.model.filePath(index)
        if os.path.isdir(path):
            self.list.setRootIndex(self.model.index(path))
        self.update_details_for_path(path)

    def on_list_doubleclicked(self, index):
        path = self.model.filePath(index)
        if os.path.isdir(path):
            self.list.setRootIndex(self.model.index(path))
            # expand tree to show it
            idx = self.model.index(path)
            self.tree.setCurrentIndex(idx)
            self.tree.expand(idx)
        else:
            # open file with default app
            try:
                if sys.platform.startswith('win'):
                    os.startfile(path)
                elif sys.platform.startswith('darwin'):
                    subprocess.call(('open', path))
                else:
                    subprocess.call(('xdg-open', path))
            except Exception as ex:
                QMessageBox.warning(self, "Ouvrir fichier", f"Impossible d'ouvrir: {ex}")
        self.update_details_for_path(path)

    def on_selection_changed(self, *a):
        # prefer list selection if present
        sel = self.list.selectionModel().selectedIndexes()
        if sel:
            path = self.model.filePath(sel[0])
            self.update_details_for_path(path)
        else:
            sel2 = self.tree.selectionModel().selectedIndexes()
            if sel2:
                path = self.model.filePath(sel2[0])
                self.update_details_for_path(path)
            else:
                self.details.setText("Sélectionnez un élément")

    def update_details_for_path(self, path):
        try:
            st = os.stat(path)
            t = "Dossier" if os.path.isdir(path) else "Fichier"
            txt = f"<b>{os.path.basename(path)}</b><br>Type: {t}<br>Chemin: {path}<br>Taille: {readable_size(st.st_size) if not os.path.isdir(path) else '-'}<br>Modifié: {QApplication.instance().toNativeSeparators(str(Path(path).stat().st_mtime))}"
            self.details.setText(txt)
        except Exception:
            self.details.setText(f"<b>{os.path.basename(path)}</b><br>Chemin: {path}")

    def context_list(self, pos):
        idx = self.list.indexAt(pos)
        menu = QMenu()
        if idx.isValid():
            path = self.model.filePath(idx)
            menu.addAction("Ouvrir", partial(self.open_path, path))
            menu.addAction("Renommer", partial(self.rename_path, path))
            menu.addAction("Supprimer", partial(self.delete_path, path))
            menu.addAction("Ajouter aux favoris", partial(self.add_favorite, path))
        else:
            menu.addAction("Nouveau dossier ici", partial(self.create_folder_in_root, self.list.rootIndex()))
        menu.exec(self.list.mapToGlobal(pos))

    def context_tree(self, pos):
        idx = self.tree.indexAt(pos)
        menu = QMenu()
        if idx.isValid():
            path = self.model.filePath(idx)
            menu.addAction("Ouvrir", partial(self.open_path, path))
            menu.addAction("Renommer", partial(self.rename_path, path))
            menu.addAction("Supprimer", partial(self.delete_path, path))
            menu.addAction("Ajouter aux favoris", partial(self.add_favorite, path))
        menu.exec(self.tree.mapToGlobal(pos))

    # -----------------------------
    # CRUD operations
    # -----------------------------
    def create_folder(self):
        # create in current list root
        idx = self.list.rootIndex()
        self.create_folder_in_root(idx)

    def create_folder_in_root(self, root_index):
        parent_path = self.model.filePath(root_index) if root_index.isValid() else self.root_path
        name, ok = QInputDialog.getText(self, "Nouveau dossier", "Nom du dossier :")
        if ok and name:
            try:
                os.mkdir(os.path.join(parent_path, name))
                self.refresh_views()
            except Exception as ex:
                QMessageBox.warning(self, "Erreur", str(ex))

    def rename_selected(self):
        sel = self.list.selectionModel().selectedIndexes()
        if sel:
            path = self.model.filePath(sel[0])
            self.rename_path(path)
        else:
            QMessageBox.information(self, "Renommer", "Sélectionnez un élément dans la liste")

    def rename_path(self, path):
        base = os.path.basename(path)
        new, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", text=base)
        if ok and new:
            try:
                new_path = os.path.join(os.path.dirname(path), new)
                os.rename(path, new_path)
                self.refresh_views()
            except Exception as ex:
                QMessageBox.warning(self, "Erreur renommage", str(ex))

    def delete_selected(self):
        sel = self.list.selectionModel().selectedIndexes()
        if sel:
            path = self.model.filePath(sel[0])
            self.delete_path(path)
        else:
            QMessageBox.information(self, "Supprimer", "Sélectionnez un élément dans la liste")

    def delete_path(self, path):
        reply = QMessageBox.question(self, "Supprimer", f"Supprimer {path} ?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                self.refresh_views()
            except Exception as ex:
                QMessageBox.warning(self, "Erreur suppression", str(ex))

    def open_selected(self):
        sel = self.list.selectionModel().selectedIndexes()
        if sel:
            path = self.model.filePath(sel[0])
            self.open_path(path)
        else:
            QMessageBox.information(self, "Ouvrir", "Sélectionnez un élément")

    def open_path(self, path):
        try:
            if os.path.isdir(path):
                self.list.setRootIndex(self.model.index(path))
                self.tree.setCurrentIndex(self.model.index(path))
                self.tree.expand(self.model.index(path))
            else:
                if sys.platform.startswith('win'):
                    os.startfile(path)
                elif sys.platform.startswith('darwin'):
                    os.system(f"open \"{path}\"")
                else:
                    os.system(f"xdg-open \"{path}\"")
        except Exception as ex:
            QMessageBox.warning(self, "Ouvrir", str(ex))

    # -----------------------------
    # Favorites
    # -----------------------------
    def load_favorites(self):
        self.fav_list.clear()
        for p in self.favs:
            it = QListWidgetItem(p)
            self.fav_list.addItem(it)

    def add_favorite(self, path):
        if path not in self.favs:
            self.favs.append(path)
            save_favs(self.favs)
            self.load_favorites()

    def add_favorite_current(self):
        # add currently selected
        sel = self.list.selectionModel().selectedIndexes()
        if sel:
            path = self.model.filePath(sel[0])
            self.add_favorite(path)
        else:
            QMessageBox.information(self, "Favoris", "Sélectionnez un élément")

    def on_fav_open(self, item):
        path = item.text()
        if os.path.exists(path):
            self.open_path(path)
        else:
            QMessageBox.warning(self, "Favoris", "Élément introuvable, suppression du favori")
            self.favs = [f for f in self.favs if f != path]
            save_favs(self.favs)
            self.load_favorites()

    # -----------------------------
    # Root & refresh
    # -----------------------------
    def change_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir racine", self.root_path)
        if folder:
            self.root_path = folder
            self.model.setRootPath(self.root_path)
            self.tree.setRootIndex(self.model.index(self.root_path))
            self.list.setRootIndex(self.model.index(self.root_path))
            self.refresh_views()

    def refresh_views(self):
        # refresh model (QFileSystemModel doesn't provide a direct refresh method everywhere)
        self.model.setRootPath(self.root_path)
        current_list_root = self.list.rootIndex()
        self.list.setRootIndex(self.model.index(self.model.filePath(current_list_root)))
        self.tree.setRootIndex(self.model.index(self.root_path))
        self.load_favorites()

    def on_fs_changed(self):
        # called after drag/drop moves to refresh
        self.refresh_views()

    # -----------------------------
    # Search
    # -----------------------------
    def on_search(self):
        q = self.search_input.text().strip()
        if not q:
            QMessageBox.information(self, "Recherche", "Entrez un terme de recherche.")
            return
        # Run threaded search to avoid freeze
        dlg = QProgressBar()
        dlg.setRange(0, 0)
        dlg.setTextVisible(True)
        dlg.setFormat("Recherche en cours...")
        dlg.setMinimumWidth(300)
        dlg.setWindowTitle("Recherche")
        dlg.show()

        results_holder = []
        def finished(results):
            dlg.close()
            # show results in a simple dialog (replacing list content)
            if not results:
                QMessageBox.information(self, "Recherche", "Aucun résultat.")
                return
            # create a temp model showing results (we will populate list as plain items)
            self.list.setModel(None)
            self.list.clear()
            # use QListWidget-like behavior: show icons + names
            lw = QListWidget()
            for p in results:
                it = QListWidgetItem(os.path.basename(p))
                it.setToolTip(p)
                it.setData(Qt.UserRole, p)
                lw.addItem(it)
            # replace list with lw temporarily inside center widget
            parent = self.list.parent()
            splitter = self.list.parent().parent().findChild(QSplitter)
            # easier approach: open a result dialog
            dlg2 = QMessageBox(self)
            dlg2.setWindowTitle("Résultats de recherche")
            text = "\n".join(results[:200])  # limit printing
            dlg2.setText(f"{len(results)} résultats (affichés: {min(len(results),200)})\n\nVoir chemins dans le terminal.")
            dlg2.exec()
            print("Search results (first 500):")
            for p in results[:500]:
                print(p)

        def worker():
            sw = SearchWorker(self.root_path, q, limit=2000)
            sw.finished.connect(finished)
            sw.run()

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    # -----------------------------
    # Utilities
    # -----------------------------
    def update_details_for_path(self, path):
        try:
            st = os.stat(path)
            t = "Dossier" if os.path.isdir(path) else "Fichier"
            size = readable_size(st.st_size) if os.path.isfile(path) else "-"
            txt = f"<b>{os.path.basename(path)}</b><br>Type: {t}<br>Chemin: {path}<br>Taille: {size}"
            self.details.setText(txt)
        except Exception:
            self.details.setText(f"<b>{os.path.basename(path)}</b><br>Chemin: {path}")

# -----------------------------
# Main
# -----------------------------
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

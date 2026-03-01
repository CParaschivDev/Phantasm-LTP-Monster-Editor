"""PySide6 GUI for MU Monster Editor (simplified modern UI).
This is a minimal but functional PySide6 application that uses the io_* modules.
"""
from __future__ import annotations

import sys
import os
from PySide6 import QtWidgets, QtCore, QtGui
try:
    from PySide6.QtSvg import QSvgWidget
except Exception:
    QSvgWidget = None
try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:
    QSvgRenderer = None
 

def asset_path(rel: str) -> str:
    """Return absolute path to an asset working in dev and PyInstaller builds."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    # possible locations depending on how --add-data was provided
    candidates = [
        os.path.join(base, 'mu_monster_editor', 'assets', rel),
        os.path.join(base, 'assets', rel),
        os.path.join(base, rel),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return os.path.join(base, 'assets', rel)
import xml.etree.ElementTree as ET

from io_monster import parse_monster_txt, save_monster_txt_patch, MONSTER_FIELDS
from io_monster import strip_inline_comment
from io_spawn import parse_monster_spawn_xml, save_monster_spawn_xml
from io_list import regenerate_monster_list_xml, render_monsterlist_string, backup_file
from history import HistoryStack
from map_loader import load_map


class MonsterTableModel(QtGui.QStandardItemModel):
    def __init__(self, monsters: list[dict]):
        super().__init__()
        headers = [f for f, _ in MONSTER_FIELDS]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.load(monsters)

    def load(self, monsters: list[dict]):
        self.setRowCount(0)
        for m in monsters:
            items = []
            for field, ftype in MONSTER_FIELDS:
                v = m.get(field, "")
                it = QtGui.QStandardItem(str(v))
                it.setEditable(True)
                items.append(it)
            self.appendRow(items)

    def to_monsters(self) -> list[dict]:
        mons = []
        for r in range(self.rowCount()):
            rec = {}
            for c, (field, ftype) in enumerate(MONSTER_FIELDS):
                val = self.item(r, c).text()
                if ftype is int:
                    try:
                        rec[field] = int(val)
                    except Exception:
                        rec[field] = 0
                else:
                    rec[field] = val
            mons.append(rec)
        return mons


class SpawnDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, monster_choices: list[tuple[int,str]] = None, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Spawn")
        self.setModal(True)
        self.result = None
        self.monster_choices = monster_choices or []

        layout = QtWidgets.QFormLayout(self)
        self.cb_mon = QtWidgets.QComboBox()
        for i,n in self.monster_choices:
            self.cb_mon.addItem(f"{i} - {n}", i)
        layout.addRow("Monster:", self.cb_mon)

        self.fields = {}
        keys = ["Count","StartX","StartY","EndX","EndY","Distance","Dir","Value"]
        for k in keys:
            le = QtWidgets.QLineEdit()
            layout.addRow(k+":", le)
            self.fields[k] = le

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

        if initial:
            idx = initial.get("Index")
            if idx is not None:
                for i in range(self.cb_mon.count()):
                    if str(self.cb_mon.itemData(i)) == str(idx):
                        self.cb_mon.setCurrentIndex(i)
                        break
            for k in keys:
                if k in initial:
                    self.fields[k].setText(str(initial.get(k, "")))

    def accept(self):
        if self.cb_mon.currentIndex() < 0:
            QtWidgets.QMessageBox.warning(self, "Missing", "Select a monster")
            return
        idx = self.cb_mon.currentData()
        data = {"Index": idx}
        for k, le in self.fields.items():
            txt = le.text().strip()
            if txt != "":
                data[k] = txt
        self.result = data
        super().accept()


class MapCanvas(QtWidgets.QWidget):
    """Simple map preview that draws spawn points and allows clicking to select them."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self._spawns = []  # list of (x,y,label)
        self._selected_index = None
        self._background_image = None
        self._map_info = None
        # zoom and pan
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self._panning = False
        self._pan_start = None

    def set_spawns(self, spawns: list[tuple[int,int,str]]):
        self._spawns = spawns or []
        self._selected_index = None
        self.update()

    def select_index(self, idx: int | None):
        self._selected_index = idx
        self.update()

    def paintEvent(self, ev):
        qp = QtGui.QPainter(self)
        rect = self.rect()
        qp.fillRect(rect, QtGui.QColor('#2e2e2e'))
        # draw background map image if available
        pad = 12
        inner = rect.adjusted(pad, pad, -pad, -pad)
        if getattr(self, '_background_image', None) is not None:
            try:
                # draw background respecting zoom and pan
                img = self._background_image
                target_w = max(1, int(inner.width() * self.zoom))
                target_h = max(1, int(inner.height() * self.zoom))
                scaled = img.scaled(target_w, target_h, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
                # compute top-left so image is centered in inner area and then shifted by pan
                offset_x = int((inner.width() - target_w) / 2 + self.pan_x)
                offset_y = int((inner.height() - target_h) / 2 + self.pan_y)
                top_left = inner.topLeft() + QtCore.QPoint(offset_x, offset_y)
                qp.drawImage(top_left, scaled)
            except Exception:
                pass
        # draw border
        pen = QtGui.QPen(QtGui.QColor('#888'))
        qp.setPen(pen)
        qp.drawRect(rect.adjusted(1,1,-2,-2))

        if not self._spawns:
            qp.setPen(QtGui.QColor('#bbb'))
            qp.drawText(rect, QtCore.Qt.AlignCenter, 'No spawn preview')
            qp.end()
            return

        # compute bounds or use map image dimensions when available
        if self._map_info and self._map_info.get('width') and self._map_info.get('height'):
            minx, miny = 0, 0
            maxx, maxy = int(self._map_info['width']) - 1, int(self._map_info['height']) - 1
        else:
            xs = [p[0] for p in self._spawns if isinstance(p[0], (int,float))]
            ys = [p[1] for p in self._spawns if isinstance(p[1], (int,float))]
            if not xs or not ys:
                qp.setPen(QtGui.QColor('#bbb'))
                qp.drawText(rect, QtCore.Qt.AlignCenter, 'Coordinates not available')
                qp.end()
                return
            minx, maxx = min(xs), max(xs)
            miny, maxy = min(ys), max(ys)
            if minx == maxx:
                minx -= 1; maxx += 1
            if miny == maxy:
                miny -= 1; maxy += 1

        # padding
        pad = 12
        w = rect.width() - pad*2
        h = rect.height() - pad*2

        def to_canvas(x, y):
            # Map world/map coordinates to canvas pixels, then apply zoom & pan
            if self._map_info and self._map_info.get('width') and self._map_info.get('height'):
                img_w = int(self._map_info['width'])
                img_h = int(self._map_info['height'])
                # image coords -> area inside padding
                base_x = pad + int((x / max(1, img_w - 1)) * w)
                base_y = pad + int((y / max(1, img_h - 1)) * h)
            else:
                base_x = pad + int((x - minx) / (maxx - minx) * w)
                base_y = pad + int((y - miny) / (maxy - miny) * h)
            # apply zoom and pan centered on widget
            cx = int((base_x - rect.center().x()) * self.zoom + rect.center().x() + self.pan_x)
            cy = int((base_y - rect.center().y()) * self.zoom + rect.center().y() + self.pan_y)
            return cx, cy

        # draw spawns
        for i, (x,y,label) in enumerate(self._spawns):
            cx, cy = to_canvas(x,y)
            color = QtGui.QColor('#66c')
            if i == self._selected_index:
                color = QtGui.QColor('#ffd54f')
            qp.setBrush(color)
            qp.setPen(QtGui.QColor('#222'))
            qp.drawEllipse(QtCore.QPoint(cx, cy), 6, 6)
        qp.end()

    def mousePressEvent(self, ev: QtGui.QMouseEvent):
        if not self._spawns:
            return
        pos = ev.position().toPoint()
        # compute same transform as paintEvent to find nearest
        xs = [p[0] for p in self._spawns]
        ys = [p[1] for p in self._spawns]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        if minx == maxx:
            minx -= 1; maxx += 1
        if miny == maxy:
            miny -= 1; maxy += 1
        pad = 12
        w = self.rect().width() - pad*2
        h = self.rect().height() - pad*2
        best = None
        bestd = 1e9
        for i, (x,y,label) in enumerate(self._spawns):
            cx = pad + int((x - minx) / (maxx - minx) * w)
            cy = pad + int((y - miny) / (maxy - miny) * h)
            d = (cx - pos.x())**2 + (cy - pos.y())**2
            if d < bestd:
                bestd = d; best = i
        # tolerance
        if best is not None and bestd <= 30*30:
            self._selected_index = best
            self.update()
            # notify parent window
            p = self.parent()
            if hasattr(p, 'on_map_selected'):
                p.on_map_selected(best)
            # begin possible drag
            self._drag_index = best
            self._dragging = True
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        else:
            self._drag_index = None
            self._dragging = False
        # start panning on middle-button
        if ev.button() == QtCore.Qt.MiddleButton:
            self._panning = True
            self._pan_start = pos
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        if not getattr(self, '_dragging', False) or self._drag_index is None:
            return
        # compute inverse transform to world coords and optionally show preview
        pos = ev.position().toPoint()
        xs = [p[0] for p in self._spawns]
        ys = [p[1] for p in self._spawns]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        if minx == maxx:
            minx -= 1; maxx += 1
        if miny == maxy:
            miny -= 1; maxy += 1
        pad = 12
        w = self.rect().width() - pad*2
        h = self.rect().height() - pad*2
        # clamp
        rx = max(0, min(pos.x()-pad, w))
        ry = max(0, min(pos.y()-pad, h))
        world_x = int(minx + (rx / w) * (maxx - minx))
        world_y = int(miny + (ry / h) * (maxy - miny))
        # notify parent with preview (optional)
        p = self.parent()
        if hasattr(p, 'on_map_move_preview'):
            p.on_map_move_preview(self._drag_index, world_x, world_y)

    def set_background_image(self, qimage: QtGui.QImage | None):
        self._background_image = qimage
        self.update()

    def load_map_file(self, path: str) -> bool:
        """Load a map file using map_loader and convert to an indexed QImage.

        Returns True on success.
        """
        info = load_map(path)
        if not info:
            self._background_image = None
            self._map_info = None
            return False
        w = info.get('width')
        h = info.get('height')
        tiles = info.get('tiles')
        try:
            img = QtGui.QImage(w, h, QtGui.QImage.Format_Indexed8)
            # build a higher-contrast palette to make terrain visible on dark UI
            palette = [0] * 256
            for i in range(256):
                # map tile value to an HSV color for visibility
                hue = (i * 97) % 360
                col = QtGui.QColor()
                col.setHsv(int(hue), 200, 220)
                palette[i] = QtGui.qRgb(col.red(), col.green(), col.blue())
            img.setColorTable(palette)
            for y, row in enumerate(tiles):
                for x, v in enumerate(row):
                    img.setPixel(x, y, int(v) & 0xFF)
            self._background_image = img
            self._map_info = info
            self.update()
            # debug write
            try:
                dbg = os.path.join(os.path.dirname(__file__), 'backups', 'map_preview_debug.txt')
                os.makedirs(os.path.dirname(dbg), exist_ok=True)
                with open(dbg, 'a', encoding='utf-8') as f:
                    f.write(f'LOAD_OK: {path} -> {w}x{h} offset={info.get("offset")}\n')
            except Exception:
                pass
            return True
        except Exception:
            self._background_image = None
            self._map_info = None
            try:
                dbg = os.path.join(os.path.dirname(__file__), 'backups', 'map_preview_debug.txt')
                os.makedirs(os.path.dirname(dbg), exist_ok=True)
                with open(dbg, 'a', encoding='utf-8') as f:
                    f.write(f'LOAD_FAIL: {path}\n')
            except Exception:
                pass
            return False

    def load_map_pair(self, terrain_path: str | None, client_path: str | None) -> bool:
        """Load terrain (base) and client (overlay) maps and composite them into an image.

        The terrain provides the main background; the client map is rendered
        as a semi-transparent overlay to show objects/structure.
        """
        if not terrain_path and not client_path:
            return False
        base_info = None
        client_info = None
        try:
            if terrain_path and os.path.exists(terrain_path):
                base_info = load_map(terrain_path)
        except Exception:
            base_info = None
        try:
            if client_path and os.path.exists(client_path):
                client_info = load_map(client_path)
        except Exception:
            client_info = None

        # prefer base_info for dimensions
        info = base_info or client_info
        if not info:
            return False
        w = info.get('width')
        h = info.get('height')
        # create 32-bit ARGB image for easy compositing
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.qRgba(0,0,0,0))

        # draw terrain as muted grayscale
        if base_info:
            palette = [QtGui.qRgb(i, i, i) for i in range(256)]
            for y, row in enumerate(base_info.get('tiles', [])):
                for x, v in enumerate(row):
                    val = int(v) & 0xFF
                    c = QtGui.QColor(palette[val]) if val < len(palette) else QtGui.QColor(val, val, val)
                    # make terrain darker for contrast
                    c = QtGui.QColor(max(0, c.red()-30), max(0, c.green()-30), max(0, c.blue()-30))
                    img.setPixelColor(x, y, c)

        # overlay client map with vivid translucent colors
        if client_info:
            for y, row in enumerate(client_info.get('tiles', [])):
                for x, v in enumerate(row):
                    val = int(v) & 0xFF
                    if val == 0:
                        continue
                    hue = (val * 73) % 360
                    col = QtGui.QColor()
                    col.setHsv(int(hue), 220, 230, 180)
                    # blend over existing pixel
                    existing = img.pixelColor(x, y)
                    # simple alpha composite
                    a = col.alpha() / 255.0
                    nr = int(col.red()*a + existing.red()*(1-a))
                    ng = int(col.green()*a + existing.green()*(1-a))
                    nb = int(col.blue()*a + existing.blue()*(1-a))
                    img.setPixelColor(x, y, QtGui.QColor(nr, ng, nb))

        self._background_image = img
        self._map_info = {'width': w, 'height': h, 'terrain': terrain_path, 'client': client_path}
        self.update()
        # debug
        try:
            dbg = os.path.join(os.path.dirname(__file__), 'backups', 'map_preview_debug.txt')
            os.makedirs(os.path.dirname(dbg), exist_ok=True)
            with open(dbg, 'a', encoding='utf-8') as f:
                f.write(f'LOAD_PAIR: terrain={terrain_path} client={client_path} -> {w}x{h}\n')
        except Exception:
            pass
        return True

    def mouseReleaseEvent(self, ev: QtGui.QMouseEvent):
        # end panning
        if getattr(self, '_panning', False):
            self._panning = False
            self._pan_start = None
            self.setCursor(QtCore.Qt.ArrowCursor)
            return
        if not getattr(self, '_dragging', False) or self._drag_index is None:
            return
        pos = ev.position().toPoint()
        xs = [p[0] for p in self._spawns]
        ys = [p[1] for p in self._spawns]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        if minx == maxx:
            minx -= 1; maxx += 1
        if miny == maxy:
            miny -= 1; maxy += 1
        pad = 12
        w = self.rect().width() - pad*2
        h = self.rect().height() - pad*2
        rx = max(0, min(pos.x()-pad, w))
        ry = max(0, min(pos.y()-pad, h))
        world_x = int(minx + (rx / w) * (maxx - minx))
        world_y = int(miny + (ry / h) * (maxy - miny))
        p = self.parent()
        if hasattr(p, 'on_map_move'):
            p.on_map_move(self._drag_index, world_x, world_y)
        self._dragging = False
        self._drag_index = None
        self.setCursor(QtCore.Qt.ArrowCursor)

    def wheelEvent(self, ev: QtGui.QWheelEvent):
        # zoom in/out centered on cursor
        delta = ev.angleDelta().y()
        if delta == 0:
            return
        old_zoom = self.zoom
        factor = 1.0 + (0.0015 * delta)
        self.zoom = max(0.1, min(8.0, self.zoom * factor))
        # adjust pan to keep cursor point stable
        cursor = ev.position().toPoint()
        cx, cy = cursor.x(), cursor.y()
        # simple pan adjustment
        self.pan_x = int((self.pan_x + cx) - (cx - (cx - self.pan_x)) * (self.zoom / old_zoom))
        self.pan_y = int((self.pan_y + cy) - (cy - (cy - self.pan_y)) * (self.zoom / old_zoom))
        self.update()

    def mouseMoveEvent(self, ev: QtGui.QMouseEvent):
        pos = ev.position().toPoint()
        if getattr(self, '_panning', False) and self._pan_start is not None:
            dx = pos.x() - self._pan_start.x()
            dy = pos.y() - self._pan_start.y()
            self.pan_x += dx
            self.pan_y += dy
            self._pan_start = pos
            self.update()
            return
        return super().mouseMoveEvent(ev)


class BulkSpawnDialog(QtWidgets.QDialog):
    """Dialog to perform bulk operations on selected spawns."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Bulk Edit Spawns')
        self.setModal(True)
        layout = QtWidgets.QFormLayout(self)

        self.count_edit = QtWidgets.QLineEdit()
        self.count_edit.setPlaceholderText('Leave empty to keep')
        layout.addRow('Set Count:', self.count_edit)

        self.index_offset = QtWidgets.QSpinBox()
        self.index_offset.setRange(-10000, 10000)
        self.index_offset.setValue(0)
        layout.addRow('Index offset (+/-):', self.index_offset)

        self.chk_delete = QtWidgets.QCheckBox('Delete selected spawns')
        layout.addRow(self.chk_delete)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self):
        cnt_txt = self.count_edit.text().strip()
        count = None
        if cnt_txt != '':
            try:
                count = int(cnt_txt)
            except Exception:
                count = None
        return {'count': count, 'offset': int(self.index_offset.value()), 'delete': bool(self.chk_delete.isChecked())}


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Phantasm LTP Monster Editor")
        self.resize(1200, 800)

        self.folder = None
        self.monster_txt_path = None
        self.monster_list_xml_path = None
        self.monster_spawn_xml_path = None

        self.monsters = []
        self.monster_lines = []
        self.monster_encoding = "utf-8"
        self.spawn_tree = None

        # history for undo/redo
        self.history = HistoryStack()

        self._build_ui()
        # load saved UI state and theme
        self._load_settings()
        # ensure icons exist (generate from SVG when possible)
        try:
            self.generate_icons_from_svg()
        except Exception:
            pass

    def _build_ui(self):
        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        v = QtWidgets.QVBoxLayout(w)

        top_bar = QtWidgets.QHBoxLayout()
        # load logo from assets (dev or bundled)
        logo_svg = asset_path("logo.svg")
        logo_png = asset_path("logo.png")
        try:
            if QSvgWidget is not None and os.path.exists(logo_svg):
                logo_w = QSvgWidget(logo_svg)
                logo_w.setFixedSize(48, 48)
                top_bar.addWidget(logo_w)
            elif os.path.exists(logo_png):
                lbl = QtWidgets.QLabel()
                pix = QtGui.QPixmap(logo_png)
                lbl.setPixmap(pix.scaled(48, 48, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
                top_bar.addWidget(lbl)
        except Exception:
            pass
        btn_open = QtWidgets.QPushButton("Open Monster Folder...")
        btn_open.clicked.connect(self.open_folder)
        top_bar.addWidget(btn_open)

        btn_dry = QtWidgets.QPushButton("Dry-run validation")
        btn_dry.clicked.connect(self.dry_run_validation)
        top_bar.addWidget(btn_dry)

        btn_regen = QtWidgets.QPushButton("Regenerate MonsterList.xml")
        btn_regen.clicked.connect(self.regen_monster_list)
        top_bar.addWidget(btn_regen)

        btn_saveall = QtWidgets.QPushButton("Save ALL")
        btn_saveall.clicked.connect(self.save_all)
        top_bar.addWidget(btn_saveall)
        btn_snaps = QtWidgets.QPushButton("Snapshots...")
        btn_snaps.clicked.connect(self.open_snapshots_browser)
        top_bar.addWidget(btn_snaps)

        top_bar.addStretch()
        self.lbl_folder = QtWidgets.QLabel("No folder selected")
        top_bar.addWidget(self.lbl_folder)
        v.addLayout(top_bar)

        tabs = QtWidgets.QTabWidget()
        v.addWidget(tabs)

        # SetBase tab (MonsterSetBase.txt / MonsterSetBaseCS.txt)
        tab_set = QtWidgets.QWidget()
        tabs.addTab(tab_set, "SetBase (MonsterSetBase)")
        set_layout = QtWidgets.QVBoxLayout(tab_set)

        top_set = QtWidgets.QHBoxLayout()
        self.sb_open_btn = QtWidgets.QPushButton("Open SetBase file...")
        self.sb_open_btn.clicked.connect(self.open_setbase_file)
        top_set.addWidget(self.sb_open_btn)
        self.sb_filter = QtWidgets.QLineEdit()
        self.sb_filter.setPlaceholderText("Filter (monster id or comment)...")
        self.sb_filter.textChanged.connect(self._filter_setbase)
        top_set.addWidget(self.sb_filter)
        set_layout.addLayout(top_set)

        self.table_setbase = QtWidgets.QTableWidget()
        cols = ["Monster","MapNumber","Range","PosX","PosY","Direction","Comment"]
        self.table_setbase.setColumnCount(len(cols))
        self.table_setbase.setHorizontalHeaderLabels(cols)
        self.table_setbase.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        self.table_setbase.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        set_layout.addWidget(self.table_setbase)

        bot_set = QtWidgets.QHBoxLayout()
        btn_import = QtWidgets.QPushButton("Import selected → Spawns")
        btn_import.clicked.connect(self.import_selected_setbase)
        bot_set.addWidget(btn_import)
        btn_sync = QtWidgets.QPushButton("Sync SetBase (write suggestion)")
        btn_sync.clicked.connect(self.sync_setbase)
        bot_set.addWidget(btn_sync)
        bot_set.addStretch()
        set_layout.addLayout(bot_set)

        # Monsters tab
        tab_mon = QtWidgets.QWidget()
        tabs.addTab(tab_mon, "Monsters (Monster.txt)")
        h = QtWidgets.QHBoxLayout(tab_mon)

        left = QtWidgets.QWidget()
        left_v = QtWidgets.QVBoxLayout(left)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Search...")
        self.filter_edit.textChanged.connect(self._filter_monsters)
        left_v.addWidget(self.filter_edit)

        self.view_mon = QtWidgets.QTableView()
        self.view_mon.setSortingEnabled(True)
        left_v.addWidget(self.view_mon)
        # context menu for monsters table
        self.view_mon.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.view_mon.customContextMenuRequested.connect(self._monsters_context_menu)

        btns = QtWidgets.QHBoxLayout()
        btn_new = QtWidgets.QPushButton("New (next free Index)")
        btn_new.clicked.connect(self.new_monster)
        btns.addWidget(btn_new)
        btn_dup = QtWidgets.QPushButton("Duplicate selected")
        btn_dup.clicked.connect(self.dup_monster)
        btns.addWidget(btn_dup)
        btn_del = QtWidgets.QPushButton("Delete selected")
        btn_del.clicked.connect(self.del_monster)
        btns.addWidget(btn_del)
        left_v.addLayout(btns)

        h.addWidget(left, 3)

        # Right: detail editor
        right = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(right)
        self.edit_fields = {}
        for field, ftype in MONSTER_FIELDS:
            le = QtWidgets.QLineEdit()
            form.addRow(field + ":", le)
            self.edit_fields[field] = le
        btn_apply = QtWidgets.QPushButton("Apply to selected row")
        btn_apply.clicked.connect(self.apply_to_selected)
        form.addRow(btn_apply)

        h.addWidget(right, 2)

        # Spawns tab
        tab_sp = QtWidgets.QWidget()
        tabs.addTab(tab_sp, "Spawns (MonsterSpawn.xml)")
        sp_layout = QtWidgets.QVBoxLayout(tab_sp)

        top_sp = QtWidgets.QHBoxLayout()
        self.cb_map = QtWidgets.QComboBox()
        self.cb_map.currentIndexChanged.connect(self._refresh_spots)
        top_sp.addWidget(QtWidgets.QLabel("Map:"))
        top_sp.addWidget(self.cb_map)
        self.cb_spot = QtWidgets.QComboBox()
        self.cb_spot.currentIndexChanged.connect(self._refresh_spawn_table)
        top_sp.addWidget(QtWidgets.QLabel("Spot:"))
        top_sp.addWidget(self.cb_spot)
        btn_new_spot = QtWidgets.QPushButton("New Spot")
        btn_new_spot.clicked.connect(self.new_spot)
        top_sp.addWidget(btn_new_spot)
        btn_del_spot = QtWidgets.QPushButton("Delete Spot")
        btn_del_spot.clicked.connect(self.delete_spot)
        top_sp.addWidget(btn_del_spot)
        sp_layout.addLayout(top_sp)

        # Spawn table
        self.table_spawns = QtWidgets.QTableWidget()
        cols = ["Index","Name","Count","StartX","StartY","EndX","EndY","Distance","Dir","Value"]
        self.table_spawns.setColumnCount(len(cols))
        self.table_spawns.setHorizontalHeaderLabels(cols)
        self.table_spawns.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        # allow inline editing (double-click) and single-click selection
        self.table_spawns.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.SelectedClicked)
        # context menu for spawns table
        self.table_spawns.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table_spawns.customContextMenuRequested.connect(self._spawns_context_menu)
        sp_layout.addWidget(self.table_spawns)

        # Map preview dock
        self.map_dock = QtWidgets.QDockWidget('Map Preview', self)
        self.map_dock.setObjectName('mapPreviewDock')
        # create container with toolbar above canvas
        dock_widget = QtWidgets.QWidget()
        dock_layout = QtWidgets.QVBoxLayout(dock_widget)
        ctrl_layout = QtWidgets.QHBoxLayout()
        btn_zoom_in = QtWidgets.QPushButton('+')
        btn_zoom_out = QtWidgets.QPushButton('-')
        btn_zoom_reset = QtWidgets.QPushButton('Reset')
        btn_fit = QtWidgets.QPushButton('Fit')
        ctrl_layout.addWidget(btn_zoom_out)
        ctrl_layout.addWidget(btn_zoom_in)
        ctrl_layout.addWidget(btn_zoom_reset)
        ctrl_layout.addWidget(btn_fit)
        ctrl_layout.addStretch()
        dock_layout.addLayout(ctrl_layout)
        # maps info row
        maps_info_layout = QtWidgets.QHBoxLayout()
        self.lbl_maps_info = QtWidgets.QLabel('Maps: (not configured)')
        btn_show_maps = QtWidgets.QPushButton('Show maps')
        maps_info_layout.addWidget(self.lbl_maps_info)
        maps_info_layout.addStretch()
        maps_info_layout.addWidget(btn_show_maps)
        dock_layout.addLayout(maps_info_layout)
        self.map_canvas = MapCanvas(self)
        dock_layout.addWidget(self.map_canvas)
        self.map_dock.setWidget(dock_widget)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.map_dock)
        # connect controls
        btn_zoom_in.clicked.connect(lambda: (setattr(self.map_canvas, 'zoom', min(8.0, self.map_canvas.zoom * 1.25)), self.map_canvas.update(), self.statusBar().showMessage(f'Zoom {self.map_canvas.zoom:.2f}',1000)))
        btn_zoom_out.clicked.connect(lambda: (setattr(self.map_canvas, 'zoom', max(0.1, self.map_canvas.zoom / 1.25)), self.map_canvas.update(), self.statusBar().showMessage(f'Zoom {self.map_canvas.zoom:.2f}',1000)))
        btn_zoom_reset.clicked.connect(lambda: (setattr(self.map_canvas, 'zoom', 1.0), setattr(self.map_canvas, 'pan_x', 0), setattr(self.map_canvas, 'pan_y', 0), self.map_canvas.update(), self.statusBar().showMessage('Zoom reset',1000)))
        btn_fit.clicked.connect(lambda: (self._fit_map_preview(), self.statusBar().showMessage('Fit to view',1000)))
        btn_show_maps.clicked.connect(self.show_maps_list)

        # MonsterList editor on the right
        right_h = QtWidgets.QHBoxLayout()
        sp_layout.addLayout(right_h)
        self.text_monsterlist = QtWidgets.QPlainTextEdit()
        self.text_monsterlist.setPlaceholderText("MonsterList.xml content (editable). Use Regenerate to overwrite with data from Monster.txt")
        self.text_monsterlist.setMinimumWidth(420)
        right_h.addWidget(self.text_monsterlist, stretch=3)

        ml_btns = QtWidgets.QVBoxLayout()
        btn_reload_ml = QtWidgets.QPushButton("Reload MonsterList.xml")
        btn_reload_ml.clicked.connect(self.reload_monsterlist_text)
        ml_btns.addWidget(btn_reload_ml)
        btn_save_ml = QtWidgets.QPushButton("Save MonsterList.xml")
        btn_save_ml.clicked.connect(self.save_monsterlist_text)
        ml_btns.addWidget(btn_save_ml)
        btn_regen_ml = QtWidgets.QPushButton("Regenerate from Monster.txt")
        btn_regen_ml.clicked.connect(self.regen_monster_list)
        ml_btns.addWidget(btn_regen_ml)
        ml_btns.addStretch()
        right_h.addLayout(ml_btns)

        # buttons for spawns
        bot_sp = QtWidgets.QHBoxLayout()
        btn_add_spawn = QtWidgets.QPushButton("Add Spawn")
        btn_add_spawn.clicked.connect(self.add_spawn)
        bot_sp.addWidget(btn_add_spawn)
        btn_edit_spawn = QtWidgets.QPushButton("Edit Spawn")
        btn_edit_spawn.clicked.connect(self.edit_spawn)
        bot_sp.addWidget(btn_edit_spawn)
        btn_del_spawn = QtWidgets.QPushButton("Delete Spawn")
        btn_del_spawn.clicked.connect(self.delete_spawn)
        bot_sp.addWidget(btn_del_spawn)
        btn_bulk = QtWidgets.QPushButton("Bulk Edit...")
        btn_bulk.clicked.connect(self.bulk_edit_spawns)
        bot_sp.addWidget(btn_bulk)
        bot_sp.addStretch()
        btn_save_spawn = QtWidgets.QPushButton("Save MonsterSpawn.xml")
        btn_save_spawn.clicked.connect(self.save_spawn_xml)
        bot_sp.addWidget(btn_save_spawn)
        sp_layout.addLayout(bot_sp)

        # connect selection change to update canvas
        self.table_spawns.itemSelectionChanged.connect(self._on_spawn_selection_changed)

        # warnings area
        self.warnings = QtWidgets.QListWidget()
        v.addWidget(QtWidgets.QLabel("Warnings:"))
        v.addWidget(self.warnings)

        # menu: Theme selection
        men = self.menuBar()
        view = men.addMenu("View")
        theme_menu = view.addMenu("Theme")
        self.theme_group = QtGui.QActionGroup(self)
        act_light = QtGui.QAction("Light", self, checkable=True)
        act_dark = QtGui.QAction("Dark", self, checkable=True)
        self.theme_group.addAction(act_light)
        self.theme_group.addAction(act_dark)
        theme_menu.addAction(act_light)
        theme_menu.addAction(act_dark)
        act_light.triggered.connect(lambda: self.apply_theme('light'))
        act_dark.triggered.connect(lambda: self.apply_theme('dark'))
        # set initial checked based on settings (loaded later)

        # Snapshots and autosave
        act_snaps = view.addAction('Snapshots...')
        act_snaps.triggered.connect(self.open_snapshots_browser)
        act_maps = view.addAction('Maps folders...')
        act_maps.triggered.connect(self.set_maps_folders)
        view.addSeparator()
        self.act_autosave = QtGui.QAction('Autosave (every 300s)', self, checkable=True)
        self.act_autosave.setChecked(False)
        self.act_autosave.triggered.connect(lambda checked: self.toggle_autosave(checked))
        view.addAction(self.act_autosave)
        act_interval = view.addAction('Set autosave interval...')
        act_interval.triggered.connect(self.set_autosave_interval)

        # autosave timer
        self.autosave_timer = QtCore.QTimer(self)
        self.autosave_timer.timeout.connect(self._autosave_tick)
        self.autosave_interval = 300
        self.autosave_enabled = False

        # Shortcuts / Actions
        act_undo = QtGui.QAction('Undo', self)
        act_undo.setShortcut('Ctrl+Z')
        act_undo.triggered.connect(self.do_undo)
        self.addAction(act_undo)
        act_redo = QtGui.QAction('Redo', self)
        act_redo.setShortcut('Ctrl+Y')
        act_redo.triggered.connect(self.do_redo)
        self.addAction(act_redo)
        act_save = QtGui.QAction('SaveAll', self)
        act_save.setShortcut('Ctrl+S')
        act_save.triggered.connect(self.save_all)
        self.addAction(act_save)
        act_find = QtGui.QAction('Find', self)
        act_find.setShortcut('Ctrl+F')
        act_find.triggered.connect(lambda: self.filter_edit.setFocus())
        self.addAction(act_find)

    def open_folder(self):
        dlg = QtWidgets.QFileDialog(self)
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        if dlg.exec() != QtWidgets.QFileDialog.Accepted:
            return
        folder = dlg.selectedFiles()[0]
        self.load_folder(folder)

    def load_folder(self, folder: str):
        self.folder = folder
        self.lbl_folder.setText(folder)
        self.monster_txt_path = os.path.join(folder, "Monster.txt")
        self.monster_list_xml_path = os.path.join(folder, "MonsterList.xml")
        self.monster_spawn_xml_path = os.path.join(folder, "MonsterSpawn.xml")
        for p in (self.monster_txt_path, self.monster_list_xml_path, self.monster_spawn_xml_path):
            if not os.path.exists(p):
                QtWidgets.QMessageBox.critical(self, "Missing files", f"Missing: {p}")
                return
        try:
            mons, lines, enc = parse_monster_txt(self.monster_txt_path)
            self.monsters = mons
            self.monster_lines = lines
            self.monster_encoding = enc
            model = MonsterTableModel(self.monsters)
            self.proxy = QtCore.QSortFilterProxyModel(self)
            self.proxy.setSourceModel(model)
            self.view_mon.setModel(self.proxy)
            self.model = model

            # selection settings
            self.view_mon.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
            self.view_mon.setSelectionMode(QtWidgets.QTableView.SingleSelection)
            self.view_mon.selectionModel().selectionChanged.connect(self.on_selection_changed)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load Monster.txt: {e}")
            return
        try:
            self.spawn_tree = parse_monster_spawn_xml(self.monster_spawn_xml_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load MonsterSpawn.xml: {e}")
            self.spawn_tree = None
        # build helper map
        self.monster_by_index = {m["Index"]: m.get("Name", "") for m in self.monsters}
        # push initial state onto history
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        # refresh spawn UI
        self._refresh_maps()
        self._refresh_spots()
        self._refresh_spawn_table()
        # load MonsterList.xml into editor area (if present)
        try:
            with open(self.monster_list_xml_path, 'r', encoding='utf-8', errors='replace') as f:
                txt = f.read()
        except Exception:
            txt = ''
        self.text_monsterlist.setPlainText(txt)
        self.update_warnings()
        # clear any loaded setbase table
        self._setbase_entries = []
        self.table_setbase.setRowCount(0)

    def _filter_monsters(self, text):
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.proxy.setFilterFixedString(text)

    def _snapshot_state(self):
        snap = {
            'monsters': [dict(m) for m in self.monsters],
            'spawn_xml': ''
        }
        if self.spawn_tree is not None:
            try:
                snap['spawn_xml'] = ET.tostring(self.spawn_tree.getroot(), encoding='unicode')
            except Exception:
                snap['spawn_xml'] = ''
        return snap

    def _restore_snapshot(self, snap: dict):
        if 'monsters' in snap:
            self.monsters = [dict(m) for m in snap['monsters']]
            try:
                self.model.load(self.monsters)
            except Exception:
                pass
        if snap.get('spawn_xml'):
            try:
                root = ET.fromstring(snap['spawn_xml'])
                self.spawn_tree = ET.ElementTree(element=root)
            except Exception:
                pass
        # rebuild helper map and UI
        self.monster_by_index = {m['Index']: m.get('Name','') for m in self.monsters}
        self._refresh_maps()
        self._refresh_spots()
        self._refresh_spawn_table()

    # ---------------- SetBase helpers ----------------
    def open_setbase_file(self):
        dlg = QtWidgets.QFileDialog(self)
        dlg.setNameFilter("Text files (*.txt);;All files (*)")
        if dlg.exec() != QtWidgets.QFileDialog.Accepted:
            return
        path = dlg.selectedFiles()[0]
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to open SetBase: {e}")
            return
        entries = []
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith('//'):
                continue
            cleaned = strip_inline_comment(ln)
            if not cleaned.strip():
                continue
            toks = cleaned.split()
            # expect at least 6 tokens
            if len(toks) < 6:
                continue
            try:
                monster = int(toks[0])
            except Exception:
                continue
            mapnum = toks[1]
            rng = toks[2]
            px = toks[3] if len(toks) > 3 else '0'
            py = toks[4] if len(toks) > 4 else '0'
            dirv = toks[5] if len(toks) > 5 else '0'
            comment = ''
            # if there's a trailing comment after //, strip_inline_comment removed it; try last tok if startswith('//')
            if '//' in ln:
                try:
                    comment = ln.split('//',1)[1].strip()
                except Exception:
                    comment = ''
            entries.append((monster, mapnum, rng, px, py, dirv, comment))
        self._setbase_entries = entries
        self._refresh_setbase_table()

    def _refresh_setbase_table(self):
        self.table_setbase.setRowCount(0)
        for ent in self._setbase_entries:
            r = self.table_setbase.rowCount()
            self.table_setbase.insertRow(r)
            for c, v in enumerate(ent):
                it = QtWidgets.QTableWidgetItem(str(v))
                self.table_setbase.setItem(r, c, it)

    def _filter_setbase(self, txt: str):
        txt = txt.strip().lower()
        self.table_setbase.setRowCount(0)
        for ent in self._setbase_entries:
            if not txt or txt in str(ent[0]).lower() or txt in str(ent[6]).lower():
                r = self.table_setbase.rowCount()
                self.table_setbase.insertRow(r)
                for c, v in enumerate(ent):
                    self.table_setbase.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))

    def import_selected_setbase(self):
        if not self.spawn_tree:
            QtWidgets.QMessageBox.information(self, "No spawns", "Load a Monster folder first (with MonsterSpawn.xml).")
            return
        # snapshot
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        sel = self.table_setbase.selectionModel().selectedRows()
        if not sel:
            QtWidgets.QMessageBox.information(self, "Select", "Select rows to import.")
            return
        root = self.spawn_tree.getroot()
        # group spawns by map -> ensure a Spot exists per map (Description=Imported)
        for idx in sel:
            row = idx.row()
            monster = int(self.table_setbase.item(row,0).text())
            mapnum = int(self.table_setbase.item(row,1).text())
            # find or create map
            mp = None
            for m in root.findall('Map'):
                try:
                    if int(m.get('Number','-9999')) == mapnum:
                        mp = m
                        break
                except Exception:
                    continue
            if mp is None:
                mp = ET.SubElement(root, 'Map')
                mp.set('Number', str(mapnum))
                mp.set('Name', f'Map{mapnum}')
            # find a spot with Description 'Imported' or create one
            spot = None
            for s in mp.findall('Spot'):
                if s.get('Description','') == 'Imported SetBase':
                    spot = s
                    break
            if spot is None:
                spot = ET.SubElement(mp, 'Spot')
                spot.set('Type', '0')
                spot.set('Description', 'Imported SetBase')
            # create spawn
            se = ET.SubElement(spot, 'Spawn')
            se.set('Index', str(monster))
            se.set('Count', '1')
        self._refresh_spots()
        self._refresh_spawn_table()
        QtWidgets.QMessageBox.information(self, 'Imported', 'Selected SetBase rows imported into MonsterSpawn.xml (unsaved).')
        self.update_warnings()

    def sync_setbase(self):
        if not hasattr(self, '_setbase_entries') or not self._setbase_entries:
            QtWidgets.QMessageBox.information(self, 'No data', 'No SetBase data loaded to sync.')
            return
        try:
            # write a suggestion file in app backups
            outp = os.path.join(os.path.dirname(__file__), 'backups', f'SetBase_suggest_{QtCore.QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")}.txt')
            os.makedirs(os.path.dirname(outp), exist_ok=True)
            with open(outp, 'w', encoding='utf-8') as f:
                for ent in sorted(self._setbase_entries, key=lambda e: (int(e[1]) if str(e[1]).isdigit() else 0, int(e[0]))):
                    line = f"{ent[0]:<4} {ent[1]:<4} {ent[2]:<4} {ent[3]:<4} {ent[4]:<4} {ent[5]:<2} // {ent[6]}\n"
                    f.write(line)
            QtWidgets.QMessageBox.information(self, 'Synced', f'SetBase suggestion written to {outp}')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Error', str(e))

    # ---------------- spawn helpers ----------------
    def _refresh_maps(self):
        self.cb_map.clear()
        if not self.spawn_tree:
            return
        root = self.spawn_tree.getroot()
        maps = []
        for mp in root.findall("Map"):
            num = mp.get("Number", "")
            name = mp.get("Name", "")
            try:
                nnum = int(num)
            except Exception:
                nnum = -9999
            maps.append((nnum, name))
        maps.sort(key=lambda x: x[0])
        for n, nm in maps:
            self.cb_map.addItem(f"{n} - {nm}", n)

    def _refresh_spots(self):
        self.cb_spot.clear()
        if not self.spawn_tree:
            return
        if self.cb_map.currentIndex() < 0:
            return
        map_num = self.cb_map.currentData()
        mp_elem = None
        for mp in self.spawn_tree.getroot().findall("Map"):
            try:
                if int(mp.get("Number", "-9999")) == int(map_num):
                    mp_elem = mp
                    break
            except Exception:
                continue
        if mp_elem is None:
            return
        spots = mp_elem.findall("Spot")
        for i, sp in enumerate(spots, start=1):
            typ = sp.get("Type", "?")
            desc = sp.get("Description", "")
            self.cb_spot.addItem(f"{i:02d}. Type={typ}  {desc}", i-1)
        # Attempt to load a matching map preview (ClientMaps / ServerSideTerrain)
        try:
            self._load_map_preview()
        except Exception:
            pass

    def _selected_spot_elem(self):
        if not self.spawn_tree:
            return None
        if self.cb_map.currentIndex() < 0 or self.cb_spot.currentIndex() < 0:
            return None
        map_num = self.cb_map.currentData()
        mp_elem = None
        for mp in self.spawn_tree.getroot().findall("Map"):
            try:
                if int(mp.get("Number", "-9999")) == int(map_num):
                    mp_elem = mp
                    break
            except Exception:
                continue
        if mp_elem is None:
            return None
        spot_idx = int(self.cb_spot.currentData())
        spots = mp_elem.findall("Spot")
        if 0 <= spot_idx < len(spots):
            return spots[spot_idx]
        return None

    def _find_map_file(self, map_num: int, map_name: str | None) -> str | None:
        """Heuristic: look for several candidate filenames under the opened folder
        and under the packaged module directory. Returns path or None."""
        candidates = []
        if self.folder:
            cm = os.path.join(self.folder, 'ClientMaps')
            ss = os.path.join(self.folder, 'ServerSideTerrain')
            candidates += [os.path.join(cm, f'Map_{map_num}.ozt'),
                           os.path.join(cm, f'Map_{map_num}.ozj'),
                           os.path.join(cm, f'Map_{map_num}.ozt')]
            if map_name:
                candidates += [os.path.join(cm, f'{map_name}.ozt'), os.path.join(ss, f'{map_name}.att')]
            candidates += [os.path.join(ss, f'Terrain{map_num}.att'), os.path.join(ss, f'Terrain{map_num}.ATT')]
        # also check module-local fallbacks (in case assets live inside the app folder)
        base = os.path.dirname(__file__)
        candidates += [os.path.join(base, 'ClientMaps', f'Map_{map_num}.ozt'),
                       os.path.join(base, 'ServerSideTerrain', f'Terrain{map_num}.att')]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return None

    def _find_map_pair(self, map_num: int, map_name: str | None) -> tuple[str | None, str | None]:
        """Return (terrain_path, client_path) if found (either may be None)."""
        terrain = None
        client = None
        # check user-configured maps folders first (QSettings)
        settings = QtCore.QSettings('Phantasm', 'Phantasm LTP Monster Editor')
        user_client = settings.value('maps/client', '') or ''
        user_server = settings.value('maps/server', '') or ''
        if user_client or user_server:
            cm = user_client
            ss = user_server
            if cm:
                for fn in (f'Map_{map_num}.ozt', f'Map_{map_num}.ozj', (f'{map_name}.ozt' if map_name else None)):
                    if fn:
                        p = os.path.join(cm, fn)
                        if os.path.exists(p):
                            client = p
                            break
            if ss:
                for fn in (f'Terrain{map_num}.att', f'Terrain{map_num}.ATT', (f'{map_name}.att' if map_name else None)):
                    if fn:
                        p = os.path.join(ss, fn)
                        if os.path.exists(p):
                            terrain = p
                            break
            # if we found both, return early
            if terrain or client:
                return terrain, client
        # fallback to maps inside the loaded folder
        if self.folder:
            cm = os.path.join(self.folder, 'ClientMaps')
            ss = os.path.join(self.folder, 'ServerSideTerrain')
            # client candidates
            for fn in (f'Map_{map_num}.ozt', f'Map_{map_num}.ozj', (f'{map_name}.ozt' if map_name else None)):
                if fn:
                    p = os.path.join(cm, fn)
                    if os.path.exists(p):
                        client = p
                        break
            # terrain candidates
            for fn in (f'Terrain{map_num}.att', f'Terrain{map_num}.ATT', (f'{map_name}.att' if map_name else None)):
                if fn:
                    p = os.path.join(ss, fn)
                    if os.path.exists(p):
                        terrain = p
                        break
        # also check module-local
        base = os.path.dirname(__file__)
        if not client:
            cands = [os.path.join(base, 'ClientMaps', f'Map_{map_num}.ozt'), os.path.join(base, 'ClientMaps', f'{map_name}.ozt' if map_name else '')]
            for c in cands:
                if c and os.path.exists(c):
                    client = c; break
        if not terrain:
            t = os.path.join(base, 'ServerSideTerrain', f'Terrain{map_num}.att')
            if os.path.exists(t):
                terrain = t
        return terrain, client

    def set_maps_folders(self):
        """Prompt the user to choose custom ClientMaps and ServerSideTerrain folders and persist them."""
        settings = QtCore.QSettings('Phantasm', 'Phantasm LTP Monster Editor')
        cur_client = settings.value('maps/client', '') or ''
        cur_server = settings.value('maps/server', '') or ''
        # choose client maps
        dlg = QtWidgets.QFileDialog(self)
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        dlg.setWindowTitle('Select ClientMaps folder (cancel to keep current)')
        if cur_client and os.path.exists(cur_client):
            dlg.setDirectory(cur_client)
        if dlg.exec() == QtWidgets.QFileDialog.Accepted:
            new_client = dlg.selectedFiles()[0]
            settings.setValue('maps/client', new_client)
            self.statusBar().showMessage(f'ClientMaps set to {new_client}', 3000)
        # choose server terrain
        dlg2 = QtWidgets.QFileDialog(self)
        dlg2.setFileMode(QtWidgets.QFileDialog.Directory)
        dlg2.setWindowTitle('Select ServerSideTerrain folder (cancel to keep current)')
        if cur_server and os.path.exists(cur_server):
            dlg2.setDirectory(cur_server)
        if dlg2.exec() == QtWidgets.QFileDialog.Accepted:
            new_server = dlg2.selectedFiles()[0]
            settings.setValue('maps/server', new_server)
            self.statusBar().showMessage(f'ServerSideTerrain set to {new_server}', 3000)

    def _load_map_preview(self):
        if self.cb_map.currentIndex() < 0:
            self.map_canvas.set_background_image(None)
            return
        map_num = self.cb_map.currentData()
        # attempt to extract name from current text (format: 'N - Name')
        txt = self.cb_map.currentText() or ''
        name = None
        if ' - ' in txt:
            try:
                name = txt.split(' - ', 1)[1].strip()
            except Exception:
                name = None
        terrain_path, client_path = self._find_map_pair(map_num, name)
        if terrain_path or client_path:
            ok = self.map_canvas.load_map_pair(terrain_path, client_path)
            if ok:
                try:
                    parts = []
                    if terrain_path:
                        parts.append(os.path.basename(terrain_path))
                    if client_path:
                        parts.append(os.path.basename(client_path))
                    self.statusBar().showMessage(f'Loaded map preview: {" + ".join(parts)}')
                except Exception:
                    pass
            else:
                self.map_canvas.set_background_image(None)
                try:
                    self.statusBar().showMessage('Failed to render composite map', 4000)
                except Exception:
                    pass
        else:
            self.map_canvas.set_background_image(None)
            try:
                self.statusBar().showMessage('No map file found for preview', 3000)
            except Exception:
                pass
        # update maps info label
        try:
            self.update_maps_info()
        except Exception:
            pass

    def update_maps_info(self):
        settings = QtCore.QSettings('Phantasm', 'Phantasm LTP Monster Editor')
        user_client = settings.value('maps/client', '') or ''
        user_server = settings.value('maps/server', '') or ''
        parts = []
        if user_client:
            parts.append(f'Client: {user_client}')
        if user_server:
            parts.append(f'Server: {user_server}')
        if not parts and self.folder:
            parts.append(f'Using folder: {self.folder}/ClientMaps and ServerSideTerrain')
        if not parts:
            txt = 'Maps: none'
        else:
            txt = ' | '.join(parts)
        if hasattr(self, 'lbl_maps_info'):
            self.lbl_maps_info.setText(txt)

    def show_maps_list(self):
        # collect candidate map files from configured folders and current folder
        settings = QtCore.QSettings('Phantasm', 'Phantasm LTP Monster Editor')
        user_client = settings.value('maps/client', '') or ''
        user_server = settings.value('maps/server', '') or ''
        files = []
        def list_dir(p):
            try:
                return [os.path.join(p, f) for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))]
            except Exception:
                return []
        if user_client and os.path.exists(user_client):
            files += list_dir(user_client)
        if user_server and os.path.exists(user_server):
            files += list_dir(user_server)
        if self.folder:
            c1 = os.path.join(self.folder, 'ClientMaps')
            s1 = os.path.join(self.folder, 'ServerSideTerrain')
            if os.path.exists(c1):
                files += list_dir(c1)
            if os.path.exists(s1):
                files += list_dir(s1)
        # also include packaged module-local maps (bundled with app)
        base = os.path.dirname(__file__)
        mod_cm = os.path.join(base, 'ClientMaps')
        mod_ss = os.path.join(base, 'ServerSideTerrain')
        if os.path.exists(mod_cm):
            files += list_dir(mod_cm)
        if os.path.exists(mod_ss):
            files += list_dir(mod_ss)
        files = sorted(set(files))
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle('Available map files')
        v = QtWidgets.QVBoxLayout(dlg)
        lw = QtWidgets.QListWidget()
        for f in files:
            lw.addItem(f)
        v.addWidget(lw)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        dlg.resize(600, 400)
        dlg.exec()

    def _fit_map_preview(self):
        # scale map_canvas zoom so the image fits inside available area
        info = getattr(self.map_canvas, '_map_info', None)
        if not info:
            return
        w = info.get('width')
        h = info.get('height')
        if not w or not h:
            return
        # compute scale to fit within widget rect (approx)
        rect = self.map_canvas.rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        # consider padding used in paintEvent (12px each side)
        pad = 12
        avail_w = max(1, rect.width() - pad*2)
        avail_h = max(1, rect.height() - pad*2)
        scale_x = avail_w / w
        scale_y = avail_h / h
        new_zoom = min(scale_x, scale_y)
        # clamp
        new_zoom = max(0.1, min(8.0, new_zoom))
        self.map_canvas.zoom = new_zoom
        self.map_canvas.pan_x = 0
        self.map_canvas.pan_y = 0
        self.map_canvas.update()

    def _refresh_spawn_table(self):
        self.table_spawns.setRowCount(0)
        sp = self._selected_spot_elem()
        if sp is None:
            return
        unknown = 0
        for node in sp.findall("Spawn"):
            idx = node.get("Index", "")
            name = ""
            if idx.isdigit():
                name = self.monster_by_index.get(int(idx), "")
            if not name:
                name = "(unknown)"
                unknown += 1
            values = [
                idx,
                name,
                node.get("Count", ""),
                node.get("StartX", ""),
                node.get("StartY", ""),
                node.get("EndX", ""),
                node.get("EndY", ""),
                node.get("Distance", ""),
                node.get("Dir", ""),
                node.get("Value", ""),
            ]
            r = self.table_spawns.rowCount()
            self.table_spawns.insertRow(r)
            for c, val in enumerate(values):
                it = QtWidgets.QTableWidgetItem(str(val))
                if val == "(unknown)":
                    it.setForeground(QtGui.QBrush(QtGui.QColor('#a00')))
                self.table_spawns.setItem(r, c, it)
        # update warnings list
        self.update_warnings()
        # update map preview with spawn centers
        spawns = []
        for node in sp.findall('Spawn'):
            try:
                sx = int(node.get('StartX', node.get('X','0')) or 0)
                sy = int(node.get('StartY', node.get('Y','0')) or 0)
            except Exception:
                try:
                    sx = int(node.get('X','0'))
                    sy = int(node.get('Y','0'))
                except Exception:
                    sx = 0; sy = 0
            idx = node.get('Index','')
            name = self.monster_by_index.get(int(idx), '') if idx.isdigit() else ''
            spawns.append((sx, sy, name))
        if hasattr(self, 'map_canvas'):
            self.map_canvas.set_spawns(spawns)

    def add_spawn(self):
        sp = self._selected_spot_elem()
        if sp is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a map and spot first.")
            return
        # snapshot before change
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        choices = [(m["Index"], m.get("Name", "")) for m in self.monsters]
        dlg = SpawnDialog(self, choices, initial=None)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        data = dlg.result
        sp_elem = sp
        selem = ET.SubElement(sp_elem, "Spawn")
        selem.set("Index", str(data.get("Index", 0)))
        for k, v in data.items():
            if k == "Index":
                continue
            selem.set(k, str(v))
        self._refresh_spawn_table()

    def _find_map_elem(self, map_num: int):
        if not self.spawn_tree:
            return None
        root = self.spawn_tree.getroot()
        for mp in root.findall("Map"):
            try:
                if int(mp.get("Number", "-9999")) == int(map_num):
                    return mp
            except Exception:
                continue
        return None

    def new_spot(self):
        if self.cb_map.currentIndex() < 0:
            QtWidgets.QMessageBox.information(self, "Select", "Select a map first.")
            return
        map_num = self.cb_map.currentData()
        mp = self._find_map_elem(map_num)
        if mp is None:
            QtWidgets.QMessageBox.information(self, "Missing", "Map not found in XML.")
            return
        # prompt for type and description
        t, ok = QtWidgets.QInputDialog.getInt(self, "New Spot", "Type (numeric):", 1, 0, 9999)
        if not ok:
            return
        desc, ok = QtWidgets.QInputDialog.getText(self, "New Spot", "Description:", text="New Spot")
        if not ok:
            return
        # snapshot
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        sp = ET.SubElement(mp, "Spot")
        sp.set("Type", str(t))
        sp.set("Description", str(desc))
        self._refresh_spots()
        # select last spot
        idx = self.cb_spot.count() - 1
        if idx >= 0:
            self.cb_spot.setCurrentIndex(idx)

    def delete_spot(self):
        sp = self._selected_spot_elem()
        if sp is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a spot first.")
            return
        if QtWidgets.QMessageBox.question(self, "Confirm", "Delete selected spot (and all its spawns)?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return
        # snapshot
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        # find parent map and remove spot
        parent = sp.getparent() if hasattr(sp, 'getparent') else None
        if parent is None:
            # fallback: find via iterating maps
            for mp in self.spawn_tree.getroot().findall("Map"):
                spots = mp.findall("Spot")
                for s in spots:
                    if s is sp:
                        mp.remove(s)
                        break
        else:
            parent.remove(sp)
        self._refresh_spots()
        self._refresh_spawn_table()

    def edit_spawn(self):
        sp = self._selected_spot_elem()
        if sp is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a map and spot first.")
            return
        sel = self.table_spawns.currentRow()
        if sel < 0:
            QtWidgets.QMessageBox.information(self, "Select", "Select a spawn row first.")
            return
        nodes = sp.findall("Spawn")
        if sel >= len(nodes):
            return
        node = nodes[sel]
        initial = {k: node.get(k) for k in ["Index","Count","StartX","StartY","EndX","EndY","Distance","Dir","Value"] if node.get(k) is not None}
        choices = [(m["Index"], m.get("Name", "")) for m in self.monsters]
        dlg = SpawnDialog(self, choices, initial=initial)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        # snapshot before edit
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        data = dlg.result
        # replace attributes
        node.attrib.clear()
        node.set("Index", str(data.get("Index", 0)))
        for k, v in data.items():
            if k == "Index":
                continue
            node.set(k, str(v))
        self._refresh_spawn_table()

    def _on_spawn_selection_changed(self):
        sel = self.table_spawns.currentRow()
        if sel is None:
            return
        # notify canvas
        if hasattr(self, 'map_canvas'):
            self.map_canvas.select_index(sel)

    def on_map_selected(self, idx: int):
        # user clicked on the map; select the corresponding table row
        if idx is None:
            return
        if 0 <= idx < self.table_spawns.rowCount():
            self.table_spawns.selectRow(idx)

    def on_map_move_preview(self, idx: int, newx: int, newy: int):
        # optional preview handler - currently no-op but could show temporary marker
        pass

    def on_map_move(self, idx: int, newx: int, newy: int):
        # update the underlying spawn XML for the selected spot
        sp = self._selected_spot_elem()
        if sp is None:
            return
        nodes = sp.findall('Spawn')
        if idx < 0 or idx >= len(nodes):
            return
        # snapshot
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        node = nodes[idx]
        # prefer StartX/StartY if present else X/Y
        if node.get('StartX') is not None:
            node.set('StartX', str(newx))
            node.set('StartY', str(newy))
        else:
            node.set('X', str(newx))
            node.set('Y', str(newy))
        # refresh table and map
        self._refresh_spawn_table()
        QtWidgets.QMessageBox.information(self, 'Moved', f'Spawn {idx} moved to ({newx},{newy}) (unsaved).')

    def open_snapshots_browser(self):
        dlg = SnapshotBrowser(self)
        dlg.exec()

    # ---------------- autosave handlers ----------------
    def toggle_autosave(self, checked: bool):
        self.autosave_enabled = bool(checked)
        if self.autosave_enabled:
            # start timer
            self.autosave_timer.start(int(self.autosave_interval * 1000))
            self.statusBar().showMessage(f'Autosave enabled ({self.autosave_interval}s)', 3000)
        else:
            self.autosave_timer.stop()
            self.statusBar().showMessage('Autosave disabled', 2000)
        # update action text
        try:
            self.act_autosave.setText(f'Autosave (every {self.autosave_interval}s)')
            self.act_autosave.setChecked(self.autosave_enabled)
        except Exception:
            pass

    def set_autosave_interval(self):
        val, ok = QtWidgets.QInputDialog.getInt(self, 'Autosave interval', 'Seconds between autosaves:', value=int(self.autosave_interval), min=10, max=86400)
        if not ok:
            return
        self.autosave_interval = int(val)
        # restart timer if enabled
        if self.autosave_enabled:
            self.autosave_timer.start(int(self.autosave_interval * 1000))
        try:
            self.act_autosave.setText(f'Autosave (every {self.autosave_interval}s)')
        except Exception:
            pass

    def _autosave_tick(self):
        # perform a snapshot push to history which also writes a snapshot file
        try:
            snap = self._snapshot_state()
            self.history.push(snap)
            self.statusBar().showMessage('Autosaved snapshot', 1500)
        except Exception:
            # don't crash on autosave errors
            pass

    # Undo / Redo
    def do_undo(self):
        cur = self._snapshot_state()
        snap = None
        try:
            snap = self.history.undo(cur)
        except Exception:
            snap = None
        if snap is None:
            QtWidgets.QMessageBox.information(self, 'Undo', 'Nothing to undo')
            return
        self._restore_snapshot(snap)

    def do_redo(self):
        cur = self._snapshot_state()
        snap = None
        try:
            snap = self.history.redo(cur)
        except Exception:
            snap = None
        if snap is None:
            QtWidgets.QMessageBox.information(self, 'Redo', 'Nothing to redo')
            return
        self._restore_snapshot(snap)

    # Context menus
    def _monsters_context_menu(self, pt: QtCore.QPoint):
        idxs = self.view_mon.selectionModel().selectedRows()
        menu = QtWidgets.QMenu(self)
        act_dup = menu.addAction('Duplicate')
        act_del = menu.addAction('Delete')
        act_copy = menu.addAction('Copy as line')
        a = menu.exec(self.view_mon.viewport().mapToGlobal(pt))
        if a == act_dup:
            self.dup_monster()
        elif a == act_del:
            self.del_monster()
        elif a == act_copy:
            r = self.get_selected_source_row()
            if r is not None:
                mons = self.model.to_monsters()
                line = ','.join(str(mons[r].get(f,'')) for f,_ in MONSTER_FIELDS)
                QtWidgets.QApplication.clipboard().setText(line)

    def _spawns_context_menu(self, pt: QtCore.QPoint):
        menu = QtWidgets.QMenu(self)
        act_edit = menu.addAction('Edit')
        act_dup = menu.addAction('Duplicate')
        act_bulk = menu.addAction('Bulk Edit...')
        act_del = menu.addAction('Delete')
        act_export = menu.addAction('Export row')
        a = menu.exec(self.table_spawns.viewport().mapToGlobal(pt))
        if a == act_edit:
            self.edit_spawn()
        elif a == act_dup:
            sel = self.table_spawns.currentRow()
            sp = self._selected_spot_elem()
            if sp is None or sel < 0:
                return
            nodes = sp.findall('Spawn')
            if sel >= len(nodes):
                return
            try:
                self.history.push(self._snapshot_state())
            except Exception:
                pass
            src = nodes[sel]
            new = ET.SubElement(sp, 'Spawn')
            for k,v in src.attrib.items():
                new.set(k,v)
            self._refresh_spawn_table()
        elif a == act_del:
            self.delete_spawn()
        elif a == act_export:
            sel = self.table_spawns.currentRow()
            if sel < 0:
                return
            nodes = self._selected_spot_elem().findall('Spawn')
            if sel >= len(nodes):
                return
            node = nodes[sel]
            txt = ET.tostring(node, encoding='unicode')
            fname, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export Spawn', f'spawn_{sel}.xml', 'XML files (*.xml);;All files (*)')
            if fname:
                with open(fname, 'w', encoding='utf-8') as f:
                    f.write(txt)
        elif a == act_bulk:
            self.bulk_edit_spawns()

    def delete_spawn(self):
        sp = self._selected_spot_elem()
        if sp is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a map and spot first.")
            return
        sel = self.table_spawns.currentRow()
        if sel < 0:
            QtWidgets.QMessageBox.information(self, "Select", "Select a spawn row first.")
            return
        nodes = sp.findall("Spawn")
        if sel >= len(nodes):
            return
        if not QtWidgets.QMessageBox.question(self, "Confirm", "Delete selected spawn?", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes:
            return
        # snapshot
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        sp.remove(nodes[sel])
        self._refresh_spawn_table()

    def bulk_edit_spawns(self):
        sp = self._selected_spot_elem()
        if sp is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a map and spot first.")
            return
        sel_rows = sorted({idx.row() for idx in self.table_spawns.selectionModel().selectedRows()})
        if not sel_rows:
            QtWidgets.QMessageBox.information(self, "Select", "Select one or more spawn rows first.")
            return
        dlg = BulkSpawnDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        vals = dlg.values()
        # push snapshot
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        nodes = sp.findall('Spawn')
        # iterate rows in reverse order if deleting to preserve indices
        for r in (reversed(sel_rows) if vals['delete'] else sel_rows):
            if r < 0 or r >= len(nodes):
                continue
            node = nodes[r]
            # apply count
            if vals['count'] is not None:
                node.set('Count', str(vals['count']))
            # apply index offset
            if vals['offset'] != 0:
                idxv = node.get('Index','')
                if idxv.isdigit():
                    newi = int(idxv) + vals['offset']
                    node.set('Index', str(newi))
            # delete
            if vals['delete']:
                sp.remove(node)
        self._refresh_spawn_table()
        QtWidgets.QMessageBox.information(self, 'Bulk Edit', 'Bulk operation applied (unsaved).')

    def save_spawn_xml(self):
        if not self.spawn_tree:
            QtWidgets.QMessageBox.information(self, "No file", "Load a Monster folder first.")
            return
        try:
            save_monster_spawn_xml(self.monster_spawn_xml_path, self.spawn_tree)
            QtWidgets.QMessageBox.information(self, "Saved", "MonsterSpawn.xml saved (backup created).")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def new_monster(self):
        used = {m["Index"] for m in self.monsters}
        idx = 0
        while idx in used:
            idx += 1
        base = self.monsters[0].copy() if self.monsters else {f: 0 for f, _ in MONSTER_FIELDS}
        base["Index"] = idx
        base["Name"] = f"New Monster {idx}"
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        self.monsters.append(base)
        self.model.load(self.monsters)
        self.update_warnings()

    def dup_monster(self):
        src_row = self.get_selected_source_row()
        if src_row is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a row to duplicate")
            return
        src = self.model.to_monsters()[src_row]
        used = {m["Index"] for m in self.monsters}
        new_idx = 0
        while new_idx in used:
            new_idx += 1
        src["Index"] = new_idx
        src["Name"] = src.get("Name", "") + " (Copy)"
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        self.monsters.append(src)
        self.model.load(self.monsters)
        self.update_warnings()

    def del_monster(self):
        src_row = self.get_selected_source_row()
        if src_row is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a row to delete")
            return
        mons = self.model.to_monsters()
        idx = mons[src_row]["Index"]
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        self.monsters = [m for m in self.monsters if m["Index"] != idx]
        self.model.load(self.monsters)
        self.update_warnings()

    def apply_to_selected(self):
        src_row = self.get_selected_source_row()
        if src_row is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a row")
            return
        mons = self.model.to_monsters()
        idx = mons[src_row]["Index"]
        try:
            self.history.push(self._snapshot_state())
        except Exception:
            pass
        for field, _ in MONSTER_FIELDS:
            val = self.edit_fields[field].text()
            for m in self.monsters:
                if m["Index"] == idx:
                    if isinstance(m.get(field, 0), int):
                        try:
                            m[field] = int(val)
                        except Exception:
                            m[field] = 0
                    else:
                        m[field] = val
        self.model.load(self.monsters)
        self.update_warnings()

    def get_selected_source_row(self) -> int | None:
        sel = self.view_mon.selectionModel().selectedRows()
        if not sel:
            return None
        proxy_index = sel[0]
        src_index = self.proxy.mapToSource(proxy_index)
        return src_index.row()

    def on_selection_changed(self, selected, deselected):
        # populate right-hand form with selected monster values
        src_row = self.get_selected_source_row()
        if src_row is None:
            for field in self.edit_fields:
                self.edit_fields[field].setText("")
            return
        mons = self.model.to_monsters()
        if src_row < 0 or src_row >= len(mons):
            return
        m = mons[src_row]
        for field, _ in MONSTER_FIELDS:
            val = m.get(field, "")
            self.edit_fields[field].setText(str(val))

    def regen_monster_list(self):
        try:
            regenerate_monster_list_xml(self.monster_list_xml_path, self.monsters)
            QtWidgets.QMessageBox.information(self, "Done", "MonsterList.xml regenerated (backup created).")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))

    def reload_monsterlist_text(self):
        if not self.monster_list_xml_path or not os.path.exists(self.monster_list_xml_path):
            QtWidgets.QMessageBox.information(self, "Missing", "MonsterList.xml not found.")
            return
        try:
            with open(self.monster_list_xml_path, 'r', encoding='utf-8', errors='replace') as f:
                txt = f.read()
            self.text_monsterlist.setPlainText(txt)
            QtWidgets.QMessageBox.information(self, "Loaded", "MonsterList.xml reloaded.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load MonsterList.xml: {e}")

    def save_monsterlist_text(self):
        if not self.monster_list_xml_path:
            QtWidgets.QMessageBox.information(self, "No file", "Load a Monster folder first.")
            return
        try:
            # backup then write user-edited text
            backup_file(self.monster_list_xml_path)
            txt = self.text_monsterlist.toPlainText()
            with open(self.monster_list_xml_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(txt)
            QtWidgets.QMessageBox.information(self, "Saved", "MonsterList.xml saved (backup created).")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save MonsterList.xml: {e}")

    def save_all(self):
        try:
            save_monster_txt_patch(self.monster_txt_path, self.monsters, self.monster_lines, encoding=self.monster_encoding)
            regenerate_monster_list_xml(self.monster_list_xml_path, self.monsters)
            if self.spawn_tree is not None:
                save_monster_spawn_xml(self.monster_spawn_xml_path, self.spawn_tree)
            QtWidgets.QMessageBox.information(self, "Saved", "All files saved (backups created).")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
        self.update_warnings()

    def validate_all(self) -> list[str]:
        warns = []
        idxs = [m["Index"] for m in self.monsters]
        seen = set()
        for i in idxs:
            if i in seen:
                warns.append(f"Duplicate monster Index: {i}")
            seen.add(i)
        if self.spawn_tree is not None:
            root = self.spawn_tree.getroot()
            for mp in root.findall("Map"):
                for sp in mp.findall("Spot"):
                    for node in sp.findall("Spawn"):
                        idx = node.get("Index", "")
                        if idx.isdigit():
                            ii = int(idx)
                            if ii not in {m["Index"] for m in self.monsters}:
                                warns.append(f"Spawn refers to missing MonsterIndex: {ii}")
                        else:
                            warns.append(f"Spawn has non-numeric Index: {idx}")
        return warns

    def update_warnings(self):
        self.warnings.clear()
        for w in self.validate_all():
            self.warnings.addItem(w)

    def dry_run_validation(self):
        warns = self.validate_all()
        if not warns:
            QtWidgets.QMessageBox.information(self, "Validation", "No warnings found.")
        else:
            QtWidgets.QMessageBox.warning(self, "Validation", f"{len(warns)} warning(s) found. See panel.")
            self.update_warnings()

    # ---------------- Settings, Theme, Icons ----------------
    def _load_settings(self):
        settings = QtCore.QSettings('Phantasm', 'Phantasm LTP Monster Editor')
        theme = settings.value('theme', 'light')
        geom = settings.value('geometry')
        state = settings.value('windowState')
        if geom:
            try:
                self.restoreGeometry(geom)
                # clamp restored geometry to available screen and minimum size
                try:
                    screen = QtGui.QGuiApplication.primaryScreen()
                    if screen:
                        avail = screen.availableGeometry()
                        g = self.geometry()
                        minw = self.minimumWidth()
                        minh = self.minimumHeight()
                        neww = min(g.width(), avail.width())
                        newh = min(g.height(), avail.height())
                        neww = max(neww, minw)
                        newh = max(newh, minh)
                        self.resize(neww, newh)
                        nx = max(avail.x(), min(g.x(), avail.x() + avail.width() - neww))
                        ny = max(avail.y(), min(g.y(), avail.y() + avail.height() - newh))
                        self.move(nx, ny)
                except Exception:
                    pass
            except Exception:
                pass
        if state:
            try:
                self.restoreState(state)
            except Exception:
                pass
        # apply theme
        QtCore.QTimer.singleShot(0, lambda: self.apply_theme(theme))

    def apply_theme(self, name: str):
        name = (name or 'light').lower()
        # simple dark stylesheet
        if name == 'dark':
            dark = """
QWidget { background: #222; color: #ddd; }
QLineEdit, QPlainTextEdit, QTextEdit { background: #2b2b2b; color: #eee; }
QTableView, QTreeView, QListView, QTableWidget { background: #252525; color: #eee; gridline-color: #444; }
QHeaderView::section { background: #2b2b2b; color: #ddd; }
QPushButton { background: #333; color: #eee; }
"""
            self.setStyleSheet(dark)
        else:
            self.setStyleSheet("")
        # persist
        settings = QtCore.QSettings('Phantasm', 'Phantasm LTP Monster Editor')
        settings.setValue('theme', name)
        # update checked state of actions if present
        if hasattr(self, 'theme_group'):
            for a in self.theme_group.actions():
                if a.text().lower() == name:
                    a.setChecked(True)

    def generate_icons_from_svg(self):
        # generate logo.png and icon.ico from logo.svg using Qt's renderer if available
        svg_path = asset_path('logo.svg')
        out_png = os.path.join(os.path.dirname(__file__), 'assets', 'logo.png')
        out_ico = os.path.join(os.path.dirname(__file__), 'assets', 'icon.ico')
        if not os.path.exists(svg_path) or not QSvgRenderer:
            return
        try:
            rend = QSvgRenderer(svg_path)
            sizes = [256, 128, 64, 48, 32, 16]
            # render a large pixmap and save PNG
            pix = QtGui.QPixmap(256, 256)
            pix.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(pix)
            rend.render(p)
            p.end()
            os.makedirs(os.path.join(os.path.dirname(__file__), 'assets'), exist_ok=True)
            pix.save(out_png)
            # create multi-size ICO by saving multiple sizes (Qt may handle single-size ICO)
            icon_pix = QtGui.QIcon(pix)
            # attempt to write a .ico file via QPixmap saving (best-effort)
            if icon_pix.isNull() is False:
                # try sizes and pick the largest for saving as ico
                if pix.save(out_ico):
                    return
        except Exception:
            return

    def closeEvent(self, event: QtGui.QCloseEvent):
        try:
            settings = QtCore.QSettings('Phantasm', 'Phantasm LTP Monster Editor')
            settings.setValue('geometry', self.saveGeometry())
            settings.setValue('windowState', self.saveState())
        except Exception:
            pass
        super().closeEvent(event)


class SnapshotBrowser(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Snapshots')
        self.setModal(True)
        v = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        v.addWidget(self.list)
        btns = QtWidgets.QHBoxLayout()
        btn_restore = QtWidgets.QPushButton('Restore Selected')
        btn_restore.clicked.connect(self._restore)
        btns.addWidget(btn_restore)
        btn_open = QtWidgets.QPushButton('Open Folder')
        btn_open.clicked.connect(self._open_folder)
        btns.addWidget(btn_open)
        btns.addStretch()
        v.addLayout(btns)
        self._load_list()

    def _snap_dir(self):
        return os.path.join(os.path.dirname(__file__), 'backups', 'snapshots')

    def _load_list(self):
        self.list.clear()
        d = self._snap_dir()
        if not os.path.exists(d):
            return
        files = sorted([f for f in os.listdir(d) if f.endswith('.json')], reverse=True)
        for f in files:
            path = os.path.join(d, f)
            try:
                info = os.path.getmtime(path)
                label = f + '  ' + QtCore.QDateTime.fromSecsSinceEpoch(int(info)).toString('yyyy-MM-dd HH:mm:ss')
            except Exception:
                label = f
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, path)
            self.list.addItem(item)

    def _open_folder(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self._snap_dir()))

    def _restore(self):
        it = self.list.currentItem()
        if not it:
            return
        path = it.data(QtCore.Qt.UserRole)
        try:
            import json
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            snap = data.get('snapshot')
            if snap and hasattr(self.parent(), '_restore_snapshot'):
                self.parent()._restore_snapshot(snap)
                QtWidgets.QMessageBox.information(self, 'Restored', 'Snapshot restored (unsaved).')
                self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Error', str(e))


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Phantasm LTP Monster Editor")
    # set application icon using bundled assets (ico or png)
    icon_file = asset_path("icon.ico")
    if not os.path.exists(icon_file):
        icon_file = asset_path("logo.png")
    if os.path.exists(icon_file):
        try:
            app.setWindowIcon(QtGui.QIcon(icon_file))
        except Exception:
            pass
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

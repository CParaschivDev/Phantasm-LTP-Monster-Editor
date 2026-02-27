"""PySide6 GUI for MU Monster Editor (simplified modern UI).
This is a minimal but functional PySide6 application that uses the io_* modules.
"""
from __future__ import annotations

import sys
import os
from PySide6 import QtWidgets, QtCore, QtGui
import xml.etree.ElementTree as ET

from io_monster import parse_monster_txt, save_monster_txt_patch, MONSTER_FIELDS
from io_spawn import parse_monster_spawn_xml, save_monster_spawn_xml
from io_list import regenerate_monster_list_xml, render_monsterlist_string


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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MU Monster Editor (Qt)")
        self.resize(1200, 800)

        self.folder = None
        self.monster_txt_path = None
        self.monster_list_xml_path = None
        self.monster_spawn_xml_path = None

        self.monsters = []
        self.monster_lines = []
        self.monster_encoding = "utf-8"
        self.spawn_tree = None

        self._build_ui()

    def _build_ui(self):
        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        v = QtWidgets.QVBoxLayout(w)

        top_bar = QtWidgets.QHBoxLayout()
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

        top_bar.addStretch()
        self.lbl_folder = QtWidgets.QLabel("No folder selected")
        top_bar.addWidget(self.lbl_folder)
        v.addLayout(top_bar)

        tabs = QtWidgets.QTabWidget()
        v.addWidget(tabs)

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
        self.table_spawns.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        sp_layout.addWidget(self.table_spawns)

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
        bot_sp.addStretch()
        btn_save_spawn = QtWidgets.QPushButton("Save MonsterSpawn.xml")
        btn_save_spawn.clicked.connect(self.save_spawn_xml)
        bot_sp.addWidget(btn_save_spawn)
        sp_layout.addLayout(bot_sp)

        # warnings area
        self.warnings = QtWidgets.QListWidget()
        v.addWidget(QtWidgets.QLabel("Warnings:"))
        v.addWidget(self.warnings)

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

    def _filter_monsters(self, text):
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.proxy.setFilterFixedString(text)

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

    def add_spawn(self):
        sp = self._selected_spot_elem()
        if sp is None:
            QtWidgets.QMessageBox.information(self, "Select", "Select a map and spot first.")
            return
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
        data = dlg.result
        # replace attributes
        node.attrib.clear()
        node.set("Index", str(data.get("Index", 0)))
        for k, v in data.items():
            if k == "Index":
                continue
            node.set(k, str(v))
        self._refresh_spawn_table()

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
        sp.remove(nodes[sel])
        self._refresh_spawn_table()

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


def main():
    app = QtWidgets.QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

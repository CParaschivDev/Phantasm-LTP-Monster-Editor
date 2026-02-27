
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MU Monster + Spawn Editor (Monster.txt + MonsterList.xml + MonsterSpawn.xml)

- Loads Monster.txt (tab/space separated, name in quotes)
- Edits/creates monsters
- Regenerates MonsterList.xml from Monster.txt
- Edits/creates spawns inside MonsterSpawn.xml

Tested with LTP-Team style files.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import datetime
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import difflib
import io


MONSTER_FIELDS = [
    ("Index", int),
    ("Rate", int),
    ("Name", str),
    ("Level", int),
    ("Life", int),
    ("Mana", int),
    ("DamageMin", int),
    ("DamageMax", int),
    ("Defense", int),
    ("MagicDefense", int),
    ("AttackRate", int),
    ("DefenseRate", int),
    ("MoveRange", int),
    ("AttackType", int),
    ("AttackRange", int),
    ("ViewRange", int),
    ("MoveSpeed", int),
    ("AttackSpeed", int),
    ("RegenTime", int),
    ("Attribute", int),
    ("ItemRate", int),
    ("MoneyRate", int),
    ("MaxItemLevel", int),
    ("MonsterSkill", int),
    ("IceRes", int),
    ("PoisonRes", int),
    ("LightRes", int),
    ("FireRes", int),
]

# defaults
DEFAULT_INDEX_MIN = 0
DEFAULT_INDEX_MAX = 65535

# MonsterSpawn.xml spawn element attributes (some optional)
SPAWN_ATTRS = ["Index", "Distance", "StartX", "StartY", "EndX", "EndY", "Dir", "Count", "Value"]


def now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    bak = f"{path}.bak_{now_stamp()}"
    shutil.copy2(path, bak)


def strip_inline_comment(line: str) -> str:
    # Remove // comment that is NOT inside quotes
    in_quote = False
    for i in range(len(line) - 1):
        ch = line[i]
        if ch == '"':
            in_quote = not in_quote
        if not in_quote and line[i] == '/' and line[i + 1] == '/':
            return line[:i].rstrip()
    return line.rstrip()


def parse_monster_txt(monster_txt_path: str) -> tuple[list[dict], list[str], str]:
    """
    Returns (monsters, raw_lines)
    monsters: list of dict using MONSTER_FIELDS
    raw_lines: original file lines (for patch style save)
    """
    # Try common encodings and pick the one that doesn't mangle too much
    encodings = ["utf-8", "cp1250", "cp1252", "latin-1"]
    raw = None
    used_enc = "utf-8"
    for enc in encodings:
        try:
            with open(monster_txt_path, "r", encoding=enc, errors="strict") as f:
                raw = f.read()
            used_enc = enc
            break
        except Exception:
            continue
    if raw is None:
        # fallback: read with replace to ensure we can show something
        with open(monster_txt_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        used_enc = "utf-8"

    raw_lines = raw.splitlines()

    monsters = []
    for ln in raw_lines:
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        cleaned = strip_inline_comment(ln)
        if not cleaned.strip():
            continue
        try:
            tokens = shlex.split(cleaned, posix=True)
        except Exception:
            continue
        # Expect 28 tokens
        if len(tokens) != len(MONSTER_FIELDS):
            # Some custom sources may have extra columns; ignore for now
            continue

        rec = {}
        for (field, ftype), tok in zip(MONSTER_FIELDS, tokens):
            if ftype is int:
                try:
                    rec[field] = int(tok)
                except ValueError:
                    rec[field] = 0
            else:
                rec[field] = tok
        monsters.append(rec)

    # Sort by index for UI convenience
    monsters.sort(key=lambda m: m["Index"])
    return monsters, raw_lines, used_enc


def format_monster_line(m: dict) -> str:
    # Keep it simple and consistent; server parsers typically accept tabs/spaces.
    parts = []
    for field, ftype in MONSTER_FIELDS:
        v = m.get(field, 0 if ftype is int else "")
        if field == "Name":
            parts.append(f"\"{str(v)}\"")
        else:
            parts.append(str(int(v) if ftype is int else v))
    # Tabs make the file readable and close to original style
    return "\t".join(parts)


def save_monster_txt_patch(monster_txt_path: str, monsters: list[dict], raw_lines: list[str], encoding: str = "utf-8") -> None:
    """
    Patch-style save: replace existing index lines, append new ones at end.
    Preserves comments/sections as much as possible.
    """
    idx_to_mon = {m["Index"]: m for m in monsters}

    # Map existing index -> line number
    line_index_map: dict[int, int] = {}
    data_line_re = re.compile(r'^\s*(\d+)\s+')
    for i, ln in enumerate(raw_lines):
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        cleaned = strip_inline_comment(ln)
        if not cleaned.strip():
            continue
        try:
            tokens = shlex.split(cleaned, posix=True)
        except Exception:
            continue
        if len(tokens) != len(MONSTER_FIELDS):
            continue
        try:
            idx = int(tokens[0])
        except Exception:
            continue
        line_index_map[idx] = i

    used = set()
    new_lines = raw_lines[:]
    for idx, m in idx_to_mon.items():
        line = format_monster_line(m)
        if idx in line_index_map:
            new_lines[line_index_map[idx]] = line
        else:
            new_lines.append(line)
        used.add(idx)

    # Optionally: keep file tidy by ensuring it ends with newline
    text = "\n".join(new_lines) + "\n"
    backup_file(monster_txt_path)
    with open(monster_txt_path, "w", encoding=encoding, errors="replace") as f:
        f.write(text)


def indent_xml(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + ("  " * level)
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            indent_xml(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def regenerate_monster_list_xml(monster_list_xml_path: str, monsters: list[dict]) -> None:
    root = ET.Element("MonsterList")
    for m in sorted(monsters, key=lambda x: x["Index"]):
        attrs = {}
        # Keep attribute names aligned with existing file
        attrs["Index"] = str(m["Index"])
        attrs["Level"] = str(m["Level"])
        attrs["Life"] = str(m["Life"])
        attrs["Mana"] = str(m["Mana"])
        attrs["DamageMin"] = str(m["DamageMin"])
        attrs["DamageMax"] = str(m["DamageMax"])
        attrs["Defense"] = str(m["Defense"])
        attrs["MagicDefense"] = str(m["MagicDefense"])
        attrs["AttackRate"] = str(m["AttackRate"])
        attrs["DefenseRate"] = str(m["DefenseRate"])
        attrs["MoveRange"] = str(m["MoveRange"])
        attrs["AttackType"] = str(m["AttackType"])
        attrs["AttackRange"] = str(m["AttackRange"])
        attrs["ViewRange"] = str(m["ViewRange"])
        attrs["MoveSpeed"] = str(m["MoveSpeed"])
        attrs["AttackSpeed"] = str(m["AttackSpeed"])
        attrs["RegenTime"] = str(m["RegenTime"])
        attrs["Attribute"] = str(m["Attribute"])
        attrs["ItemRate"] = str(m["ItemRate"])
        attrs["MoneyRate"] = str(m["MoneyRate"])
        attrs["MaxItemLevel"] = str(m["MaxItemLevel"])
        attrs["MonsterSkill"] = str(m["MonsterSkill"])
        attrs["IceRes"] = str(m["IceRes"])
        attrs["PoisonRes"] = str(m["PoisonRes"])
        attrs["LightRes"] = str(m["LightRes"])
        attrs["FireRes"] = str(m["FireRes"])
        attrs["Name"] = str(m["Name"])
        ET.SubElement(root, "Monster", attrib=attrs)

    indent_xml(root)
    tree = ET.ElementTree(root)

    backup_file(monster_list_xml_path)
    with open(monster_list_xml_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        # Small header comment; the original file has a big banner but it's not required
        f.write(b'<!-- Generated by MU Monster Editor -->\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)


def parse_monster_spawn_xml(monster_spawn_xml_path: str) -> ET.ElementTree:
    return ET.parse(monster_spawn_xml_path)


def save_monster_spawn_xml(monster_spawn_xml_path: str, tree: ET.ElementTree) -> None:
    root = tree.getroot()
    indent_xml(root)
    backup_file(monster_spawn_xml_path)
    with open(monster_spawn_xml_path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!-- Generated by MU Monster Editor -->\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)


class SpawnDialog(tk.Toplevel):
    def __init__(self, parent, monster_choices: list[tuple[int, str]], initial: dict | None = None):
        super().__init__(parent)
        self.title("Spawn")
        self.resizable(False, False)
        self.result = None

        self.monster_choices = monster_choices
        self.var_index = tk.StringVar()
        self.var_name = tk.StringVar()

        # Build an index->name map for quick fill
        self.idx_to_name = {str(i): n for i, n in monster_choices}

        frm = ttk.Frame(self, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frm, text="Monster:").grid(row=0, column=0, sticky="w")
        self.cb_mon = ttk.Combobox(frm, width=45, state="readonly",
                                  values=[f"{i} - {n}" for i, n in monster_choices])
        self.cb_mon.grid(row=0, column=1, sticky="w")

        ttk.Separator(frm).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 8))

        self.vars = {}
        row = 2
        for key in SPAWN_ATTRS:
            if key in ("Index",):
                continue
            ttk.Label(frm, text=f"{key}:").grid(row=row, column=0, sticky="w")
            v = tk.StringVar()
            e = ttk.Entry(frm, textvariable=v, width=20)
            e.grid(row=row, column=1, sticky="w")
            self.vars[key] = v
            row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self._cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="OK", command=self._ok).grid(row=0, column=1)

        # Bind selection change
        self.cb_mon.bind("<<ComboboxSelected>>", self._on_monster_select)

        # Prefill
        if initial:
            idx = str(initial.get("Index", "0"))
            # Find matching combobox entry
            display = None
            for i, n in monster_choices:
                if str(i) == idx:
                    display = f"{i} - {n}"
                    break
            if display:
                self.cb_mon.set(display)
            else:
                if monster_choices:
                    self.cb_mon.current(0)
            for key in self.vars:
                if key in initial and initial[key] is not None:
                    self.vars[key].set(str(initial[key]))
        else:
            if monster_choices:
                self.cb_mon.current(0)
            # reasonable defaults
            self.vars["Distance"].set("0")
            self.vars["Dir"].set("-1")

        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _on_monster_select(self, _evt=None):
        pass

    def _cancel(self):
        self.result = None
        self.destroy()

    def _ok(self):
        if not self.cb_mon.get():
            messagebox.showerror("Missing", "Select a monster.")
            return
        idx = self.cb_mon.get().split(" - ", 1)[0].strip()
        data = {"Index": idx}
        for k, v in self.vars.items():
            if v.get().strip() == "":
                continue
            data[k] = v.get().strip()
        self.result = data
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MU Monster + Spawn Editor")
        self.geometry("1180x720")

        self.folder = None
        self.monster_txt_path = None
        self.monster_list_xml_path = None
        self.monster_spawn_xml_path = None

        self.monsters = []
        self.monster_lines = []
        self.monster_by_index = {}
        self.monster_txt_encoding = "utf-8"

        # configurable index range
        self.index_min = DEFAULT_INDEX_MIN
        self.index_max = DEFAULT_INDEX_MAX

        self.spawn_tree: ET.ElementTree | None = None

        self._build_ui()

    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self, padding=8)
        top.pack(side="top", fill="x")
        ttk.Button(top, text="Open Monster Folder...", command=self.open_folder).pack(side="left")
        ttk.Button(top, text="Dry-run validation", command=self.dry_run_validation).pack(side="left", padx=(8,0))
        ttk.Button(top, text="Index range...", command=self.set_index_range).pack(side="left", padx=(8,0))
        ttk.Button(top, text="Preview MonsterList diff", command=self.preview_monsterlist_diff).pack(side="left", padx=(8,0))
        ttk.Button(top, text="Sync MonsterSetBase...", command=self.sync_monster_setbase).pack(side="left", padx=(8,0))
        self.lbl_folder = ttk.Label(top, text="No folder selected", foreground="#555")
        self.lbl_folder.pack(side="left", padx=10)

        ttk.Button(top, text="Save ALL", command=self.save_all).pack(side="right")

        # Notebook
        # Main area: notebook + warnings panel stacked vertically
        self.main_v = ttk.Frame(self)
        self.main_v.pack(fill="both", expand=True)

        self.nb = ttk.Notebook(self.main_v)
        self.nb.pack(fill="both", expand=True)

        self.tab_mon = ttk.Frame(self.nb)
        self.tab_spw = ttk.Frame(self.nb)
        self.nb.add(self.tab_mon, text="Monsters (Monster.txt)")
        self.nb.add(self.tab_spw, text="Spawns (MonsterSpawn.xml)")

        self._build_monsters_tab()
        self._build_spawns_tab()

        # Warnings panel
        warn_frame = ttk.Frame(self.main_v, padding=6)
        warn_frame.pack(side="bottom", fill="x")
        ttk.Label(warn_frame, text="Warnings:").pack(anchor="w")
        self.lst_warnings = tk.Listbox(warn_frame, height=4)
        self.lst_warnings.pack(fill="x", expand=True)

        # Status bar
        self.status_var = tk.StringVar(value="No folder")
        status = ttk.Frame(self, padding=(4, 2))
        status.pack(side="bottom", fill="x")
        self.lbl_status = ttk.Label(status, textvariable=self.status_var, anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)

    # -------------------- Monsters tab --------------------
    def _build_monsters_tab(self):
        left = ttk.Frame(self.tab_mon, padding=8)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="Search:").pack(anchor="w")
        self.var_msearch = tk.StringVar()
        ent = ttk.Entry(left, textvariable=self.var_msearch, width=30)
        ent.pack(anchor="w", pady=(0, 6))
        ent.bind("<KeyRelease>", lambda e: self._refresh_monster_list())

        self.lst_mon = tk.Listbox(left, width=38, height=28)
        self.lst_mon.pack(fill="y", expand=True)
        self.lst_mon.bind("<<ListboxSelect>>", lambda e: self._on_monster_select())

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="New (next free Index)", command=self.new_monster).pack(fill="x")
        ttk.Button(btns, text="Duplicate selected", command=self.dup_monster).pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Delete selected", command=self.del_monster).pack(fill="x", pady=(6, 0))
        ttk.Separator(left).pack(fill="x", pady=10)
        ttk.Button(left, text="Save Monster.txt", command=self.save_monster_txt).pack(fill="x")
        ttk.Button(left, text="Regenerate MonsterList.xml", command=self.regen_monster_list).pack(fill="x", pady=(6, 0))

        # Right edit form (scrollable)
        right = ttk.Frame(self.tab_mon, padding=8)
        right.pack(side="left", fill="both", expand=True)

        self.form_canvas = tk.Canvas(right, borderwidth=0)
        self.form_scroll = ttk.Scrollbar(right, orient="vertical", command=self.form_canvas.yview)
        self.form_frame = ttk.Frame(self.form_canvas)

        self.form_frame.bind(
            "<Configure>",
            lambda e: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")),
        )

        self.form_canvas.create_window((0, 0), window=self.form_frame, anchor="nw")
        self.form_canvas.configure(yscrollcommand=self.form_scroll.set)

        self.form_canvas.pack(side="left", fill="both", expand=True)
        self.form_scroll.pack(side="right", fill="y")

        self.mon_vars = {}
        r = 0
        for field, ftype in MONSTER_FIELDS:
            ttk.Label(self.form_frame, text=field, width=16).grid(row=r, column=0, sticky="w", pady=2)
            v = tk.StringVar()
            e = ttk.Entry(self.form_frame, textvariable=v, width=40)
            e.grid(row=r, column=1, sticky="w", pady=2)
            self.mon_vars[field] = v
            r += 1

        self.btn_save_one = ttk.Button(self.form_frame, text="Apply changes to selected monster", command=self.apply_monster_changes)
        self.btn_save_one.grid(row=r, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _refresh_monster_list(self):
        self.lst_mon.delete(0, tk.END)
        q = self.var_msearch.get().strip().lower()
        for m in self.monsters:
            label = f'{m["Index"]:>4}  -  {m["Name"]}'
            if q and (q not in label.lower()):
                continue
            self.lst_mon.insert(tk.END, label)

    def _selected_monster_index(self) -> int | None:
        sel = self.lst_mon.curselection()
        if not sel:
            return None
        text = self.lst_mon.get(sel[0])
        try:
            idx = int(text.split("-")[0].strip())
            return idx
        except Exception:
            return None

    def _on_monster_select(self):
        idx = self._selected_monster_index()
        if idx is None:
            return
        m = self.monster_by_index.get(idx)
        if not m:
            return
        for field, _ in MONSTER_FIELDS:
            self.mon_vars[field].set(str(m.get(field, "")))

    def new_monster(self):
        if not self.monsters:
            messagebox.showerror("No data", "Load a Monster folder first.")
            return
        used = {m["Index"] for m in self.monsters}
        idx = 0
        while idx in used:
            idx += 1
        base = self.monsters[0].copy()
        base["Index"] = idx
        base["Rate"] = 1
        base["Name"] = f"New Monster {idx}"
        self.monsters.append(base)
        self.monsters.sort(key=lambda x: x["Index"])
        self._reindex_monsters()
        self._refresh_monster_list()
        # select new
        for i in range(self.lst_mon.size()):
            if self.lst_mon.get(i).startswith(f"{idx:>4}"):
                self.lst_mon.selection_clear(0, tk.END)
                self.lst_mon.selection_set(i)
                self.lst_mon.see(i)
                self._on_monster_select()
                break

    def dup_monster(self):
        idx = self._selected_monster_index()
        if idx is None:
            messagebox.showerror("Select", "Select a monster to duplicate.")
            return
        used = {m["Index"] for m in self.monsters}
        new_idx = 0
        while new_idx in used:
            new_idx += 1
        src = self.monster_by_index[idx].copy()
        src["Index"] = new_idx
        src["Name"] = f'{src["Name"]} (Copy)'
        self.monsters.append(src)
        self.monsters.sort(key=lambda x: x["Index"])
        self._reindex_monsters()
        self._refresh_monster_list()

    def del_monster(self):
        idx = self._selected_monster_index()
        if idx is None:
            messagebox.showerror("Select", "Select a monster to delete.")
            return
        if not messagebox.askyesno("Confirm", f"Delete monster Index {idx}?"):
            return
        self.monsters = [m for m in self.monsters if m["Index"] != idx]
        self._reindex_monsters()
        self._refresh_monster_list()

    def apply_monster_changes(self):
        idx = self._selected_monster_index()
        if idx is None:
            messagebox.showerror("Select", "Select a monster first.")
            return
        m = self.monster_by_index.get(idx)
        if not m:
            return

        # Build new record
        new = {}
        for field, ftype in MONSTER_FIELDS:
            val = self.mon_vars[field].get().strip()
            if field == "Name":
                new[field] = val
            else:
                try:
                    new[field] = int(val)
                except Exception:
                    new[field] = 0

        # Index changes are tricky; allow but keep unique
        if new["Index"] != idx and new["Index"] in self.monster_by_index:
            messagebox.showerror("Index exists", "That Index already exists.")
            return

        # Apply
        if new["Index"] != idx:
            # Remove old index entry
            self.monsters = [mm for mm in self.monsters if mm["Index"] != idx]
            self.monsters.append(new)
        else:
            m.update(new)

        self.monsters.sort(key=lambda x: x["Index"])
        self._reindex_monsters()
        self._refresh_monster_list()
        messagebox.showinfo("OK", "Monster updated in memory.\nUse 'Save Monster.txt' to write to disk.")

    def save_monster_txt(self):
        if not self.monster_txt_path:
            messagebox.showerror("No file", "Load a Monster folder first.")
            return
        try:
            save_monster_txt_patch(self.monster_txt_path, self.monsters, self.monster_lines, encoding=self.monster_txt_encoding)
            # Reload to refresh lines map and encoding
            parsed = parse_monster_txt(self.monster_txt_path)
            if isinstance(parsed, tuple) and len(parsed) == 3:
                self.monsters, self.monster_lines, enc = parsed
                self.monster_txt_encoding = enc
            else:
                self.monsters, self.monster_lines = parsed
            self._reindex_monsters()
            self._refresh_monster_list()
            self.update_warnings()
            self.update_statusbar()
            messagebox.showinfo("Saved", "Monster.txt saved (backup created).")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def regen_monster_list(self):
        if not self.monster_list_xml_path:
            messagebox.showerror("No file", "Load a Monster folder first.")
            return
        try:
            regenerate_monster_list_xml(self.monster_list_xml_path, self.monsters)
            messagebox.showinfo("Done", "MonsterList.xml regenerated (backup created).")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def render_monsterlist_string(self, monsters: list[dict]) -> str:
        root = ET.Element("MonsterList")
        for m in sorted(monsters, key=lambda x: x["Index"]):
            attrs = {}
            attrs["Index"] = str(m["Index"])
            attrs["Level"] = str(m["Level"])
            attrs["Life"] = str(m["Life"])
            attrs["Mana"] = str(m["Mana"])
            attrs["DamageMin"] = str(m["DamageMin"])
            attrs["DamageMax"] = str(m["DamageMax"])
            attrs["Defense"] = str(m["Defense"])
            attrs["MagicDefense"] = str(m["MagicDefense"])
            attrs["AttackRate"] = str(m["AttackRate"])
            attrs["DefenseRate"] = str(m["DefenseRate"])
            attrs["MoveRange"] = str(m["MoveRange"])
            attrs["AttackType"] = str(m["AttackType"])
            attrs["AttackRange"] = str(m["AttackRange"])
            attrs["ViewRange"] = str(m["ViewRange"])
            attrs["MoveSpeed"] = str(m["MoveSpeed"])
            attrs["AttackSpeed"] = str(m["AttackSpeed"])
            attrs["RegenTime"] = str(m["RegenTime"])
            attrs["Attribute"] = str(m["Attribute"])
            attrs["ItemRate"] = str(m["ItemRate"])
            attrs["MoneyRate"] = str(m["MoneyRate"])
            attrs["MaxItemLevel"] = str(m["MaxItemLevel"])
            attrs["MonsterSkill"] = str(m["MonsterSkill"])
            attrs["IceRes"] = str(m["IceRes"])
            attrs["PoisonRes"] = str(m["PoisonRes"])
            attrs["LightRes"] = str(m["LightRes"])
            attrs["FireRes"] = str(m["FireRes"])
            attrs["Name"] = str(m["Name"])
            ET.SubElement(root, "Monster", attrib=attrs)

        indent_xml(root)
        tree = ET.ElementTree(root)
        bio = io.BytesIO()
        bio.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        bio.write(b'<!-- Generated by MU Monster Editor (preview) -->\n')
        tree.write(bio, encoding="utf-8", xml_declaration=False)
        return bio.getvalue().decode("utf-8")

    def preview_monsterlist_diff(self):
        if not self.monster_list_xml_path:
            messagebox.showerror("No file", "Load a Monster folder first.")
            return
        try:
            with open(self.monster_list_xml_path, "r", encoding="utf-8", errors="replace") as f:
                existing = f.read().splitlines()
        except Exception:
            existing = []
        generated = self.render_monsterlist_string(self.monsters).splitlines()
        diff = list(difflib.unified_diff(existing, generated, fromfile="MonsterList.xml (existing)", tofile="MonsterList.xml (generated)", lineterm=""))

        d = tk.Toplevel(self)
        d.title("MonsterList.xml Preview Diff")
        txt = tk.Text(d, wrap="none", width=120, height=40)
        txt.pack(fill="both", expand=True)
        if not diff:
            txt.insert("1.0", "No differences found. Generated MonsterList matches existing file.")
        else:
            for line in diff:
                txt.insert("end", line + "\n")

        btns = ttk.Frame(d, padding=6)
        btns.pack(fill="x")
        def save_generated():
            if not messagebox.askyesno("Confirm", "Overwrite MonsterList.xml with generated version? This creates a backup."):
                return
            regenerate_monster_list_xml(self.monster_list_xml_path, self.monsters)
            messagebox.showinfo("Saved", "MonsterList.xml regenerated (backup created).")
            d.destroy()

        ttk.Button(btns, text="Save generated MonsterList.xml", command=save_generated).pack(side="right")
        ttk.Button(btns, text="Close", command=d.destroy).pack(side="right", padx=(6,0))

    def sync_monster_setbase(self):
        # Check for MonsterSetBase files and report missing indices
        if not self.folder:
            messagebox.showerror("No folder", "Load a Monster folder first.")
            return
        paths = [os.path.join(self.folder, "MonsterSetBase.txt"), os.path.join(self.folder, "MonsterSetBaseCS.txt")]
        missing_report = {}
        for p in paths:
            if not os.path.isfile(p):
                missing_report[p] = None
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
            except Exception:
                txt = ""
            missing = []
            for m in self.monsters:
                token = str(m["Index"])
                if token not in txt:
                    missing.append(m["Index"])
            missing_report[p] = missing

        # Show dialog with report and allow creating suggestions file or appending commented placeholders
        d = tk.Toplevel(self)
        d.title("Sync MonsterSetBase")
        frm = ttk.Frame(d, padding=10)
        frm.grid(row=0, column=0)
        row = 0
        for p, miss in missing_report.items():
            ttk.Label(frm, text=os.path.basename(p) + ":").grid(row=row, column=0, sticky="w")
            if miss is None:
                ttk.Label(frm, text="(file missing)").grid(row=row, column=1, sticky="w")
            else:
                ttk.Label(frm, text=f"{len(miss)} missing entries").grid(row=row, column=1, sticky="w")
            row += 1

        def create_suggestions():
            outp = os.path.join(self.folder, "MonsterSetBase.suggestions.txt")
            with open(outp, "w", encoding="utf-8") as f:
                f.write("# Suggested entries for missing Monster indices\n")
                for p, miss in missing_report.items():
                    if not miss:
                        continue
                    f.write(f"# From file: {os.path.basename(p)}\n")
                    for idx in miss:
                        f.write(f"MISSING_INDEX\t{idx}\t# TODO: insert correct setbase line for this monster\n")
                    f.write("\n")
            messagebox.showinfo("Saved", f"Suggestions written to {outp}")
            d.destroy()

        def append_commented():
            # Append commented placeholders to each real file after backing up
            for p, miss in missing_report.items():
                if miss is None or not miss:
                    continue
                backup_file(p)
                with open(p, "a", encoding="utf-8", errors="replace") as f:
                    f.write("\n# Appended placeholders by MU Monster Editor - " + now_stamp() + "\n")
                    for idx in miss:
                        f.write(f"# MISSING_MONSTER_INDEX: {idx} -- please add proper entry\n")
            messagebox.showinfo("Done", "Appended commented placeholders to files (backups created).")
            d.destroy()

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10,0))
        ttk.Button(btns, text="Create suggestions file", command=create_suggestions).grid(row=0, column=0, padx=(0,6))
        ttk.Button(btns, text="Append commented placeholders", command=append_commented).grid(row=0, column=1)
        ttk.Button(btns, text="Close", command=d.destroy).grid(row=0, column=2, padx=(6,0))

    # -------------------- Spawns tab --------------------
    def _build_spawns_tab(self):
        top = ttk.Frame(self.tab_spw, padding=8)
        top.pack(side="top", fill="x")

        ttk.Label(top, text="Map:").pack(side="left")
        self.var_map = tk.StringVar()
        self.cb_map = ttk.Combobox(top, textvariable=self.var_map, state="readonly", width=40)
        self.cb_map.pack(side="left", padx=(6, 14))
        self.cb_map.bind("<<ComboboxSelected>>", lambda e: self._refresh_spot_list())

        ttk.Label(top, text="Spot:").pack(side="left")
        self.var_spot = tk.StringVar()
        self.cb_spot = ttk.Combobox(top, textvariable=self.var_spot, state="readonly", width=50)
        self.cb_spot.pack(side="left", padx=(6, 14))
        self.cb_spot.bind("<<ComboboxSelected>>", lambda e: self._refresh_spawn_table())

        ttk.Button(top, text="New Spot", command=self.new_spot).pack(side="left")
        ttk.Button(top, text="Delete Spot", command=self.delete_spot).pack(side="left", padx=(6, 0))

        # Table area
        mid = ttk.Frame(self.tab_spw, padding=8)
        mid.pack(fill="both", expand=True)

        cols = ("Index", "Name", "Count", "StartX", "StartY", "EndX", "EndY", "Distance", "Dir", "Value")
        self.tree_spawns = ttk.Treeview(mid, columns=cols, show="headings", height=22)
        for c in cols:
            self.tree_spawns.heading(c, text=c)
            self.tree_spawns.column(c, width=90 if c != "Name" else 220, anchor="center")
        self.tree_spawns.column("Name", anchor="w")

        yscroll = ttk.Scrollbar(mid, orient="vertical", command=self.tree_spawns.yview)
        self.tree_spawns.configure(yscrollcommand=yscroll.set)
        self.tree_spawns.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # Buttons
        bottom = ttk.Frame(self.tab_spw, padding=8)
        bottom.pack(side="bottom", fill="x")

        ttk.Button(bottom, text="Add Spawn", command=self.add_spawn).pack(side="left")
        ttk.Button(bottom, text="Edit Spawn", command=self.edit_spawn).pack(side="left", padx=(6, 0))
        ttk.Button(bottom, text="Delete Spawn", command=self.delete_spawn).pack(side="left", padx=(6, 0))

        ttk.Separator(bottom).pack(side="left", fill="y", padx=10)

        ttk.Button(bottom, text="Save MonsterSpawn.xml", command=self.save_spawn_xml).pack(side="right")

        self.lbl_spawn_warn = ttk.Label(bottom, text="", foreground="#a00")
        self.lbl_spawn_warn.pack(side="left", padx=10)

    def _monster_choices(self) -> list[tuple[int, str]]:
        return [(m["Index"], m["Name"]) for m in self.monsters]

    def _refresh_spot_list(self):
        self.cb_spot["values"] = []
        self.var_spot.set("")
        self._refresh_spawn_table()

        if not self.spawn_tree:
            return
        root = self.spawn_tree.getroot()
        map_num = self._selected_map_number()
        if map_num is None:
            return
        mp = self._find_map_elem(map_num)
        if mp is None:
            return
        spots = mp.findall("Spot")
        values = []
        for i, sp in enumerate(spots, start=1):
            typ = sp.get("Type", "?")
            desc = sp.get("Description", "")
            values.append(f"{i:02d}. Type={typ}  {desc}")
        self.cb_spot["values"] = values
        if values:
            self.cb_spot.current(0)
            self._refresh_spawn_table()

    def _selected_map_number(self) -> int | None:
        if not self.var_map.get():
            return None
        try:
            return int(self.var_map.get().split(" - ", 1)[0].strip())
        except Exception:
            return None

    def _selected_spot_elem(self) -> ET.Element | None:
        mp_num = self._selected_map_number()
        if mp_num is None or not self.spawn_tree:
            return None
        mp = self._find_map_elem(mp_num)
        if mp is None:
            return None
        if not self.var_spot.get():
            return None
        try:
            spot_idx = int(self.var_spot.get().split(".", 1)[0]) - 1
        except Exception:
            return None
        spots = mp.findall("Spot")
        if 0 <= spot_idx < len(spots):
            return spots[spot_idx]
        return None

    def _find_map_elem(self, map_number: int) -> ET.Element | None:
        if not self.spawn_tree:
            return None
        root = self.spawn_tree.getroot()
        for mp in root.findall("Map"):
            try:
                if int(mp.get("Number", "-9999")) == map_number:
                    return mp
            except Exception:
                continue
        return None

    def _refresh_spawn_table(self):
        for item in self.tree_spawns.get_children():
            self.tree_spawns.delete(item)
        self.lbl_spawn_warn.config(text="")

        sp = self._selected_spot_elem()
        if sp is None:
            self.update_warnings()
            self.update_statusbar()
            return

        # ensure tag style
        try:
            self.tree_spawns.tag_configure("unknown", foreground="#a00")
        except Exception:
            pass

        unknown = 0
        for node in sp.findall("Spawn"):
            idx = node.get("Index", "")
            name = self.monster_by_index.get(int(idx), {}).get("Name", "") if idx.isdigit() else ""
            is_unknown = False
            if not name:
                unknown += 1
                name = "(unknown)"
                is_unknown = True
            row = (
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
            )
            item = self.tree_spawns.insert("", "end", values=row)
            if is_unknown:
                self.tree_spawns.item(item, tags=("unknown",))
        if unknown:
            self.lbl_spawn_warn.config(text=f"⚠ {unknown} spawn-uri referă indecși lipsă din Monster.txt")
        # update warnings list and statusbar
        self.update_warnings()
        self.update_statusbar()

    def _selected_spawn_node(self) -> tuple[ET.Element | None, int | None]:
        sp = self._selected_spot_elem()
        if sp is None:
            return None, None
        sel = self.tree_spawns.selection()
        if not sel:
            return None, None
        item = sel[0]
        # Determine selected row index in treeview order
        all_items = list(self.tree_spawns.get_children())
        row_idx = all_items.index(item)
        nodes = sp.findall("Spawn")
        if 0 <= row_idx < len(nodes):
            return nodes[row_idx], row_idx
        return None, None

    def add_spawn(self):
        sp = self._selected_spot_elem()
        if sp is None:
            messagebox.showerror("Select", "Select a map and spot first.")
            return
        dlg = SpawnDialog(self, self._monster_choices(), initial=None)
        self.wait_window(dlg)
        if not dlg.result:
            return
        data = dlg.result
        node = ET.SubElement(sp, "Spawn")
        # Required
        node.set("Index", str(data.get("Index", "0")))
        # Optional
        for k in SPAWN_ATTRS:
            if k == "Index":
                continue
            if k in data:
                node.set(k, str(data[k]))
        self._refresh_spawn_table()

    def edit_spawn(self):
        node, _ = self._selected_spawn_node()
        if node is None:
            messagebox.showerror("Select", "Select a spawn row first.")
            return
        initial = {k: node.get(k) for k in SPAWN_ATTRS if node.get(k) is not None}
        dlg = SpawnDialog(self, self._monster_choices(), initial=initial)
        self.wait_window(dlg)
        if not dlg.result:
            return
        data = dlg.result
        # Update node
        node.attrib.clear()
        node.set("Index", str(data.get("Index", "0")))
        for k in SPAWN_ATTRS:
            if k == "Index":
                continue
            if k in data:
                node.set(k, str(data[k]))
        self._refresh_spawn_table()

    def delete_spawn(self):
        sp = self._selected_spot_elem()
        node, _ = self._selected_spawn_node()
        if sp is None or node is None:
            messagebox.showerror("Select", "Select a spawn row first.")
            return
        if not messagebox.askyesno("Confirm", "Delete selected spawn?"):
            return
        sp.remove(node)
        self._refresh_spawn_table()

    def new_spot(self):
        mp_num = self._selected_map_number()
        if mp_num is None:
            messagebox.showerror("Select", "Select a map first.")
            return
        mp = self._find_map_elem(mp_num)
        if mp is None:
            messagebox.showerror("Missing", "Map not found in XML.")
            return

        # Simple dialog for spot type and description
        d = tk.Toplevel(self)
        d.title("New Spot")
        d.resizable(False, False)
        frm = ttk.Frame(d, padding=10)
        frm.grid(row=0, column=0)

        ttk.Label(frm, text="Type (0..4):").grid(row=0, column=0, sticky="w")
        v_type = tk.StringVar(value="1")
        ttk.Entry(frm, textvariable=v_type, width=8).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Description:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        v_desc = tk.StringVar(value="New Spot")
        ttk.Entry(frm, textvariable=v_desc, width=40).grid(row=1, column=1, sticky="w", pady=(6, 0))

        def ok():
            sp = ET.SubElement(mp, "Spot")
            sp.set("Type", v_type.get().strip() or "1")
            sp.set("Description", v_desc.get().strip() or "New Spot")
            d.destroy()
            self._refresh_spot_list()
            # select last spot
            vals = list(self.cb_spot["values"])
            if vals:
                self.cb_spot.current(len(vals) - 1)
                self._refresh_spawn_table()

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=d.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="OK", command=ok).grid(row=0, column=1)

        d.transient(self)
        d.grab_set()
        self.wait_window(d)

    def delete_spot(self):
        mp_num = self._selected_map_number()
        if mp_num is None:
            messagebox.showerror("Select", "Select a map first.")
            return
        mp = self._find_map_elem(mp_num)
        if mp is None:
            return
        sp = self._selected_spot_elem()
        if sp is None:
            messagebox.showerror("Select", "Select a spot first.")
            return
        if not messagebox.askyesno("Confirm", "Delete selected spot (and all its spawns)?"):
            return
        mp.remove(sp)
        self._refresh_spot_list()

    def save_spawn_xml(self):
        if not self.monster_spawn_xml_path or not self.spawn_tree:
            messagebox.showerror("No file", "Load a Monster folder first.")
            return
        try:
            save_monster_spawn_xml(self.monster_spawn_xml_path, self.spawn_tree)
            messagebox.showinfo("Saved", "MonsterSpawn.xml saved (backup created).")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # -------------------- Load / Save All --------------------
    def _reindex_monsters(self):
        self.monster_by_index = {m["Index"]: m for m in self.monsters}

    def open_folder(self):
        folder = filedialog.askdirectory(title="Select Monster folder (contains Monster.txt, MonsterSpawn.xml, MonsterList.xml)")
        if not folder:
            return
        self.load_folder(folder)

    def load_folder(self, folder: str):
        self.folder = folder
        self.lbl_folder.config(text=folder)

        self.monster_txt_path = os.path.join(folder, "Monster.txt")
        self.monster_list_xml_path = os.path.join(folder, "MonsterList.xml")
        self.monster_spawn_xml_path = os.path.join(folder, "MonsterSpawn.xml")

        missing = [p for p in [self.monster_txt_path, self.monster_list_xml_path, self.monster_spawn_xml_path] if not os.path.isfile(p)]
        if missing:
            messagebox.showerror("Missing files", "Could not find:\n" + "\n".join(missing))
            return

        try:
            parsed = parse_monster_txt(self.monster_txt_path)
            if isinstance(parsed, tuple) and len(parsed) == 3:
                self.monsters, self.monster_lines, enc = parsed
                self.monster_txt_encoding = enc
            else:
                self.monsters, self.monster_lines = parsed
            self._reindex_monsters()
            self._refresh_monster_list()
            self.update_warnings()
            self.update_statusbar()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load Monster.txt\n{e}")
            return

        try:
            self.spawn_tree = parse_monster_spawn_xml(self.monster_spawn_xml_path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load MonsterSpawn.xml\n{e}")
            self.spawn_tree = None
            return

        # Populate maps
        maps = []
        root = self.spawn_tree.getroot()
        for mp in root.findall("Map"):
            num = mp.get("Number", "")
            name = mp.get("Name", "")
            maps.append((int(num) if str(num).lstrip("-").isdigit() else -9999, name))
        maps.sort(key=lambda x: x[0])
        map_vals = [f"{n} - {nm}" for n, nm in maps]
        self.cb_map["values"] = map_vals
        if map_vals:
            self.cb_map.current(0)
            self._refresh_spot_list()

    def save_all(self):
        if not self.folder:
            messagebox.showerror("No folder", "Load a Monster folder first.")
            return
        # Save Monster.txt, regenerate MonsterList, save spawn xml
        try:
            self.save_monster_txt()
            self.regen_monster_list()
            self.save_spawn_xml()
            messagebox.showinfo("Done", "All saved.\nBackups were created for each file.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # -------------------- Validation / UI helpers --------------------
    def validate_all(self) -> list[str]:
        warnings: list[str] = []
        # Duplicate or range checks for monsters
        idxs = [m["Index"] for m in self.monsters]
        seen = set()
        for i in idxs:
            if i in seen:
                warnings.append(f"Duplicate monster Index: {i}")
            seen.add(i)
            if i < self.index_min or i > self.index_max:
                warnings.append(f"Monster Index {i} out of allowed range ({self.index_min}-{self.index_max})")

        # Spawns referencing missing monsters
        if self.spawn_tree is not None:
            root = self.spawn_tree.getroot()
            for mp in root.findall("Map"):
                for sp in mp.findall("Spot"):
                    for node in sp.findall("Spawn"):
                        idx = node.get("Index", "")
                        if idx.isdigit():
                            ii = int(idx)
                            if ii not in self.monster_by_index:
                                warnings.append(f"Spawn refers to missing MonsterIndex: {ii}")
                        else:
                            warnings.append(f"Spawn has non-numeric Index: {idx}")

        return warnings

    def update_warnings(self) -> None:
        items = self.validate_all()
        self.lst_warnings.delete(0, tk.END)
        for it in items:
            self.lst_warnings.insert(tk.END, it)

    def update_statusbar(self) -> None:
        mons = len(self.monsters) if self.monsters is not None else 0
        spots = 0
        if self.spawn_tree is not None:
            root = self.spawn_tree.getroot()
            for mp in root.findall("Map"):
                spots += len(mp.findall("Spot"))
        warns = self.lst_warnings.size() if hasattr(self, 'lst_warnings') else 0
        enc = getattr(self, 'monster_txt_encoding', 'utf-8')
        self.status_var.set(f"Folder: {self.folder or 'none'} | Monsters: {mons} | Spots: {spots} | Warnings: {warns} | Encoding: {enc}")

    def dry_run_validation(self):
        if not self.folder:
            messagebox.showerror("No folder", "Load a Monster folder first.")
            return
        warns = self.validate_all()
        self.lst_warnings.delete(0, tk.END)
        if not warns:
            messagebox.showinfo("Validation OK", "No warnings found.")
        else:
            for w in warns:
                self.lst_warnings.insert(tk.END, w)
            messagebox.showwarning("Validation Warnings", f"{len(warns)} warning(s) found. See panel.")
        self.update_statusbar()

    def set_index_range(self):
        d = tk.Toplevel(self)
        d.title("Index Range")
        d.resizable(False, False)
        frm = ttk.Frame(d, padding=10)
        frm.grid(row=0, column=0)

        ttk.Label(frm, text="Min Index:").grid(row=0, column=0, sticky="w")
        vmin = tk.StringVar(value=str(self.index_min))
        ttk.Entry(frm, textvariable=vmin, width=10).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Max Index:").grid(row=1, column=0, sticky="w", pady=(6,0))
        vmax = tk.StringVar(value=str(self.index_max))
        ttk.Entry(frm, textvariable=vmax, width=10).grid(row=1, column=1, sticky="w", pady=(6,0))

        def ok():
            try:
                mn = int(vmin.get())
                mx = int(vmax.get())
                if mn < 0 or mx < 0 or mn >= mx:
                    raise ValueError()
                self.index_min = mn
                self.index_max = mx
                d.destroy()
                self.update_warnings()
                self.update_statusbar()
            except Exception:
                messagebox.showerror("Invalid", "Enter valid numeric min < max")

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=d.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="OK", command=ok).grid(row=0, column=1)



def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

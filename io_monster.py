"""I/O utilities for Monster.txt parsing and saving."""
from __future__ import annotations

import shlex
import os
import shutil
import datetime
from typing import List, Tuple

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


def now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    bak = f"{path}.bak_{now_stamp()}"
    shutil.copy2(path, bak)


def strip_inline_comment(line: str) -> str:
    in_quote = False
    for i in range(len(line) - 1):
        ch = line[i]
        if ch == '"':
            in_quote = not in_quote
        if not in_quote and line[i] == '/' and line[i + 1] == '/':
            return line[:i].rstrip()
    return line.rstrip()


def parse_monster_txt(path: str, encodings: List[str] | None = None) -> Tuple[List[dict], List[str], str]:
    encs = encodings or ["utf-8", "cp1250", "cp1252", "latin-1"]
    raw = None
    used = "utf-8"
    for e in encs:
        try:
            with open(path, "r", encoding=e, errors="strict") as f:
                raw = f.read()
            used = e
            break
        except Exception:
            continue
    if raw is None:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        used = "utf-8"
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
        if len(tokens) != len(MONSTER_FIELDS):
            continue
        rec = {}
        for (field, ftype), tok in zip(MONSTER_FIELDS, tokens):
            if ftype is int:
                try:
                    rec[field] = int(tok)
                except Exception:
                    rec[field] = 0
            else:
                rec[field] = tok
        monsters.append(rec)

    monsters.sort(key=lambda m: m["Index"])
    return monsters, raw_lines, used


def format_monster_line(m: dict) -> str:
    parts = []
    for field, ftype in MONSTER_FIELDS:
        v = m.get(field, 0 if ftype is int else "")
        if field == "Name":
            parts.append(f'"{str(v)}"')
        else:
            parts.append(str(int(v) if ftype is int else v))
    return "\t".join(parts)


def save_monster_txt_patch(path: str, monsters: List[dict], raw_lines: List[str], encoding: str = "utf-8") -> None:
    idx_to_mon = {m["Index"]: m for m in monsters}
    line_index_map = {}
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

    new_lines = raw_lines[:]
    for idx, m in idx_to_mon.items():
        line = format_monster_line(m)
        if idx in line_index_map:
            new_lines[line_index_map[idx]] = line
        else:
            new_lines.append(line)

    text = "\n".join(new_lines) + "\n"
    backup_file(path)
    with open(path, "w", encoding=encoding, errors="replace") as f:
        f.write(text)

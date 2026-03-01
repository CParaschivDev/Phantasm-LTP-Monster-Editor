"""Simple history stack for undo/redo of monsters + spawn XML.
Stores timestamped snapshots and writes autosave snapshots to backups/snapshots.
"""
from copy import deepcopy
from datetime import datetime
import json
import os


# snapshots will be written to backups/snapshots next to this module
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(BASE_DIR, 'backups', 'snapshots')
os.makedirs(SNAP_DIR, exist_ok=True)


class HistoryStack:
    def __init__(self, maxlen: int = 200):
        # store tuples of (timestamp_iso, snapshot)
        self._undo: list[tuple[str, dict]] = []
        self._redo: list[tuple[str, dict]] = []
        self.maxlen = maxlen

    def push(self, snapshot: dict):
        ts = datetime.utcnow().isoformat() + 'Z'
        self._undo.append((ts, deepcopy(snapshot)))
        if len(self._undo) > self.maxlen:
            self._undo.pop(0)
        self._redo.clear()
        # also persist snapshot to disk for autosave history
        try:
            safe_ts = ts.replace(':', '-')
            fname = os.path.join(SNAP_DIR, f'snapshot_{safe_ts}.json')
            data = {
                'time': ts,
                'snapshot': snapshot
            }
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def can_undo(self) -> bool:
        return len(self._undo) > 0

    def can_redo(self) -> bool:
        return len(self._redo) > 0

    def undo(self, current_snapshot: dict) -> dict | None:
        if not self.can_undo():
            return None
        ts, last = self._undo.pop()
        # push current to redo
        now_ts = datetime.utcnow().isoformat() + 'Z'
        self._redo.append((now_ts, deepcopy(current_snapshot)))
        return deepcopy(last)

    def redo(self, current_snapshot: dict) -> dict | None:
        if not self.can_redo():
            return None
        ts, nxt = self._redo.pop()
        now_ts = datetime.utcnow().isoformat() + 'Z'
        self._undo.append((now_ts, deepcopy(current_snapshot)))
        return deepcopy(nxt)

    def list_snapshots(self) -> list[tuple[str, dict]]:
        return list(self._undo)

    def export_snapshot(self, ts: str, path: str) -> bool:
        for s_ts, snap in self._undo:
            if s_ts == ts:
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump({'ts': s_ts, 'snapshot': snap}, f, ensure_ascii=False, indent=2)
                    return True
                except Exception:
                    return False
        return False

    def clear(self):
        self._undo.clear()
        self._redo.clear()

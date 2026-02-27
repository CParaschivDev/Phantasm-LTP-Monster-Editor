MU Monster + Spawn Editor (Monster.txt / MonsterList.xml / MonsterSpawn.xml)

Ce face:
- Editează Monster.txt (monștri: stats + nume + index)
- Regenerază MonsterList.xml automat din Monster.txt (ca să vezi mob-ul corect în joc)
- Editează MonsterSpawn.xml (spot-uri: maps / spots / spawns)

Cum rulezi:
1) Instalează Python 3.10+ (Windows)
2) Deschide CMD în folderul cu scriptul și rulează:
   python mu_monster_editor.py

3) În aplicație: Open Monster Folder... și selectezi folderul care conține:
   Monster.txt
   MonsterList.xml
   MonsterSpawn.xml

Siguranță:
- La fiecare save îți face backup automat:
  Monster.txt.bak_YYYYMMDD_HHMMSS
  MonsterList.xml.bak_...
  MonsterSpawn.xml.bak_...

Workflow recomandat:
1) Monsters tab: adaugi / editezi mob-ul în Monster.txt
2) Regenerate MonsterList.xml (sau Save ALL)
3) Spawns tab: pui spot/spawn în MonsterSpawn.xml
4) Save MonsterSpawn.xml (sau Save ALL)

Note:
- Dacă ai spawns care referă indecși lipsă din Monster.txt, în tabel vei vedea "(unknown)" și un warning.

Fixtures:
- Am adăugat un set de fixtures minimale în folderul `mu_monster_editor/fixtures` pentru test rapid:
   - Monster.txt
   - MonsterList.xml
   - MonsterSpawn.xml

Build / Executabil (pyinstaller):
- Pentru a crea un executabil Windows (opţional):

```powershell
pip install pyinstaller
pyinstaller --onefile mu_monster_editor.py --name "MU_Monster_Editor"
```

- Executabilul va fi în `dist/`.

Running with fixtures:
1) Rulează `python mu_monster_editor.py`
2) Click `Open Monster Folder...` și selectează `mu_monster_editor/fixtures` din repo
3) Verifică tab-urile `Monsters` și `Spawns`

Notes & safety:
- Backup automatic la salvare: `*.bak_YYYYMMDD_HHMMSS` pentru fiecare fișier.
- Dacă parser-ul nu poate interpreta complet un fișier, aplicația va afișa o eroare și nu va suprascrie originalul.
- `Dry-run validation` verifică referințele și range-urile fără a scrie fișiere.

Dacă vrei, pot genera un pachet MSI/EXE mai avansat sau un instalator; spune dacă preferi asta.

PySide6 GUI (modern)
---------------------
Am adăugat un GUI modern bazat pe `PySide6` în `gui_pyside.py`. Pentru a rula aplicația Qt:

```powershell
python gui_pyside.py
```

Acest GUI păstrează toate funcționalitățile: încărcare `Monster.txt`, editare tabelară, preview/regenerare `MonsterList.xml`, validare spawn-uri și `Save ALL`.

Construire EXE cu PyInstaller (Qt):

```powershell
pip install pyinstaller PySide6
pyinstaller --onefile gui_pyside.py --name "MU_Monster_Editor_Qt"
```

Observație: PyInstaller pentru PySide6 poate necesita includeri suplimentare pe anumite versiuni; vezi documentația PyInstaller dacă exe-ul lipsește resurse Qt.


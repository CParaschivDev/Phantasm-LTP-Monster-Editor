import os
from io_monster import parse_monster_txt
from io_list import render_monsterlist_string

FIX_DIR = os.path.join(os.path.dirname(__file__), '..', 'fixtures')


def test_parse_monsters():
    path = os.path.join(FIX_DIR, 'Monster.txt')
    mons, lines, enc = parse_monster_txt(path)
    assert isinstance(mons, list)
    assert len(mons) >= 1
    assert 'Index' in mons[0]


def test_render_monsterlist_contains_index():
    path = os.path.join(FIX_DIR, 'Monster.txt')
    mons, lines, enc = parse_monster_txt(path)
    xml = render_monsterlist_string(mons)
    # should contain Index="0" etc
    assert 'Index="0"' in xml
    assert 'Name="Slime"' in xml

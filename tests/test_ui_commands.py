from types import SimpleNamespace
import main as m
from main import FileManager
from PyQt5.QtCore import Qt


def test_on_list_selection_calls_execute():
    fm = FileManager()
    called = {}

    def fake_execute(cmd):
        called['cmd'] = cmd

    fm.execute_search_command = fake_execute

    # Replace fileListModel with a simple object to avoid C++ QModelIndex issues
    fm.fileListModel = SimpleNamespace(fileName=lambda idx: 'sample (one) [two]', setRootPath=lambda p: None, setFilter=lambda f: None, index=lambda p: None)

    class Sel:
        def indexes(self):
            return [object()]

    fm.on_listView_selectionChanged(Sel(), None)

    assert 'cmd' in called
    assert called['cmd'] == 'one|two'


class DummyEvent:
    def __init__(self, key_val):
        self._key = key_val

    def key(self):
        return self._key


def test_keypress_f3_f4_calls_execute():
    fm = FileManager()

    # Operate on the module-level globals defined in main
    m.global_keywords = ['a', 'b', 'c', 'd']
    m.ref_s = 0
    m.ref_e = 4

    called = []

    def fake_execute(cmd):
        called.append(cmd)

    fm.execute_search_command = fake_execute

    # Press F3 -> increment ref_s
    fm.keyPressEvent(DummyEvent(Qt.Key_F3))
    # Expected command should be everything except the first keyword
    assert called[-1] == 'b|c|d'

    # Press F4 -> decrement ref_e
    fm.keyPressEvent(DummyEvent(Qt.Key_F4))
    # Now ref_e reduced by 1, expected command uses ref_s..ref_e (ref_s still 1)
    assert called[-1] == 'b|c'

from main import FileManager
from PyQt5.QtWidgets import QApplication
import sys

# Ensure a QApplication exists for creating QWidget/QMainWindow instances
_app = QApplication.instance() or QApplication([])


def test_extract_keywords_basic():
    fm = FileManager()
    assert fm.extract_keywords('example (one) [two]') == ['one', 'two']


def test_extract_keywords_nested():
    fm = FileManager()
    # Nested brackets should produce separate keywords per nested segment
    assert fm.extract_keywords('nested (outer(inner))') == ['outer', 'inner']


def test_extract_keywords_empty_and_spaces():
    fm = FileManager()
    assert fm.extract_keywords('file (  ) (a  b)') == ['a  b']


def test_extract_keywords_no_brackets():
    fm = FileManager()
    assert fm.extract_keywords('no brackets here') == []


def test_extract_keywords_multiple_types():
    fm = FileManager()
    assert fm.extract_keywords('mix {alpha} and [beta] and (gamma)') == ['alpha', 'beta', 'gamma']

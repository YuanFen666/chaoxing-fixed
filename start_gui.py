# -*- coding: utf-8 -*-
"""一键启动新版 Python GUI：.venv-gui\\Scripts\\python.exe start_gui.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.app import main

if __name__ == "__main__":
    main()

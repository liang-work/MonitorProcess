import sys
from PySide6.QtWidgets import QApplication
from ui import ProcessMonitor
from exception_handler import handle_exception
from logging_setup import setup_logging


def main():
    setup_logging()
    sys.excepthook = handle_exception
    
    app = QApplication(sys.argv)
    window = ProcessMonitor()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

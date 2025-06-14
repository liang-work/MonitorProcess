import sys
import traceback
import logging
from PySide6.QtWidgets import QMessageBox, QApplication

def handle_exception(exc_type, exc_value, exc_traceback):
    """全局异常处理函数"""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.critical(f"程序发生未捕获异常: {error_msg}")
    show_error_dialog(error_msg)
    
    # 退出程序
    QApplication.quit()
    sys.exit(1)

def show_error_dialog(error_msg):
    """显示错误对话框"""
    error_dialog = QMessageBox()
    error_dialog.setIcon(QMessageBox.Critical)
    error_dialog.setWindowTitle("程序错误")
    error_dialog.setText("程序遇到意外错误，即将退出")
    error_dialog.setDetailedText(error_msg)
    error_dialog.setStandardButtons(QMessageBox.Ok)
    error_dialog.exec()

from PySide6.QtGui import QIcon
import os
import logging

def load_icon():
    """加载应用程序图标"""
    try:
        icon_path = os.path.join(os.path.dirname(__file__), "app_icon.png")
        if os.path.exists(icon_path):
            logging.debug(f"从本地文件加载图标: {icon_path}")
            return QIcon(icon_path)
        
        if QIcon.hasThemeIcon("system-run"):
            logging.debug("使用系统图标")
            return QIcon.fromTheme("system-run")
        
        logging.warning("未找到合适的图标")
        return QIcon()
    except Exception as e:
        logging.error(f"加载图标时出错: {e}")
        return QIcon()

def format_bytes(size):
    """格式化字节大小"""
    try:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} GB"
    except Exception as e:
        logging.error(f"格式化字节大小时出错: {e}")
        return "0 B"

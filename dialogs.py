from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, 
                              QFormLayout, QComboBox, QDialogButtonBox)
from PySide6.QtCore import Qt
import logging

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        logging.debug("初始化设置对话框")
        self.setWindowTitle("设置")
        self.resize(400, 300)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        form = QFormLayout()
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("深色主题", "dark")
        self.theme_combo.addItem("浅色主题", "light")
        form.addRow("界面主题:", self.theme_combo)
        
        self.list_refresh_combo = QComboBox()
        self.list_refresh_combo.addItem("列表刷新: 低 (3秒)", 3000)
        self.list_refresh_combo.addItem("列表刷新: 中 (2秒)", 2000)
        self.list_refresh_combo.addItem("列表刷新: 高 (1秒)", 1000)
        form.addRow("进程列表:", self.list_refresh_combo)
        
        self.monitor_refresh_combo = QComboBox()
        self.monitor_refresh_combo.addItem("监视刷新: 低 (0.5秒)", 500)
        self.monitor_refresh_combo.addItem("监视刷新: 中 (0.2秒)", 200)
        self.monitor_refresh_combo.addItem("监视刷新: 高 (0.1秒)", 100)
        form.addRow("监视区域:", self.monitor_refresh_combo)
        
        layout.addLayout(form)
        layout.addStretch()
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        logging.debug("初始化关于对话框")
        self.setWindowTitle("关于")
        self.resize(400, 300)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        title_label = QLabel("进程资源监视器")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignCenter)
        
        version_label = QLabel("版本 1.0")
        version_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(title_label)
        layout.addWidget(version_label)
        
        info_text = QLabel("""
        <p>这是一个高级进程资源监视工具，可以实时监控系统进程的资源使用情况。</p>
        <p>功能特点：</p>
        <ul>
            <li>精确的CPU使用率监控</li>
            <li>独立刷新的进程列表和监视区域</li>
            <li>全面的资源监控：CPU、内存、磁盘、网络、显卡</li>
            <li>显存占用监控</li>
            <li>主题切换功能</li>
        </ul>
        <p>© 2025 NRFF版权所有</p>
        """)
        info_text.setWordWrap(True)
        layout.addWidget(info_text)
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

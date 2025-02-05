import sys
import re
import json
import requests
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from queue import Queue
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QTextEdit, QLabel,
                             QFileDialog, QMessageBox, QGroupBox, QProgressBar,
                             QTabWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont


class RateLimiter:
    """速率限制器，控制请求频率"""

    def __init__(self, max_requests, time_window):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []

    def acquire(self):
        """获取许可，如果超过限制则等待"""
        current_time = time.time()

        # 清理过期的请求记录
        while self.requests and self.requests[0] <= current_time - self.time_window:
            self.requests.pop(0)

        # 如果当前请求数达到上限，等待
        if len(self.requests) >= self.max_requests:
            sleep_time = self.requests[0] + self.time_window - current_time
            if sleep_time > 0:
                time.sleep(sleep_time)
                return self.acquire()

        # 记录新的请求时间
        self.requests.append(current_time)
        return True


class LinkChecker(QThread):
    """用于检查链接的后台线程"""
    progress_signal = pyqtSignal(str, dict)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, links):
        super().__init__()
        self.links = links
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.is_running = True
        self.rate_limiter = RateLimiter(max_requests=20, time_window=60)

    def check_link(self, link):
        """检查单个链接"""
        if not self.is_running:
            return None

        # 等待速率限制
        self.rate_limiter.acquire()

        try:
            # 标准化链接格式
            if link.startswith('@'):
                link = f'https://t.me/{link[1:]}'
            elif not link.startswith('http'):
                link = f'https://t.me/{link}'

            response = requests.get(link, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')

            result = {
                '链接': link,
                '名称': '未知',
                '成员信息': '未知',
                '状态': '无效',
                '检查时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '重定向链接': ''
            }

            if response.url != link:
                result['重定向链接'] = response.url

            # 查找频道/群组名称
            title = soup.find('div', {'class': 'tgme_page_title'})
            if title:
                result['名称'] = title.text.strip()

            # 查找成员数量
            subscribers = soup.find('div', {'class': 'tgme_page_extra'})
            if subscribers:
                result['成员信息'] = subscribers.text.strip()

            result['状态'] = '有效' if title else '无效'
            return result

        except Exception as e:
            return {
                '链接': link,
                '名称': '错误',
                '成员信息': '未知',
                '状态': f'错误：{str(e)}',
                '检查时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '重定向链接': ''
            }

    def run(self):
        """运行检查任务"""
        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                for link in self.links:
                    if not self.is_running:
                        break
                    result = self.check_link(link.strip())
                    if result:
                        self.progress_signal.emit(link, result)
            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))

    def stop(self):
        """停止检查"""
        self.is_running = False


class TelegramToolsManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.check_results = {}
        self.links_to_remove = set()
        self.checker = None
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle('Telegram工具集')
        self.setGeometry(100, 100, 800, 600)

        # 创建主窗口部件和布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 创建选项卡
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # 设置各个选项卡
        self.setup_extract_tab()
        self.setup_check_tab()
        self.setup_compare_tab()
        self.setup_help_tab()

    def create_styled_button(self, text, callback):
        """创建统一风格的按钮"""
        button = QPushButton(text)
        button.setStyleSheet("""
            QPushButton {
                background-color: #4a90e2;
                color: white;
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #357abd;
            }
            QPushButton:pressed {
                background-color: #2a5d8c;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        button.clicked.connect(callback)
        return button

    def create_styled_text_edit(self, placeholder='', readonly=False):
        """创建统一风格的文本编辑框"""
        text_edit = QTextEdit()
        text_edit.setPlaceholderText(placeholder)
        text_edit.setReadOnly(readonly)
        text_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 5px;
                font-size: 12px;
            }
        """)
        return text_edit

    def setup_extract_tab(self):
        """设置链接提取选项卡"""
        extract_widget = QWidget()
        layout = QVBoxLayout(extract_widget)

        # 输入区域
        input_group = QGroupBox("文本输入")
        input_layout = QVBoxLayout()

        input_label = QLabel('输入包含Telegram链接的文本：')
        self.extract_input = self.create_styled_text_edit(
            placeholder="在此粘贴包含Telegram链接的文本...")

        input_layout.addWidget(input_label)
        input_layout.addWidget(self.extract_input)
        input_group.setLayout(input_layout)

        # 按钮区域
        button_layout = QHBoxLayout()
        load_btn = self.create_styled_button('加载文件', self.load_file_for_extract)
        extract_btn = self.create_styled_button('提取链接', self.extract_links_from_text)
        save_btn = self.create_styled_button('保存结果', self.save_extract_results)

        button_layout.addWidget(load_btn)
        button_layout.addWidget(extract_btn)
        button_layout.addWidget(save_btn)

        # 结果显示区域
        result_group = QGroupBox("提取结果")
        result_layout = QVBoxLayout()
        self.extract_result = self.create_styled_text_edit(readonly=True)
        result_layout.addWidget(self.extract_result)
        result_group.setLayout(result_layout)

        # 添加所有组件到布局
        layout.addWidget(input_group)
        layout.addLayout(button_layout)
        layout.addWidget(result_group)

        self.tabs.addTab(extract_widget, '链接提取')

    def setup_check_tab(self):
        """设置链接检查选项卡"""
        check_widget = QWidget()
        layout = QVBoxLayout(check_widget)

        # 输入区域
        input_group = QGroupBox("链接输入")
        input_layout = QVBoxLayout()

        input_label = QLabel('输入要检查的Telegram链接（每行一个）：')
        self.check_input = self.create_styled_text_edit(
            placeholder="在此输入要检查的链接，每行一个...")

        input_layout.addWidget(input_label)
        input_layout.addWidget(self.check_input)
        input_group.setLayout(input_layout)

        # 按钮区域
        button_layout = QHBoxLayout()
        self.start_check_btn = self.create_styled_button('开始检查', self.start_check)
        self.stop_check_btn = self.create_styled_button('停止检查', self.stop_check)
        self.save_check_btn = self.create_styled_button('保存结果', self.save_check_results)
        self.clear_check_btn = self.create_styled_button('清除结果', self.clear_check_results)

        self.stop_check_btn.setEnabled(False)
        self.save_check_btn.setEnabled(False)
        self.clear_check_btn.setEnabled(False)

        button_layout.addWidget(self.start_check_btn)
        button_layout.addWidget(self.stop_check_btn)
        button_layout.addWidget(self.save_check_btn)
        button_layout.addWidget(self.clear_check_btn)

        # 进度条
        self.check_progress = QProgressBar()
        self.check_progress.hide()

        # 结果显示区域
        result_group = QGroupBox("检查结果")
        result_layout = QVBoxLayout()
        self.check_result = self.create_styled_text_edit(readonly=True)
        result_layout.addWidget(self.check_result)
        result_group.setLayout(result_layout)

        # 添加所有组件到布局
        layout.addWidget(input_group)
        layout.addLayout(button_layout)
        layout.addWidget(self.check_progress)
        layout.addWidget(result_group)

        self.tabs.addTab(check_widget, '链接检查')

    def setup_compare_tab(self):
        """设置链接比较选项卡"""
        compare_widget = QWidget()
        layout = QVBoxLayout(compare_widget)

        # 按钮区域
        button_layout = QHBoxLayout()
        compare_btn = self.create_styled_button('选择文件比较', self.compare_files)
        remove_btn = self.create_styled_button('删除重复链接', self.remove_duplicate_links)
        remove_btn.setEnabled(False)
        self.remove_btn = remove_btn

        button_layout.addWidget(compare_btn)
        button_layout.addWidget(remove_btn)

        # 结果显示区域
        result_group = QGroupBox("比较结果")
        result_layout = QVBoxLayout()
        self.compare_result = self.create_styled_text_edit(readonly=True)
        result_layout.addWidget(self.compare_result)
        result_group.setLayout(result_layout)

        # 添加所有组件到布局
        layout.addLayout(button_layout)
        layout.addWidget(result_group)

        self.tabs.addTab(compare_widget, '链接比较')

    def setup_help_tab(self):
        """设置帮助选项卡"""
        help_widget = QWidget()
        layout = QVBoxLayout(help_widget)

        help_text = """
        Telegram工具集使用说明：

        1. 链接提取
        - 支持从文本中提取Telegram链接
        - 可以直接粘贴文本或加载文本文件
        - 支持保存提取的链接到文件

        2. 链接检查
        - 检查Telegram链接的有效性
        - 获取频道/群组的基本信息
        - 支持批量检查多个链接
        - 为避免请求过于频繁，限制每分钟最多检查20个链接

        3. 链接比较
        - 比较两个文件中的链接
        - 找出重复的链接
        - 可以删除文件中的重复链接

        注意事项：
        - 请遵守Telegram的使用政策
        - 建议不要一次性检查太多链接
        - 如果遇到问题，可以先尝试停止操作后重试
        """

        help_label = QTextEdit()
        help_label.setPlainText(help_text)
        help_label.setReadOnly(True)
        help_label.setStyleSheet("""
            QTextEdit {
                border: none;
                background-color: transparent;
                font-size: 12px;
            }
        """)

        layout.addWidget(help_label)
        self.tabs.addTab(help_widget, '帮助')

    def load_file_for_extract(self):
        """加载文件用于提取链接"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, '选择文件', '', 'Text Files (*.txt);;All Files (*)'
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    text = file.read()
                    self.extract_input.setText(text)
                    self.extract_links_from_text()
            except Exception as e:
                QMessageBox.critical(self, '错误', f'读取文件时发生错误：{str(e)}')

    def extract_links_from_text(self):
        """从输入文本中提取链接"""
        text = self.extract_input.toPlainText()
        links = self.extract_links(text)
        if links:
            self.extract_result.setText('\n'.join(links))
        else:
            self.extract_result.setText('未找到任何Telegram链接')

    def extract_links(self, text):
        """从文本中提取Telegram链接"""
        pattern = r'(?:https://t\.me/|@)([A-Za-z0-9_]+)'
        matches = re.findall(pattern, text)
        return [f'https://t.me/{username.replace("@", "")}' for username in matches]

    def save_extract_results(self):
        """保存提取的链接"""
        links = self.extract_result.toPlainText().strip()
        if not links:
            QMessageBox.warning(self, '提示', '没有可保存的链接！')
            return

        self.save_to_file(links, '保存提取结果')

    def start_check(self):
        """开始检查链接"""
        text = self.check_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, '提示', '请输入要检查的链接！')
            return

        links = [link.strip() for link in text.split('\n') if link.strip()]
        if not links:
            QMessageBox.warning(self, '提示', '没有找到有效的链接！')
            return

        if len(links) > 50:
            reply = QMessageBox.question(self, '确认',
                                         f'您输入了{len(links)}个链接，检查可能需要较长时间。是否继续？',
                                         QMessageBox.StandardButton.Yes |
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        self.check_results.clear()
        self.check_result.clear()
        self.check_result.append("开始检查链接...\n")
        self.check_result.append(f"注意：为避免请求过于频繁，限制每分钟最多检查20个链接\n")

        # 设置UI状态
        self.start_check_btn.setEnabled(False)
        self.stop_check_btn.setEnabled(True)
        self.save_check_btn.setEnabled(False)
        self.clear_check_btn.setEnabled(False)
        self.check_input.setReadOnly(True)

        # 设置进度条
        self.check_progress.setMaximum(len(links))
        self.check_progress.setValue(0)
        self.check_progress.show()

        # 启动检查线程
        self.checker = LinkChecker(links)
        self.checker.progress_signal.connect(self.update_check_result)
        self.checker.finished_signal.connect(self.check_finished)
        self.checker.error_signal.connect(self.handle_check_error)
        self.checker.start()

    def stop_check(self):
        """停止检查"""
        if self.checker:
            self.checker.stop()
            self.stop_check_btn.setEnabled(False)

    def update_check_result(self, link, result):
        """更新检查结果"""
        self.check_results[link] = result

        formatted_result = (
            f"链接: {result['链接']}\n"
            f"名称: {result['名称']}\n"
            f"成员信息: {result['成员信息']}\n"
            f"状态: {result['状态']}\n"
            f"检查时间: {result['检查时间']}\n"
        )
        if result['重定向链接']:
            formatted_result += f"重定向到: {result['重定向链接']}\n"
        formatted_result += f"{'-' * 50}\n"

        self.check_result.append(formatted_result)
        self.check_progress.setValue(len(self.check_results))

    def check_finished(self):
        """检查完成处理"""
        self.check_result.append("\n检查完成！")

    def clear_check_results(self):
        """清除检查结果"""
        self.check_results.clear()
        self.check_result.clear()
        self.check_progress.setValue(0)
        self.check_progress.hide()
        self.save_check_btn.setEnabled(False)
        self.clear_check_btn.setEnabled(False)

    def save_check_results(self):
        """保存检查结果"""
        if not self.check_results:
            QMessageBox.warning(self, '提示', '没有可保存的结果！')
            return

        # 准备保存的内容
        content = []
        for result in self.check_results.values():
            formatted_result = (
                f"链接: {result['链接']}\n"
                f"名称: {result['名称']}\n"
                f"成员信息: {result['成员信息']}\n"
                f"状态: {result['状态']}\n"
                f"检查时间: {result['检查时间']}\n"
            )
            if result['重定向链接']:
                formatted_result += f"重定向到: {result['重定向链接']}\n"
            formatted_result += f"{'-' * 50}\n"
            content.append(formatted_result)

        self.save_to_file('\n'.join(content), '保存检查结果')

    def compare_files(self):
        """比较两个文件中的链接"""
        # 选择第一个文件
        file1_path, _ = QFileDialog.getOpenFileName(
            self, '选择第一个文件', '', 'Text Files (*.txt);;All Files (*)'
        )
        if not file1_path:
            return

        # 选择第二个文件
        file2_path, _ = QFileDialog.getOpenFileName(
            self, '选择第二个文件', '', 'Text Files (*.txt);;All Files (*)'
        )
        if not file2_path:
            return

        try:
            # 读取并提取两个文件中的链接
            with open(file1_path, 'r', encoding='utf-8') as f1, \
                    open(file2_path, 'r', encoding='utf-8') as f2:
                links1 = set(self.extract_links(f1.read()))
                links2 = set(self.extract_links(f2.read()))

            # 计算重复的链接
            duplicates = links1.intersection(links2)
            self.links_to_remove = duplicates

            # 显示比较结果
            self.compare_result.clear()
            self.compare_result.append(f"文件1中的链接数: {len(links1)}")
            self.compare_result.append(f"文件2中的链接数: {len(links2)}")
            self.compare_result.append(f"重复的链接数: {len(duplicates)}\n")

            if duplicates:
                self.compare_result.append("重复的链接:")
                for link in sorted(duplicates):
                    self.compare_result.append(link)
                self.remove_btn.setEnabled(True)
            else:
                self.compare_result.append("没有找到重复的链接")
                self.remove_btn.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, '错误', f'比较文件时发生错误：{str(e)}')
            self.remove_btn.setEnabled(False)

    def remove_duplicate_links(self):
        """从文件中删除重复的链接"""
        if not self.links_to_remove:
            QMessageBox.warning(self, '提示', '没有需要删除的重复链接！')
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, '选择要删除重复链接的文件', '', 'Text Files (*.txt);;All Files (*)'
        )
        if not file_path:
            return

        try:
            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取所有链接
            all_links = self.extract_links(content)

            # 过滤掉重复的链接
            filtered_links = [link for link in all_links
                              if link not in self.links_to_remove]

            # 保存结果
            save_path, _ = QFileDialog.getSaveFileName(
                self, '保存结果', '', 'Text Files (*.txt);;All Files (*)'
            )
            if save_path:
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(filtered_links))
                QMessageBox.information(
                    self, '成功',
                    f'已删除 {len(all_links) - len(filtered_links)} 个重复链接\n'
                    f'结果已保存到：{save_path}'
                )

        except Exception as e:
            QMessageBox.critical(self, '错误', f'删除重复链接时发生错误：{str(e)}')

    def save_to_file(self, content, title='保存文件'):
        """通用文件保存方法"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, title, '', 'Text Files (*.txt);;All Files (*)'
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                QMessageBox.information(self, '成功', f'文件已保存到：{file_path}')
                return True
            except Exception as e:
                QMessageBox.critical(self, '错误', f'保存文件时出错：{str(e)}')
                return False
        return False


def main():
    app = QApplication(sys.argv)

    # 设置应用程序样式
    app.setStyle('Fusion')

    # 设置全局字体
    font = QFont('Arial', 10)
    app.setFont(font)

    # 创建并显示主窗口
    window = TelegramToolsManager()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
from PyQt5.QtCore import Qt, QUrl, QSize, QThread, QTimer
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QListWidgetItem, QSlider,
                             QStyle, QTableWidgetItem, QFrame)
from PyQt5.QtWidgets import QMainWindow, QPushButton, QAction, QHeaderView, QGraphicsOpacityEffect
from PyQt5.QtGui import QIcon, QColor, QFont, QPixmap, QTransform
import sys
import os
import time
from main_window import Ui_MainWindow
from my_popup import Ui_Dialog
from songs_data import SongsDataManager
import pickle
from scipy.io import wavfile
import numpy as np
from scipy import fft
import globals
from PyQt5.QtCore import pyqtSignal
import subprocess


class ProcessingFilesThread(QThread):
    def __init__(self, parent=None, main_widget=None, names=[]):
        super(ProcessingFilesThread, self).__init__(parent)
        self.main_widget = main_widget
        self.names = names

    def run(self):
        file_to_style_dict = {}
        has_error = False

        for name in self.names:
            try:
                if name.endswith('.mp3') or name.endswith('.wav'):
                    wav_name = './converted/' + os.path.basename(name)[:-4] + '.wav'
                    subprocess.run(['./bin/ffmpeg.exe', '-y', '-i', name, '-ar', '8000', wav_name])
                else:
                    raise Exception('歌曲格式不支持')
                sample_rate, x = wavfile.read(wav_name)
                if len(x.shape) > 1:
                    x = x[:, 0]
                if x.shape[0] / sample_rate < 10:
                    raise Exception('歌曲长度少于10秒')
                x = abs(fft(x)[:1000])
                x = np.array(x).reshape(1, -1)
                y = self.main_widget.model.predict(x)[0]
                if 0 <= y < len(globals.styles):
                    file_to_style_dict[name] = y
                else:
                    raise Exception('歌曲未能被识别')
            except Exception as e:
                has_error = True
                err_str = '导入失败' + os.linesep + os.path.basename(name) + ': ' + str(e)
                break

        while_count = 0
        while True:
            time.sleep(1)
            if hasattr(self.main_widget, 'progress_window'):
                if self.main_widget.progress_window.isActiveWindow():
                    break
            while_count += 1
            if while_count == 10:
                break

        if has_error:
            self.main_widget.detected_result_str = err_str
            self.main_widget.signal_close_popup.emit()
            return

        name_to_style_dict = {}
        for name in self.names:
            style = globals.styles[file_to_style_dict[name]]
            name_to_style_dict[name] = style
            self.main_widget.songs_data.setdefault(style, {})
            if name not in self.main_widget.songs_data[style]:
                self.main_widget.songs_data[style].setdefault(name, {})

        self.main_widget.songs_data_manager.write_songs_data(self.main_widget.songs_data)
        self.main_widget.detected_result_str = ''
        for name, style in name_to_style_dict.items():
            self.main_widget.detected_result_str += os.path.basename(name) + '已被识别为' +\
                                        globals.styles_chinese[globals.styles.index(style)] + os.linesep

        self.main_widget.signal_close_popup.emit()


class MyPopup(QDialog, Ui_Dialog):
    def __init__(self, has_close=False, main_widget=None):
        QDialog.__init__(self)
        Ui_Dialog.__init__(self)
        self.setupUi(self)
        self.setWindowTitle(' ')
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        if not has_close:
            self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setWindowModality(Qt.ApplicationModal)
        if main_widget:
            main_widget.signal_close_popup.connect(self.on_close_signal_received)

    def on_close_signal_received(self):
        self.close()


class MyMainForm(QMainWindow, Ui_MainWindow):
    signal_close_popup = pyqtSignal()

    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent)
        Ui_MainWindow.__init__(self)
        self.setupUi(self)

        self.setWindowTitle(' ')
        self.setWindowFlags(Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint | Qt.MSWindowsFixedSizeDialogHint)

        self.songs_data_manager = SongsDataManager()
        self.songs_data = self.songs_data_manager.read_songs_data()

        self.playlist_items = []
        self.selected_style_index = -1
        self.selected_song_name = ''  # single click selected
        self.last_ignited_style_index = -1
        self.location_root = os.getcwd()

        self.video_widget = QVideoWidget()

        self.back_btn.clicked.connect(self._on_back_to_style_view)
        self.delete_btn.clicked.connect(self._on_delete_item)

        self.playlist.itemClicked.connect(self._on_playlist_item_clicked)
        self.playlist.itemDoubleClicked.connect(self._on_playlist_item_double_clicked)

        self.playlist_widget.setVisible(False)

        self.media_player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.notify_interval = 100
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.setNotifyInterval(self.notify_interval)
        self.media_player.stateChanged.connect(self.media_state_changed)
        self.media_player.positionChanged.connect(self.play_time_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.error.connect(self.handle_error)

        self.detected_result_str = ''
        with open('music_model.pkl', 'rb') as fp:
            self.model = pickle.load(fp)

        # buttons

        import_btn_pixmap = QPixmap('res/import_btn.png')
        import_btn_icon = QIcon(import_btn_pixmap)
        self.import_btn.setIcon(import_btn_icon)
        self.import_btn.setIconSize(import_btn_pixmap.size())
        self.import_btn.setMask(import_btn_pixmap.mask())
        self.import_btn.clicked.connect(self._import_files)

        for i in range(globals.style_num):
            style_btn = getattr(self, 'style_btn_%i' % (i + 1))
            style_btn_pixmap = QPixmap('res/%s.png' % (i + 1))
            style_btn_icon = QIcon(style_btn_pixmap)
            style_btn.setIcon(style_btn_icon)
            style_btn.setIconSize(style_btn_pixmap.size())
            style_btn.setMask(style_btn_pixmap.mask())
            style_btn.clicked.connect(lambda state, selected_index=i: self._change_to_playlist_view(selected_index))

        self.rotate_pixmap_origin = QPixmap('res/rotate_note.png')
        self.rotate_angle = 0

        op = QGraphicsOpacityEffect()
        op.setOpacity(0)
        self.play_pause_btn.setGraphicsEffect(op)
        self.play_pause_btn.setMask(self.rotate_pixmap_origin.mask())
        self.play_pause_btn.clicked.connect(self.play_or_pause)

        self.rotate_note_label.setAlignment(Qt.AlignCenter)
        self.rotate_note_label.setPixmap(self.rotate_pixmap_origin)

        background_pixmap = QPixmap('res/background.png')
        self.background_label.setPixmap(background_pixmap)

        self.should_rotate = False
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_rotate_timer)
        self.timer.start(30)

    def closeEvent(self, event):
        self.media_player.pause()
        self.timer.stop()

    def _on_rotate_timer(self):
        if not self.should_rotate:
            return
        self.rotate_angle += 0.5
        transform = QTransform().rotate(self.rotate_angle)
        rotate_pixmap = self.rotate_pixmap_origin.transformed(transform, Qt.SmoothTransformation)
        self.rotate_note_label.setPixmap(rotate_pixmap)

    def _set_styles_stuff_visibility(self, visibility):
        for i in range(globals.style_num):
            style_btn = getattr(self, 'style_btn_%i' % (i + 1))
            style_btn.setVisible(visibility)
        self.import_btn.setVisible(visibility)
        self.play_pause_btn.setVisible(visibility)
        self.rotate_note_label.setVisible(visibility)

    def _ignite_selected_style(self, selected_style_index):
        if self.last_ignited_style_index != -1:
            style_btn = getattr(self, 'style_btn_%i' % (self.last_ignited_style_index + 1))
            style_btn_pixmap = QPixmap('res/%s.png' % (self.last_ignited_style_index + 1))
            style_btn_icon = QIcon(style_btn_pixmap)
            style_btn.setIcon(style_btn_icon)
            style_btn.setIconSize(style_btn_pixmap.size())
        style_btn_ignited = getattr(self, 'style_btn_%i' % (selected_style_index + 1))
        style_btn_ignited_pixmap = QPixmap('res/%s-2.png' % (selected_style_index + 1))
        style_btn_ignited_icon = QIcon(style_btn_ignited_pixmap)
        style_btn_ignited.setIcon(style_btn_ignited_icon)
        style_btn_ignited.setIconSize(style_btn_ignited_pixmap.size())
        self.last_ignited_style_index = selected_style_index

    def _change_to_playlist_view(self, style_index):
        self._set_styles_stuff_visibility(False)
        self.playlist_widget.setVisible(True)
        self.selected_style_index = style_index
        self._refresh_playlist()

    def _refresh_playlist(self):
        if self.selected_style_index == -1:
            return
        files = self.songs_data.get(globals.styles[self.selected_style_index], [])
        self.playlist_items = []
        self.playlist.clear()
        flip_count = False
        for file in files:
            flip_count = False if flip_count else True
            list_item = QListWidgetItem(os.path.basename(file))
            setattr(list_item, 'full_file_name', file)
            list_item.setBackground(Qt.lightGray if flip_count else Qt.white)
            self.playlist_items.append(list_item)
            self.playlist.addItem(list_item)

    def _on_back_to_style_view(self):
        self._set_styles_stuff_visibility(True)
        self.playlist_widget.setVisible(False)
        self.selected_song_name = ''
        self.delete_btn.setEnabled(False)

    @staticmethod
    def _pop_message_box(alert_text):
        result_window = MyPopup(has_close=True)
        result_window.label.setText(alert_text)
        result_window.exec()

    def _on_playlist_item_clicked(self, item):
        self.selected_song_name = getattr(item, 'full_file_name')
        self.delete_btn.setEnabled(True)

    def _on_playlist_item_double_clicked(self, item):
        if self.selected_style_index == -1:
            return
        filename = getattr(item, 'full_file_name')
        if os.path.isfile(filename):
            self.media_player.setMedia(QMediaContent(QUrl.fromLocalFile(filename)))
            self.play_or_pause()
            self._ignite_selected_style(self.selected_style_index)
        else:
            self._pop_message_box('找不到文件:%s' % filename)

    def _on_delete_item(self):
        if not self.selected_song_name:
            return
        if self.selected_style_index == -1:
            return
        self.songs_data[globals.styles[self.selected_style_index]].pop(self.selected_song_name, None)
        self.songs_data_manager.write_songs_data(self.songs_data)
        self._refresh_playlist()

    def _import_files(self):
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFiles)
        names = file_dialog.getOpenFileNames(None, 'open wav file', '.', 'AUDIO(*.wav *.mp3)')
        if not names[0]:
            return
        if not isinstance(names[0], list):
            audio_names = [names[0]]
        else:
            audio_names = names[0]
        self.processing_files_thread = ProcessingFilesThread(main_widget=self, names=audio_names)
        self.processing_files_thread.start()
        self.progress_window = MyPopup(main_widget=self)
        self.progress_window.exec()
        self.processing_files_thread.wait()
        self._pop_message_box(self.detected_result_str)

    def play_or_pause(self):
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.should_rotate = False
        else:
            self.media_player.play()
            self.should_rotate = True

    def media_state_changed(self, state):
        pass

    def play_time_changed(self, play_time):
        pass

    def duration_changed(self, duration):
        pass

    def set_position(self, position):
        self.media_player.setPosition(position)

    def handle_error(self):
        pass


if __name__ == '__main__':
    if os.path.exists('converted'):
        for f in os.listdir('converted'):
            os.remove('converted/' + f)
        os.rmdir('converted')
    os.mkdir('converted')
    app = QApplication(sys.argv)
    app_icon = QIcon()
    app_icon.addFile('res/main_window_icon.jpg', QSize(16, 16))
    app.setWindowIcon(app_icon)
    myWin = MyMainForm()
    myWin.show()
    sys.exit(app.exec_())

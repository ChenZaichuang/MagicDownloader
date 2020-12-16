import math

import PySimpleGUI as sg
from gevent import spawn, sleep

from .base_window import BaseWindow
from ..http_downloader import HttpMultiThreadDownloader


class MainWindow(BaseWindow):

    cls_window_tag = 'main_window'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = False
        self.download_task = None
        self.print_task = None

    def design_layout(self):
        return [[sg.Text('Input Link Address: '), sg.Input('', key='-LINK ADDRESS-', size=(30, 1)), sg.Button('Download', key='-BUTTON-')],
                [sg.ProgressBar(1, orientation='h', size=(60, 20), key='progress')],
                [sg.Multiline(size=(40, 1), enter_submits=True, key='Download Status', do_not_clear=True, disabled=True)]]

    def inputs_to_bind_shortcut(self):
        return ['-LINK ADDRESS-']

    def stop_download(self):
        self.started = False
        self.download_task.stop()
        self.print_task.kill()
        self.window['-BUTTON-'].update("Download")
        self.window['-LINK ADDRESS-'].update(disabled=False)
        self.window['Download Status'].Update('')

    def start_print_task(self):
        while True:
            progress = self.download_task.calculate_progress_once()
            finish_percent = progress['finish_percent']
            done = math.floor(50 * finish_percent)
            show_text = "\r[%s%s] %.2f%% %.2fMB|%.2fMB %.3fMB/s %ds" % ('█' * done, ' ' * (50 - done), 100 * finish_percent, math.floor(progress['downloaded_size'] / 1024 / 10.24) / 100, math.floor(self.download_task.total_size / 1024 / 10.24) / 100, math.floor(progress['downloaded_size_in_period'] / 1024 / 1.024) / 1000, progress['total_seconds'])
            print(show_text)
            res = self.window['progress'].UpdateBar(finish_percent, 1)
            if not res:
                print("UpdateBar fail")

            self.window['Download Status'].Update("%.2f%% %.2fMB|%.2fMB %.3fMB/s %ds" % (100 * finish_percent, math.floor(progress['downloaded_size'] / 1024 / 10.24) / 100, math.floor(self.download_task.total_size / 1024 / 10.24) / 100, math.floor(progress['downloaded_size_in_period'] / 1024 / 1.024) / 1000, progress['total_seconds']))
            if finish_percent == 1:
                self.started = False
                self.window['-BUTTON-'].update("Download")
                self.window['-LINK ADDRESS-'].update(disabled=False)
                break
            sleep(1)

    def start_download(self, url):
        self.started = True
        self.window['-BUTTON-'].update("Stop")
        self.window['-LINK ADDRESS-'].update(disabled=True)
        self.download_task = HttpMultiThreadDownloader(url=url, thread_number=64, print_progress=False, download_strategy='best_ip')
        spawn(self.download_task.download)
        self.print_task = spawn(self.start_print_task)

    def handle_event(self, event_name, event_value):

        if event_name == '-BUTTON-':
            if not self.started:
                url = self.window.Element('-LINK ADDRESS-').Get()
                if url == '':
                    sg.popup("please input download link address")
                else:
                    self.start_download(url)
            else:
                self.stop_download()

        elif event_name == 'show':
            self.show_window()

import PySimpleGUI as sg
from gevent import sleep

from module.window.main_window import MainWindow

sg.set_options(font=("Any", 25))


class App:

    def start(self):
        main_window = MainWindow()

        main_window.show_window()
        while True:
            sleep(999999)

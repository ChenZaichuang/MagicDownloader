import os
import sys
import traceback
import PySimpleGUI as sg
from gevent.queue import Queue
from gevent import spawn, sleep



class PasteMonitor:
    def __init__(self, window_entity, key):
        self.window_entity = window_entity
        self.key = key

    def callback(self, event):
        value = event.widget.clipboard_get()
        self.window_entity.event_queue.put((self.key, {self.key: value}))
        self.window_entity.window[self.key].Update(value)

    def bind(self, element):
        element.bind('<Command-v>', self.callback)


class CutMonitor:
    def __init__(self, window_entity, key):
        self.window_entity = window_entity
        self.key = key

    def callback(self, event):
        self.window_entity.event_queue.put((self.key, {self.key: ''}))
        self.window_entity.window[self.key].Update('')

    def bind(self, element):
        element.bind('<Command-x>', self.callback)


class BaseWindow:
    window_name = 'Super VPN'
    window_map = dict()
    cls_window_tag = ''

    def __init__(self, **kwargs):
        self.window_tag = kwargs.get('window_tag', self.cls_window_tag)
        assert self.window_tag not in BaseWindow.window_map
        BaseWindow.window_map[self.window_tag] = self
        self.event_queue = Queue()
        self.hidden = kwargs.get('hidden', True)
        self.window = None
        self.layout = self.design_layout()
        self.need_bind_shortcuts = True
        spawn(self.handle_event_job)

    def design_layout(self):
        return []

    def inputs_to_bind_shortcut(self):
        return []

    def multilines_to_bind_shortcut(self):
        return []

    def send_request(self, event_name, func, args=None, kwargs=None):
        if args is None:
            args = tuple()
        if kwargs is None:
            kwargs = dict()

        def send():
            try:
                res = func(*args, **kwargs)
                self.event_queue.put((event_name, res))
            except:
                res = traceback.format_exc()
                self.event_queue.put(("exception happen", res))

        spawn(send)

    def send_event_to_window(self, window_tag, event_name, event_value=None):
        assert window_tag in BaseWindow.window_map, f'{window_tag} tag not found'
        window_entity = BaseWindow.window_map[window_tag]
        window_entity.event_queue.put((event_name, event_value))

    def broadcast(self, event_name, event_value):
        for window_tag, window_entity in BaseWindow.window_map.items():
            if window_tag != self.window_tag:
                window_entity.event_queue.put((event_name, event_value))

    def make_window(self):
        self.window = sg.Window(self.window_name, layout=self.layout, finalize=True, icon=f'{os.environ["PROJECT_ROOT"]}/icon/magic.icns')
        self.make_window_center()
        self.int()
        spawn(self.read_from_window)

    def make_window_center(self):
        screen_w, screen_h = sg.Window.get_screen_size()
        window_w, window_h = self.window.size
        window_h += 22
        self.window.Move((screen_w - window_w) // 2, (screen_h - window_h) // 2)

    def handle_event_job(self):
        while True:
            try:
                e = self.event_queue.get()
                event_name, event_value = e
                if event_name == "exception happen":
                    sg.popup("Exception happen, please contact developer for help.")
                else:
                    self.handle_event(event_name, event_value)
            except Exception:
                sg.popup("Exception happen, please contact developer for help.")

    def int(self):
        pass

    def handle_event(self, event_name, event_value):
        pass

    def check_required_values(self, element_key_list):
        for key in element_key_list:
            if self.window.Element(key).Get() == '':
                sg.popup(f"{key} is required !")
                return False
        return True

    def bind_input(self, key):
        def select_all_callback(event):
            # select text
            event.widget.select_range(0, 'end')
            # move cursor to the end
            event.widget.icursor('end')
            #stop propagation
            return 'break'
        element = self.window.Element(key).TKEntry
        element.bind('<Command-a>', select_all_callback)
        # PasteMonitor(self, key).bind(element)
        CutMonitor(self, key).bind(element)

    def bind_multiline(self, key):
        def select_all_callback(event):
            # select text
            event.widget.tag_add('sel', '1.0', 'end')
            return 'break'
        element = self.window.Element(key).TKText
        element.bind('<Command-a>', select_all_callback)
        PasteMonitor(self, key).bind(element)
        CutMonitor(self, key).bind(element)

    def read_from_window(self):
        while True:
            sleep(0.001)
            try:
                event, values = self.window.read(timeout=1)
            except Exception:
                continue
            if self.need_bind_shortcuts:
                self.need_bind_shortcuts = False
                for input_key in self.inputs_to_bind_shortcut():
                    self.bind_input(input_key)
                for multiline_key in self.multilines_to_bind_shortcut():
                    self.bind_multiline(multiline_key)
            if event == "__TIMEOUT__":
                continue
            if event == sg.WIN_CLOSED:
                sys.exit()
            self.event_queue.put((event, values))
        sys.exit()

    def show_window(self):
        if self.window is None:
            self.make_window()
        else:
            self.window.UnHide()

    def hide_window(self):
        self.window.Hide()

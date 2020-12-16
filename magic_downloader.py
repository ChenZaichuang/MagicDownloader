from gevent import monkey
monkey.patch_all(thread=False)
import sys
import os
from os import path

os.environ["PROJECT_ROOT"] = f"{getattr(sys, '_MEIPASS', path.abspath(path.dirname(__file__)))}"


from module.app import App


if __name__ == '__main__':

    App().start()

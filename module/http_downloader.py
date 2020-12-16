import ssl
import traceback

import gevent
from gevent import monkey, timeout, Timeout, signal_handler, spawn, greenlet
from greenlet import GreenletExit

monkey.patch_all(thread=False)

from gevent.lock import BoundedSemaphore
from gevent import sleep
from gevent.queue import Queue
import dns.resolver
from signal import SIGINT

import re
import subprocess
import datetime
import math
import os
import pickle
import sys
import requests
import logging

import tkinter as tk

requests.packages.urllib3.disable_warnings()

# LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
# logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)

sys.setrecursionlimit(2000)


class HttpMultiThreadDownloader:

    TOTAL_BUFFER_SIZE = 1024 * 1024 * 64
    CHUNK_SIZE = 1024
    MIN_TASK_CHUNK_SIZE = 2 * CHUNK_SIZE
    DEFAULT_THREAD_NUMBER = 32

    DNS_SERVERS = ['119.29.29.29',
                   '182.254.116.116',
                   '114.114.114.114',
                   '223.5.5.5',
                   '223.6.6.6',
                   '180.76.76.76',
                   '9.9.9.9',
                   '8.8.8.8']

    headers = {"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36", 'Accept-Language':'zh-CN,zh;q=0.9', 'Accept': '*'}

    # headers = {
    #     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    #     # "Accept-Encoding": "gzip, deflate, br",
    #     "Accept-Language": "en,en-US;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    #     "Cache-Control": "max-age=0",
    #     "Connection": "keep-alive",
    #     "Host": "r3---sn-n4v7knls.googlevideo.com",
    #     "Sec-Fetch-Dest": "document",
    #     "Sec-Fetch-Mode": "navigate",
    #     "Sec-Fetch-Site": "none",
    #     "Sec-Fetch-User": "?1",
    #     "Upgrade-Insecure-Requests": "1",
    #     "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.135 Safari/537.36",
    #     # "X-Client-Data": "CIS2yQEIprbJAQjBtskBCKmdygEI06HKAQiWrMoBCIa1ygEImbXKAQj3x8oBCOfIygEI6cjKAQiW1soBCLzXygE="
    # }

    def __init__(self, url=None, file_name=None, path_to_store=None, total_size=None, thread_number=None, logger=None, print_progress=False, download_strategy='best_ip'):

        assert url or file_name

        file_name = file_name if file_name else url.split('?')[0].split('/')[-1]
        file_name_split = file_name.split('.')
        if len(file_name_split[0]) > 64:
            file_name_split[0] = file_name_split[0][:64]
        file_name = '.'.join(file_name_split)
        self.path_to_store = path_to_store if path_to_store else f"{os.environ['HOME']}/Downloads"

        self.logger = logger or logging
        self.print_progress = print_progress
        self.url = url
        self.download_strategy = download_strategy

        url_spilts = re.match(r"(https?://)([^/]+)(.+)", self.url).groups()
        self.schema = url_spilts[0]
        self.host = url_spilts[1]
        self.headers['Host'] = self.host
        print(self.headers)
        self.path = "" if len(url_spilts) < 3 else url_spilts[2]

        print(self.schema)
        print(self.host)
        print(self.path)

        if self.download_strategy == 'best_ip':
            self.best_ip = self.host
            self.best_ip = self._get_best_ip()
            print(f"best ip: {self.best_ip}")
        else:
            self.ip_pool = Queue()
            for ip in self._get_ip_set():
                self.ip_pool.put(ip)

        self.total_size = total_size
        self.file_name_with_path = self.path_to_store + '/' + file_name
        self.breakpoint_file_path = self.file_name_with_path + '.tmp'
        self.file_seeker = None
        self.thread_number = thread_number
        self.thread_buffer_size = None
        self.remaining_segments = []
        self.remaining_segments_lock = BoundedSemaphore()
        self.written_segments = []
        self.start_time = None
        self.segment_dispatch_task = None
        self.progress_show_task = None
        self.bytearray_of_threads = None
        self.last_progress_time = None
        self.last_downloaded_size = 0
        self.workers = []
        self.coworker_end_to_indexes_map = dict()
        self.to_dispatcher_queue = Queue()
        self.download_info = self.get_download_info()
        self.all_done = False
        self.almost_done = False

        self.to_store_queue = Queue()
        self.segment_store_task = None

    def get_ip(self):
        if self.download_strategy == 'best_ip':
            return self.best_ip
        else:
            ip = self.ip_pool.get()
            self.ip_pool.put(ip)
            return ip

    def _get_ip_from_dns_server(self, dns_server, ip_result_set, timeout_value=5):
        try:
            with Timeout(timeout_value):
                resolver = dns.resolver.Resolver()
                resolver.nameservers = [dns_server]
                answers = resolver.query(self.host, 'A')
                for answer in answers:
                    ip_result_set.add(answer.to_text())
        except (timeout.Timeout, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            pass

    def _get_response_from_ip(self, ip, queue):
        try:
            print(f"{self.schema}{ip}{self.path}")
            res = requests.get(f"{self.schema}{ip}{self.path}", stream=True, verify=False, headers=self.headers)
            print(f'ip: {ip}, sttaus_code: {res.status_code}')
            if int(res.status_code / 100) == 2 and 'Content-Length' in res.headers:
                self.total_size = int(res.headers['Content-Length'])
                queue.put(ip)
        except:
            pass

    def _get_ip_set(self):
        ip_result_set = set()
        gevent.joinall([spawn(self._get_ip_from_dns_server, dns_server, ip_result_set) for dns_server in self.DNS_SERVERS])
        print(f"ips: {ip_result_set}")
        return ip_result_set

    def _get_best_ip(self):
        ip_result_set = self._get_ip_set()
        queue = Queue()
        tasks = [spawn(self._get_response_from_ip, ip, queue) for ip in ip_result_set]
        with Timeout(20):
            best_ip = queue.get()
        gevent.killall(tasks)
        return best_ip

    def get_total_size(self):
        print('get_total_size')
        def get_total_size_once(queue):
            for _ in range(15):
                try:
                    # with Timeout(30):
                    # res = requests.get(f"{self.schema}{self.get_ip()}{self.path}", stream=True, verify=False, headers=self.headers, timeout=(10, 30), proxies={"http": f"http://127.0.0.1:8888", "https": f"https://127.0.0.1:8888"})
                    res = requests.get(f"{self.schema}{self.get_ip()}{self.path}", stream=True, verify=False, headers=self.headers, timeout=(30, 30))
                    if int(res.status_code / 100) == 2:
                        break
                    else:
                        print(f'\n\nreturn code: {res.status_code}, body: {res.text}\n\n')
                except (GreenletExit, ssl.SSLEOFError, requests.exceptions.SSLError, requests.exceptions.ProxyError, requests.exceptions.ConnectionError):
                    print(traceback.format_exc())
                    pass
                except:
                    print(traceback.format_exc())
            else:
                queue.put(f'Failed to get total size of {self.url} after 10 times')
                return
            if 'Content-Length' in res.headers:
                queue.put(int(res.headers['Content-Length']))
            else:
                queue.put(f'Not support multi thread: {self.url}')


        queue = Queue()
        # get_total_size_once(queue)
        tasks = [spawn(get_total_size_once, queue) for _ in range(10)]
        res = queue.get()
        gevent.killall(tasks)
        if type(res) is int:
            print('finish get_total_size')
            return res
        else:
            raise RuntimeError(res)

    def get_segments_without_duplicate(self, segments):
        segments_without_duplicates = []
        for [start, end] in sorted(segments, key=lambda x: x[0]):
            if start is not None and end > start:
                if len(segments_without_duplicates) > 0:
                    s, e = segments_without_duplicates[-1]
                    if start <= e and end >= s:
                        segments_without_duplicates[-1] = [min(start, s), max(end, e)]
                        continue
                segments_without_duplicates.append([start, end])
        return segments_without_duplicates

    def get_download_info(self):
        if os.path.exists(self.file_name_with_path) and os.path.exists(self.breakpoint_file_path):
            with open(self.breakpoint_file_path, 'rb') as f:
                info_map = pickle.load(f)
            self.file_seeker = open(self.file_name_with_path, "r+b")
            thread_number = info_map['thread_number']
            self.total_size = info_map['total_size']
            self.url = info_map['url']
            written_segments = sorted(info_map['written_segments'], key=lambda x: x[0])
            self.written_segments = written_segments
            remaining_segments = []
            if len(written_segments) == 0:
                remaining_segments.append([0, self.total_size])
            for index, seg in enumerate(written_segments):
                if index == 0:
                    if seg[0] > 0:
                        remaining_segments.append([0, seg[1]])
                if index == len(written_segments) - 1:
                    if seg[1] < self.total_size:
                        remaining_segments.append([seg[1], self.total_size])
                if index > 0:
                    remaining_segments.append([written_segments[index - 1][1], seg[0]])

            if self.thread_number is None:
                self.thread_number = thread_number
            self.remaining_segments = remaining_segments
            if len(remaining_segments) < self.thread_number:
                for index in range(len(remaining_segments), self.thread_number):
                    self.to_dispatcher_queue.put({'type': 'finish_download', 'index': index, 'start': None, 'data': None, 'end': None})
                for _ in range(self.thread_number - len(remaining_segments)):
                    self.remaining_segments.append([None, None])
        else:
            if self.total_size is None:
                self.total_size = self.get_total_size()
            info_map = {
                'url': self.url,
                'thread_number': self.thread_number,
                'total_size': self.total_size
            }
            if self.thread_number is None:
                self.thread_number = self.DEFAULT_THREAD_NUMBER
            subprocess.Popen(f'mkdir -p {self.path_to_store}', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.file_seeker = open(self.file_name_with_path, "w+b")
            if math.floor(self.total_size / self.CHUNK_SIZE) < self.thread_number:
                self.thread_number = math.floor(self.total_size / self.CHUNK_SIZE)
            divided_segment_size = math.floor(self.total_size / self.thread_number / self.CHUNK_SIZE) * self.CHUNK_SIZE
            for i in range(self.thread_number - 1):
                self.remaining_segments.append([divided_segment_size * i, divided_segment_size * (i + 1)])
            self.remaining_segments.append([divided_segment_size * (self.thread_number - 1), self.total_size])

        self.thread_buffer_size = math.ceil(self.TOTAL_BUFFER_SIZE / self.thread_number / self.CHUNK_SIZE) * self.CHUNK_SIZE
        self.bytearray_of_threads = [None] * self.thread_number
        self.workers = [None] * self.thread_number
        return info_map

    def balance_remaining_segments(self, completed_index):
        if self.all_done:
            return False
        if len(self.remaining_segments) > self.thread_number:
            self.remaining_segments_lock.acquire()
            new_start, new_end = self.remaining_segments[-1]
            self.remaining_segments[completed_index] = [new_start, new_end]
            del self.remaining_segments[-1]
            self.remaining_segments_lock.release()
            return True

        copied_remaining_segments_with_index = []

        self.remaining_segments_lock.acquire()
        for index, seg in enumerate(self.remaining_segments):
            if seg[0] is not None and seg[1] > seg[0]:
                copied_remaining_segments_with_index.append((index, [seg[0], seg[1]]))
        self.remaining_segments_lock.release()

        sorted_copied_remaining_segments = sorted(copied_remaining_segments_with_index, key=lambda x: x[1][1] - x[1][0], reverse=True)

        if len(sorted_copied_remaining_segments) > 0:

            max_remaining_index, max_remaining_task = sorted_copied_remaining_segments[0]
            end_to_max_start_map = dict()
            for index, seg in sorted_copied_remaining_segments:
                if seg[1] not in end_to_max_start_map or end_to_max_start_map[seg[1]][1] < seg[0]:
                    end_to_max_start_map[seg[1]] = (index, seg[0])
            remaining_bytes = max_remaining_task[1] - max_remaining_task[0]
            if remaining_bytes >= self.MIN_TASK_CHUNK_SIZE:

                new_end_of_max_remaining_task = max_remaining_task[1] - math.floor(remaining_bytes * 0.5 / self.CHUNK_SIZE) * self.CHUNK_SIZE
                new_start = new_end_of_max_remaining_task
                new_end = max_remaining_task[1]
                self.remaining_segments_lock.acquire()
                self.remaining_segments[max_remaining_index][1] = new_end_of_max_remaining_task
                self.remaining_segments[completed_index] = [new_start, new_end]
                self.remaining_segments_lock.release()
            else:

                self.almost_done = True

                end_with_min_coworkers = sorted([(end, len(self.coworker_end_to_indexes_map[end]) if end in self.coworker_end_to_indexes_map else 0) for end in end_to_max_start_map], key=lambda x: x[1])[0][0]
                index, new_start = end_to_max_start_map[end_with_min_coworkers]
                new_end = end_with_min_coworkers

                self.remaining_segments_lock.acquire()
                self.remaining_segments[completed_index][0] = new_start
                self.remaining_segments[completed_index][1] = new_end
                self.remaining_segments_lock.release()

                if new_end not in self.coworker_end_to_indexes_map:
                    self.coworker_end_to_indexes_map[new_end] = {index, completed_index}
                else:
                    self.coworker_end_to_indexes_map[new_end].add(completed_index)
            return True
        else:
            self.all_done = True
            return False

    def calculate_progress_once(self):
        self.remaining_segments_lock.acquire()
        tmp = [[seg[0], seg[1]] for seg in self.remaining_segments if seg[1] is not None]
        self.remaining_segments_lock.release()
        new_tmp = self.get_segments_without_duplicate(tmp)

        remaining_size = sum([end - start for [start, end] in new_tmp])
        downloaded_size = self.total_size - remaining_size

        current_time = datetime.datetime.now()
        seconds = (current_time - self.start_time).seconds

        if self.last_progress_time is None:
            self.last_progress_time = seconds + 0.001
            self.last_downloaded_size = downloaded_size
        assert downloaded_size >= self.last_downloaded_size, f"{downloaded_size}, {self.last_downloaded_size}"
        downloaded_size_in_period = downloaded_size - self.last_downloaded_size
        self.last_downloaded_size = downloaded_size
        finish_percent = math.floor(downloaded_size / self.total_size * 10000) / 10000

        return {
            'total_size': self.total_size,
            'downloaded_size': downloaded_size,
            'downloaded_size_in_period': downloaded_size_in_period,
            'finish_percent': finish_percent,
            'realtime_speed': downloaded_size_in_period / (seconds - self.last_progress_time),
            'total_seconds': seconds
        }

    def show_progress_once(self):
        if not self.print_progress:
            return
        progress = self.calculate_progress_once()
        finish_percent = progress['finish_percent']
        done = math.floor(50 * finish_percent)

        sys.stdout.write("\r[%s%s] %.2f%% %.2fMB|%.2fMB %.3fMB/s %ds" % ('█' * done, ' ' * (50 - done), 100 * finish_percent, math.floor(progress['downloaded_size'] / 1024 / 10.24) / 100, math.floor(self.total_size / 1024 / 10.24) / 100, math.floor(progress['downloaded_size_in_period'] / 1024 / 1.024) / 1000, progress['total_seconds']))
        sys.stdout.flush()

        return finish_percent == 1

    def show_progress(self):
        if not self.print_progress:
            return
        while True:
            sleep(1)
            if self.show_progress_once():
                break

    def refresh_written_segments(self, start, end):
        self.written_segments = self.get_segments_without_duplicate(self.written_segments + [[start, end]])
        written_size = sum([end - start for [start, end] in self.written_segments])
        if written_size == self.total_size:
            self.remove_breakpoint_file()
            self.segment_dispatch_task.kill()
            return True
        return False

    def is_segment_new(self, start, end):
        for written_start, written_end in self.written_segments:
            if start < written_end and end > written_start:
                return start < written_start or end > written_end
        else:
            return True

    def store_segment(self, start, data):
        assert start is not None and start >= 0
        data_length = self.total_size-start if start + len(data) > self.total_size else len(data)
        end = start + data_length
        if data_length > 0 and self.is_segment_new(start, end):
            data = data[:data_length]
            self.file_seeker.seek(start)
            self.file_seeker.write(data)
            return self.refresh_written_segments(start, end)
        return False

    def store_segment_task(self):
        while True:
            start, data = self.to_store_queue.get()
            if self.store_segment(start, data):
                break

    def store_remaining_segment(self):
        for index, segment in enumerate(self.bytearray_of_threads):
            if segment is not None:
                start, data, data_length = segment[0], segment[1], segment[2]
                self.to_store_queue.put((start, data[:data_length]))

    def start_download_task(self, task_index):
        try:
            self.remaining_segments_lock.acquire()
            start = self.remaining_segments[task_index][0]
            end = self.remaining_segments[task_index][1]
        except GreenletExit:
            self.remaining_segments_lock.release()
            return
        self.remaining_segments_lock.release()

        assert start is not None or start < end, f"{task_index}: {start} ~ {end}"

        data = bytearray(self.thread_buffer_size)
        data_length = 0

        self.bytearray_of_threads[task_index] = [start, data, data_length]
        while True:
            try:
                with Timeout(60):
                    headers = {**self.headers, 'Range': 'bytes=%d-%d' % (start + data_length, end - 1)}
                    r = requests.get(f"{self.schema}{self.get_ip()}{self.path}", stream=True, verify=False, headers=headers)
                if r.status_code == 206:
                    chunk_size = min(self.CHUNK_SIZE, end - start - data_length)
                    chunks = r.iter_content(chunk_size=chunk_size)

                    while True:
                        with Timeout(60):
                            chunk = chunks.__next__()
                        get_chunk_size = len(chunk)
                        if get_chunk_size == self.CHUNK_SIZE or get_chunk_size == chunk_size:
                            data_length += get_chunk_size
                            try:
                                self.remaining_segments_lock.acquire()
                                end = self.remaining_segments[task_index][1]
                                self.remaining_segments[task_index][0] = start + data_length
                            except GreenletExit:
                                self.remaining_segments_lock.release()
                                return
                            self.remaining_segments_lock.release()

                            data[data_length - get_chunk_size:data_length] = chunk
                            self.bytearray_of_threads[task_index][2] = data_length

                            if end - 1 <= start + data_length or data_length + self.CHUNK_SIZE > self.thread_buffer_size:
                                if end - 1 <= start + data_length:
                                    self.to_dispatcher_queue.put({'type': 'finish_download', 'index': task_index, 'start': start, 'data': data[:data_length], 'end': end})
                                    try:
                                        self.remaining_segments_lock.acquire()
                                        self.remaining_segments[task_index] = [None, None]
                                    except GreenletExit:
                                        self.remaining_segments_lock.release()
                                        return
                                    self.remaining_segments_lock.release()

                                    self.bytearray_of_threads[task_index] = None
                                    self.workers[task_index] = None
                                    return
                                else:
                                    self.to_dispatcher_queue.put({'type': 'part_downloaded', 'start': start, 'data': data[:data_length]})
                                    start += data_length
                                    data = bytearray(self.thread_buffer_size)
                                    data_length = 0
                                    self.bytearray_of_threads[task_index] = [start, data, data_length]
                        else:
                            break
            except (timeout.Timeout, requests.exceptions.ProxyError, requests.exceptions.ConnectionError, StopIteration, KeyboardInterrupt, ConnectionResetError):
                # except Exception:
                pass

    def store_breakpoint(self):
        downloaded_size = self.calculate_progress_once()['downloaded_size']
        self.store_remaining_segment()
        max_wait = 0
        while True:
            written_size = sum([end - start for [start, end] in self.written_segments])
            if downloaded_size == written_size:
                break
            sleep(0.1)
            max_wait += 1
            if max_wait >= 100:
                break
        self.segment_dispatch_task.kill()
        self.segment_store_task.kill()
        if downloaded_size < self.total_size:
            with open(self.breakpoint_file_path, 'wb') as f:
                self.download_info['thread_number'] = self.thread_number
                self.download_info['written_segments'] = self.written_segments
                pickle.dump(self.download_info, f)
        self.show_progress_once()

    def remove_breakpoint_file(self):
        if os.path.exists(self.breakpoint_file_path):
            os.remove(self.breakpoint_file_path)

    def dispatch_segment(self):
        while True:
            request = self.to_dispatcher_queue.get()

            if request['type'] == 'part_downloaded':
                start, data = request['start'], request['data']
                self.to_store_queue.put((start, data))

            elif request['type'] == 'finish_download':
                completed_index, start, data, end = request['index'], request['start'], request['data'], request['end']
                if start is not None:
                    if end in self.coworker_end_to_indexes_map:
                        for index in self.coworker_end_to_indexes_map[end]:
                            if index == completed_index:
                                continue
                            self.to_dispatcher_queue.put({'type': 'finish_download', 'index': index, 'start': None, 'data': None, 'end': None})
                            if self.workers[index] is not None:
                                self.workers[index].kill()
                                self.workers[index] = None
                            self.remaining_segments_lock.acquire()
                            self.remaining_segments[index][0] = None
                            self.remaining_segments[index][1] = None
                            self.remaining_segments_lock.release()
                            if self.bytearray_of_threads[index] is not None:
                                [buffer_start, buffer_data, _] = self.bytearray_of_threads[index]
                                if start > buffer_start:
                                    self.to_store_queue.put((buffer_start, buffer_data[:start - buffer_start]))

                        del self.coworker_end_to_indexes_map[end]
                    self.to_store_queue.put((start, data))
                if self.workers[completed_index] is None and self.balance_remaining_segments(completed_index):
                    self.workers[completed_index] = spawn(self.start_download_task, completed_index)

    def stop(self):
        self.progress_show_task.kill()
        for index in range(self.thread_number):
            if self.workers[index] is not None:
                self.workers[index].kill()
                self.workers[index] = None
        self.store_breakpoint()

    def download(self):

        self.start_time = datetime.datetime.now()
        if self.show_progress_once():
            self.file_seeker.flush()
            self.file_seeker.close()
            return
        self.progress_show_task = spawn(self.show_progress)
        self.segment_dispatch_task = spawn(self.dispatch_segment)

        for index in range(self.thread_number):
            if self.workers[index] is None and self.remaining_segments[index][0] is not None:
                self.workers[index] = spawn(self.start_download_task, index)
        self.segment_store_task = spawn(self.store_segment_task)

        # if self.print_progress:
        #     signal_handler(SIGINT, self.stop)

        self.progress_show_task.join()
        self.segment_dispatch_task.join()
        self.segment_store_task.join()
        self.file_seeker.flush()
        self.file_seeker.close()
        if self.print_progress:
            sys.stdout.write('\n')
        # os.kill(os.getpid(),SIGTERM)
        # sys.exit()

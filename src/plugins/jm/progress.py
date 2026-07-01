import threading

from jmcomic import JmDownloader


class ProgressJmDownloader(JmDownloader):
    def __init__(self, option, cancel_event=None):
        super().__init__(option)
        self._cancel_event = cancel_event or threading.Event()

    def before_photo(self, photo):
        if self._cancel_event.is_set():
            photo.skip = True
            super().before_photo(photo)
            return
        super().before_photo(photo)

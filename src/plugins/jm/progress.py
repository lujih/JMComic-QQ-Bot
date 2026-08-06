import threading

from jmcomic import JmAsyncDownloader


class ProgressJmDownloader(JmAsyncDownloader):
    def __init__(self, option, cancel_event=None):
        super().__init__(option)
        self._cancel_event = cancel_event or threading.Event()

    async def before_photo(self, photo):
        if self._cancel_event.is_set():
            photo.skip = True
        await super().before_photo(photo)

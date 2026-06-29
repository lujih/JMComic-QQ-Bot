import threading

from jmcomic import JmDownloader


class ProgressJmDownloader(JmDownloader):
    def __init__(self, option, progress_cb, fmt_name='PDF', cancel_event=None):
        super().__init__(option)
        self._cb = progress_cb
        self._fmt_name = fmt_name
        self._cancel_event = cancel_event or threading.Event()

    def before_photo(self, photo):
        if self._cancel_event.is_set():
            # NOTE: `photo.skip` 是 jmcomic 内部属性（非公共 API），
            # jmcomic>=2.7.0 中 stable，升 3.x 大版本时需验证
            photo.skip = True
            super().before_photo(photo)
            return
        super().before_photo(photo)

    def after_album(self, album):
        if self._cancel_event.is_set():
            return
        self._cb(f"📄 正在生成 {self._fmt_name}……")
        super().after_album(album)

from jmcomic import JmDownloader
from plugins.jm.common import _cancel_event


class ProgressJmDownloader(JmDownloader):
    def __init__(self, option, progress_cb, fmt_name='PDF'):
        super().__init__(option)
        self._cb = progress_cb
        self._fmt_name = fmt_name

    def after_album(self, album):
        if _cancel_event.is_set():
            return
        self._cb(f"📄 正在生成 {self._fmt_name}……")
        super().after_album(album)

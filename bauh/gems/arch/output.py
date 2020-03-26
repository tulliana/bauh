from bauh.api.abstract.handler import ProcessWatcher
from bauh.view.util.translation import I18n


class TransactionStatusHandler:

    def __init__(self, watcher: ProcessWatcher, i18n: I18n, npackages: int):
        self.watcher = watcher
        self.i18n = i18n
        self.npackages = npackages
        self.downloading = 0
        self.upgrading = 0
        self.installing = 0

    def handle(self, output: str):
        if output:
            if output.startswith('downloading'):
                self.downloading += 1
                self.watcher.change_substatus('[{}/{}] {} {}'.format(self.downloading, self.npackages,
                                                                     self.i18n['downloading'].capitalize(), output.split(' ')[1].strip()))
            elif output.startswith('upgrading'):
                self.upgrading += 1
                self.watcher.change_substatus('[{}/{}] {} {}'.format(self.upgrading, self.npackages,
                                                                     self.i18n['manage_window.status.upgrading'].capitalize(), output.split(' ')[1].strip()))
            elif output.startswith('installing'):
                self.installing += 1
                self.watcher.change_substatus('[{}/{}] {} {}'.format(self.installing, self.npackages,
                                                                     self.i18n['manage_window.status.installing'].capitalize(),
                                                                     output.split(' ')[1].strip()))

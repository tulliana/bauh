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

    def gen_percentage(self) -> str:
        performed = self.downloading + self.upgrading + self.installing
        return '({}%)'.format(int((performed / (2 * self.npackages)) * 100))

    def handle(self, output: str):
        if output:
            if output.startswith('downloading'):
                perc = self.gen_percentage()
                self.downloading += 1
                self.watcher.change_substatus('{} [{}/{}] {} {}'.format(perc, self.downloading, self.npackages,
                                                                        self.i18n['downloading'].capitalize(), output.split(' ')[1].strip()))
            elif output.startswith('upgrading'):
                perc = self.gen_percentage()
                self.upgrading += 1
                self.watcher.change_substatus('{} [{}/{}] {} {}'.format(perc, self.upgrading, self.npackages,
                                                                        self.i18n['manage_window.status.upgrading'].capitalize(), output.split(' ')[1].strip()))
            elif output.startswith('installing'):
                perc = self.gen_percentage()
                self.installing += 1
                self.watcher.change_substatus('{} [{}/{}] {} {}'.format(perc, self.installing, self.npackages,
                                                                        self.i18n['manage_window.status.installing'].capitalize(),
                                                                        output.split(' ')[1].strip()))

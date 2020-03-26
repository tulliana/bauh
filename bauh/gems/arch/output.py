import logging
from threading import Thread
from typing import Iterable

from bauh.api.abstract.handler import ProcessWatcher
from bauh.view.util.translation import I18n


class TransactionStatusHandler(Thread):

    def __init__(self, watcher: ProcessWatcher, i18n: I18n, pkgs: Iterable[str], logger: logging.Logger):
        super(TransactionStatusHandler, self).__init__(daemon=True)
        self.watcher = watcher
        self.i18n = i18n
        self.pkgs = pkgs
        self.npkgs = len(pkgs)
        self.downloading = 0
        self.upgrading = 0
        self.installing = 0
        self.outputs = []
        self.work = True
        self.logger = logger

    def gen_percentage(self) -> str:
        performed = self.downloading + self.upgrading + self.installing
        return '({0:.2f}%)'.format((performed / (2 * self.npkgs)) * 100)

    def _can_notify(self, output: str):
        return output.split(' ')[1].split('.')[0] in self.pkgs

    def _handle(self, output: str) -> bool:
        if output:
            if output.startswith('downloading') and self._can_notify(output):
                perc = self.gen_percentage()
                self.downloading += 1

                if self.downloading <= self.npkgs:
                    self.watcher.change_substatus('{} [{}/{}] {} {}'.format(perc, self.downloading, self.npkgs,
                                                                            self.i18n['downloading'].capitalize(), output.split(' ')[1].strip()))
            elif output.startswith('upgrading') and self._can_notify(output):
                perc = self.gen_percentage()
                self.upgrading += 1

                performed = self.upgrading + self.installing

                if performed <= self.npkgs:
                    self.watcher.change_substatus('{} [{}/{}] {} {}'.format(perc, self.upgrading, self.npkgs,
                                                                            self.i18n['manage_window.status.upgrading'].capitalize(), output.split(' ')[1].strip()))
            elif output.startswith('installing') and self._can_notify(output):
                perc = self.gen_percentage()
                self.installing += 1

                performed = self.upgrading + self.installing

                if performed <= self.npkgs:
                    self.watcher.change_substatus('{} [{}/{}] {} {}'.format(perc, self.installing, self.npkgs,
                                                                            self.i18n['manage_window.status.installing'].capitalize(),
                                                                            output.split(' ')[1].strip()))
            else:
                performed = self.upgrading + self.installing
                if performed == self.npkgs:
                    self.watcher.change_substatus("")
                    return False

        return True

    def handle(self, output: str):
        self.outputs.append(output)

    def stop_working(self):
        self.work = False

    def run(self):
        self.logger.info("Starting")
        while self.work:
            if self.outputs:
                output = self.outputs.pop()
                if not self._handle(output):
                    break

        self.logger.info("Finished")
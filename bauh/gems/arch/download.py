import glob
import logging
import os
import time
import traceback
from threading import Thread
from typing import List, Iterable, Dict, Tuple

from bauh.api.abstract.download import FileDownloader
from bauh.api.abstract.handler import ProcessWatcher
from bauh.api.abstract.view import MessageType
from bauh.api.http import HttpClient
from bauh.commons.html import bold
from bauh.commons.system import ProcessHandler, SimpleProcess
from bauh.gems.arch import pacman
from bauh.view.util.translation import I18n


class ArchDownloadException(Exception):
    pass


class CacheDirCreationException(ArchDownloadException):
    pass


class MultiThreadedDownloader:

    def __init__(self, file_downloader: FileDownloader, http_client: HttpClient, mirrors_available: Iterable[str],
                 mirrors_branch: str, cache_dir: str, logger: logging.Logger):
        self.downloader = file_downloader
        self.http_client = http_client
        self.mirrors = mirrors_available
        self.branch = mirrors_branch
        self.extensions = ['.tar.zst', '.tar.xz']
        self.cache_dir = cache_dir
        self.logger = logger

    def is_file_already_downloaded(self, filename: str, watcher: ProcessWatcher = None) -> bool:
        if {f for f in glob.glob(self.cache_dir + '/*') if f.split('/')[-1].startswith(filename)}:
            if watcher:
                watcher.print("File {} found o cache dir. Skipping download.".format(filename, self.cache_dir))
            return True

        return False

    def get_available_package_url(self, pkg: Dict[str, str]) -> Tuple[str, str, str]:
        arch = pkg['a'] if pkg.get('a') and pkg['a'] != 'any' else 'x86_64'

        url_base = '{}/{}/{}/{}'.format(self.branch, pkg['r'], arch, pkg['f'])
        for mirror in self.mirrors:
            for ext in self.extensions:
                url = '{}{}{}'.format(mirror, url_base, ext)

                if self.http_client.exists(url=url, session=True, timeout=3):
                    return url, mirror, self.get_base_output_path(pkg['f']) + ext

    def download_package(self, pkg: Dict[str, str], url: str, mirror: str, output_path: str, watcher: ProcessWatcher,
                         root_password: str, substatus_prefix: str = None) -> bool:
        watcher.print("Downloading '{}' from mirror '{}'".format(pkg['f'], mirror))
        pkg_downloaded = self.downloader.download(file_url=url, watcher=watcher, output_path=output_path,
                                                  cwd='.', root_password=root_password, display_file_size=True,
                                                  substatus_prefix=substatus_prefix)
        if not pkg_downloaded:
            watcher.print("Could not download '{}' from mirror '{}'".format(pkg['f'], mirror))
            return False
        else:
            self.logger.info("Package '{}' successfully downloaded".format(pkg['n']))
            self.logger.info("Downloading package '{}' signature".format(pkg['n']))

            sig_downloaded = self.downloader.download(file_url=url + '.sig', watcher=watcher,
                                                      output_path=output_path + '.sig',
                                                      cwd='.', root_password=root_password,
                                                      display_file_size=False,
                                                      substatus_prefix=substatus_prefix)

            if not sig_downloaded:
                self.logger.warning("Could not download package '{}' signature".format(pkg['n']))
            else:
                self.logger.info("Package '{}' signature successfully downloaded".format(pkg['n']))

        return True

    def get_base_output_path(self, filename: str) -> str:
        return '{}/{}'.format(self.cache_dir, filename)

    def check_and_download_package(self, pkg: Dict[str, str], root_password: str, substatus_prefix: str, watcher: ProcessWatcher) -> bool:
        if self.mirrors and self.branch:
            if self.is_file_already_downloaded(pkg['f'], watcher):
                return True

            arch = pkg['a'] if pkg.get('a') and pkg['a'] != 'any' else 'x86_64'

            url_base = '{}/{}/{}/{}'.format(self.branch, pkg['r'], arch, pkg['f'])
            base_output_path = self.get_base_output_path(pkg['f'])
            for mirror in self.mirrors:
                for ext in self.extensions:
                    url = '{}{}{}'.format(mirror, url_base, ext)
                    output_path = base_output_path + ext

                    if self.download_package(pkg=pkg, url=url, output_path=output_path, root_password=root_password,
                                             watcher=watcher, substatus_prefix=substatus_prefix, mirror=mirror):
                        return True
        return False


class PackageUrlChecker(Thread):

    def __init__(self, pkgs: List[Dict[str, str]], downloader: MultiThreadedDownloader):
        super(PackageUrlChecker, self).__init__(daemon=True)
        self.downloader = downloader
        self.pkgs = pkgs
        self.checked = []
        self._finished = False
        self.next_idx = 0

    def run(self):
        for p in self.pkgs:
            url_data = self.downloader.get_available_package_url(p)

            if url_data:
                p['url'] = url_data[0]
                p['mirror'] = url_data[1]
                p['output_path'] = url_data[2]

            self.checked.append(p)

        self._finished = True

    def get_package(self) -> Dict[str, str]:
        if self.checked and len(self.checked) > self.next_idx:
            to_return = self.checked[self.next_idx]
            self.next_idx += 1
            return to_return

    def get_packages_number(self) -> int:
        return len(self.pkgs)

    def has_finished(self):
        return self._finished and self.next_idx >= len(self.checked)


class PackageDownloader(Thread):

    def __init__(self, already_downloaded: int, downloader: MultiThreadedDownloader, url_checker: PackageUrlChecker, logger: logging.Logger,
                 watcher: ProcessWatcher, root_password: str):
        super(PackageDownloader, self).__init__(daemon=True)
        self.downloader = downloader
        self.url_checker = url_checker
        self.logger = logger
        self.watcher = watcher
        self.download_errors = False
        self.downloaded = already_downloaded
        self.already_downloaded = already_downloaded
        self.root_password = root_password

    @staticmethod
    def get_status_prefix(downloaded: int, npkgs: int) -> str:
        perc = '({0:.2f}%)'.format((downloaded / (2 * npkgs)) * 100)
        return '{} [{}/{}]'.format(perc, downloaded + 1, npkgs)

    @classmethod
    def download(cls, pkg: Dict[str, str], root_password: str, already_downloaded: int, npkgs: int, downloader: MultiThreadedDownloader, watcher: ProcessWatcher, only_download: bool) -> Tuple[bool, bool]:
        status_prefix = cls.get_status_prefix(already_downloaded, npkgs)
        try:
            if only_download:
                downloaded = downloader.download_package(pkg=pkg, url=pkg['url'], mirror=pkg['mirror'], output_path=pkg['output_path'],
                                                         root_password=root_password, watcher=watcher, substatus_prefix=status_prefix)
            else:
                downloaded = downloader.check_and_download_package(pkg=pkg, root_password=root_password, watcher=watcher, substatus_prefix=status_prefix)

            return downloaded, False
        except:
            traceback.print_exc()
            return False, True

    def run(self):
        self.logger.info("Starting")
        npkgs = self.url_checker.get_packages_number() + self.already_downloaded
        while not self.url_checker.has_finished():
            pkg = self.url_checker.get_package()

            if pkg:
                self.logger.info('Preparing to download package: {} ({})'.format(pkg['n'], pkg['v']))
                success, err = self.download(pkg, self.root_password, self.downloaded, npkgs, self.downloader, self.watcher, only_download=True)

                if success:
                    self.downloaded += 1
                elif err:
                    self.download_errors = True
                    break
            else:
                time.sleep(0.001)

        self.logger.info("Finished")


class MultithreadedDownloadService:

    def __init__(self, file_downloader: FileDownloader, http_client: HttpClient, logger: logging.Logger, i18n: I18n):
        self.file_downloader = file_downloader
        self.http_client = http_client
        self.logger = logger
        self.i18n = i18n

    def list_not_cached_packages(self, pkgs: List[Dict[str, str]], downloader: MultiThreadedDownloader) -> List[Dict[str, str]]:
        not_cached = []

        for p in pkgs:
            if not downloader.is_file_already_downloaded(p['f']):
                not_cached.append(p)

        return not_cached

    def _raise_download_error(self, watcher: ProcessWatcher):
        watcher.show_message(title=self.i18n['error'].capitalize(),
                             body=self.i18n['arch.mthread_downloaded.error.cancelled'],
                             type_=MessageType.ERROR)
        raise ArchDownloadException()

    def download_packages(self, pkgs: List[str], handler: ProcessHandler, root_password: str) -> int:
        ti = time.time()
        watcher = handler.watcher
        mirrors = pacman.list_available_mirrors()

        if not mirrors:
            self.logger.warning('repository mirrors seem to be not reachable')
            watcher.print('[warning] repository mirrors seem to be not reachable')
            watcher.print('[warning] multi-threaded download cancelled')
            return 0

        branch = pacman.get_mirrors_branch()

        if not branch:
            self.logger.warning('no default repository branch found')
            watcher.print('[warning] no default repository branch found')
            watcher.print('[warning] multi-threaded download cancelled')
            return 0

        cache_dir = pacman.get_cache_dir()

        if not os.path.exists(cache_dir):
            success, _ = handler.handle_simple(SimpleProcess(['mkdir', '-p', cache_dir], root_password=root_password))

            if not success:
                msg = "could not create cache dir '{}'".format(cache_dir)
                self.logger.warning(msg)
                watcher.print("[warning] {}".format(cache_dir))
                watcher.show_message(title=self.i18n['warning'].capitalize(),
                                     body=self.i18n['arch.mthread_downloaded.error.cache_dir'].format(bold(cache_dir)),
                                     type_=MessageType.WARNING)
                raise CacheDirCreationException()

        downloader = MultiThreadedDownloader(file_downloader=self.file_downloader,
                                             mirrors_available=mirrors,
                                             mirrors_branch=branch,
                                             http_client=self.http_client,
                                             logger=self.logger,
                                             cache_dir=cache_dir)

        pkgs_data = pacman.list_download_data(pkgs)
        downloaded = 0

        if len(pkgs_data) == 1:
            pkg = pkgs_data[0]
            self.logger.info('Preparing to download package: {} ({})'.format(pkg['n'], pkg['v']))

            success, err = PackageDownloader.download(pkg, root_password, downloaded, 1, downloader, watcher, only_download=False)

            if success:
                downloaded += 1
            elif err:
                self._raise_download_error(watcher)
        else:
            watcher.print("Checking cached files")
            self.logger.info("Checking cached files")
            not_downloaded = self.list_not_cached_packages(pkgs_data, downloader)
            downloaded = len(pkgs_data) - len(not_downloaded)

            if downloaded < len(pkgs_data):
                thread_checker = PackageUrlChecker(not_downloaded, downloader)
                thread_checker.start()

                thread_downloader = PackageDownloader(downloader=downloader, url_checker=thread_checker, root_password=root_password,
                                                      logger=self.logger, watcher=watcher, already_downloaded=downloaded)
                thread_downloader.start()
                thread_downloader.join()

                downloaded += thread_downloader.downloaded

                if thread_downloader.download_errors:
                    self._raise_download_error(watcher)

        tf = time.time()
        self.logger.info("Download took {0:.2f} seconds".format(tf - ti))
        return downloaded

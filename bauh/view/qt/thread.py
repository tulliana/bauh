import time
from datetime import datetime, timedelta
from typing import List

import requests
from PyQt5.QtCore import QThread, pyqtSignal
from bauh_api.abstract.controller import ApplicationManager
from bauh_api.abstract.handler import ProcessWatcher
from bauh_api.abstract.model import ApplicationStatus
from bauh_api.abstract.view import InputViewComponent, MessageType
from bauh_api.exception import NoInternetException
from bauh_api.util.cache import Cache

from bauh.view.qt.view_model import ApplicationView


class AsyncAction(QThread, ProcessWatcher):

    signal_output = pyqtSignal(str)  # print messages to the terminal widget
    signal_confirmation = pyqtSignal(dict)  # asks the users to confirm something
    signal_finished = pyqtSignal(object)  # informs the main window that the action has finished
    signal_message = pyqtSignal(dict)  # asks the GUI to show an error popup
    signal_status = pyqtSignal(str)  # changes the GUI status message
    signal_substatus = pyqtSignal(str)  # changes the GUI substatus message

    def __init__(self):
        super(AsyncAction, self).__init__()
        self.wait_confirmation = False
        self.confirmation_res = None

    def request_confirmation(self, title: str, body: str, components: List[InputViewComponent] = None, confirmation_label: str = None, deny_label: str = None) -> bool:
        self.wait_confirmation = True
        self.signal_confirmation.emit({'title': title, 'body': body, 'components': components, 'confirmation_label': confirmation_label, 'deny_label': deny_label})
        self.wait_user()
        return self.confirmation_res

    def confirm(self, res: bool):
        self.confirmation_res = res
        self.wait_confirmation = False

    def wait_user(self):
        while self.wait_confirmation:
            time.sleep(0.01)

    def print(self, msg: str):
        if msg:
            self.signal_output.emit(msg)

    def show_message(self, title: str, body: str, type_: MessageType = MessageType.INFO):
        self.signal_message.emit({'title': title, 'body': body, 'type': type_})

    def notify_finished(self, res: object):
        self.signal_finished.emit(res)

    def change_status(self, status: str):
        self.signal_status.emit(status)

    def change_substatus(self, substatus: str):
        self.signal_substatus.emit(substatus)


class UpdateSelectedApps(AsyncAction):

    def __init__(self, manager: ApplicationManager, locale_keys: dict, apps_to_update: List[ApplicationView] = None):
        super(UpdateSelectedApps, self).__init__()
        self.apps_to_update = apps_to_update
        self.manager = manager
        self.root_password = None
        self.locale_keys = locale_keys

    def run(self):

        success = False

        if self.apps_to_update:
            updated = 0
            for app in self.apps_to_update:
                self.change_status('{} {}...'.format(self.locale_keys['manage_window.status.upgrading'], app.model.base_data.name))
                success = bool(self.manager.update(app.model, self.root_password, self))

                if not success:
                    break
                else:
                    updated += 1
                    self.signal_output.emit('\n')

            self.notify_finished({'success': success, 'updated': updated})

        self.apps_to_update = None


class RefreshApps(AsyncAction):

    def __init__(self, manager: ApplicationManager):
        super(RefreshApps, self).__init__()
        self.manager = manager

    def run(self):
        self.notify_finished(self.manager.read_installed())


class UninstallApp(AsyncAction):

    def __init__(self, manager: ApplicationManager, icon_cache: Cache, app: ApplicationView = None):
        super(UninstallApp, self).__init__()
        self.app = app
        self.manager = manager
        self.icon_cache = icon_cache
        self.root_password = None

    def run(self):
        if self.app:
            success = self.manager.uninstall(self.app.model, self.root_password, self)

            if success:
                self.icon_cache.delete(self.app.model.base_data.icon_url)
                self.manager.clean_cache_for(self.app.model)

            self.notify_finished(self.app if success else None)
            self.app = None
            self.root_password = None


class DowngradeApp(AsyncAction):

    def __init__(self, manager: ApplicationManager, locale_keys: dict, app: ApplicationView = None):
        super(DowngradeApp, self).__init__()
        self.manager = manager
        self.app = app
        self.locale_keys = locale_keys
        self.root_password = None

    def run(self):
        if self.app:
            success = False
            try:
                success = self.manager.downgrade_app(self.app.model, self.root_password, self)
            except (requests.exceptions.ConnectionError, NoInternetException):
                success = False
                self.print(self.locale_keys['internet.required'])
            finally:
                self.app = None
                self.root_password = None
                self.notify_finished(success)


class GetAppInfo(AsyncAction):

    def __init__(self, manager: ApplicationManager, app: ApplicationView = None):
        super(GetAppInfo, self).__init__()
        self.app = app
        self.manager = manager

    def run(self):
        if self.app:
            info = {'__app__': self.app}
            info.update(self.manager.get_info(self.app.model))
            self.notify_finished(info)
            self.app = None


class GetAppHistory(AsyncAction):

    def __init__(self, manager: ApplicationManager, locale_keys: dict, app: ApplicationView = None):
        super(GetAppHistory, self).__init__()
        self.app = app
        self.manager = manager
        self.locale_keys = locale_keys

    def run(self):
        if self.app:
            try:
                self.notify_finished({'history': self.manager.get_history(self.app.model)})
            except (requests.exceptions.ConnectionError, NoInternetException):
                self.notify_finished({'error': self.locale_keys['internet.required']})
            finally:
                self.app = None


class SearchApps(AsyncAction):

    def __init__(self, manager: ApplicationManager):
        super(SearchApps, self).__init__()
        self.word = None
        self.manager = manager

    def run(self):
        apps_found = []

        if self.word:
            res = self.manager.search(self.word)
            apps_found.extend(res['installed'])
            apps_found.extend(res['new'])
            self.notify_finished(apps_found)
            self.word = None


class InstallApp(AsyncAction):

    def __init__(self, manager: ApplicationManager, disk_cache: bool, icon_cache: Cache, locale_keys: dict, app: ApplicationView = None):
        super(InstallApp, self).__init__()
        self.app = app
        self.manager = manager
        self.icon_cache = icon_cache
        self.disk_cache = disk_cache
        self.locale_keys = locale_keys
        self.root_password = None

    def run(self):
        if self.app:
            success = False

            try:
                success = self.manager.install(self.app.model, self.root_password, self)

                if success and self.disk_cache:
                    self.app.model.installed = True

                    if self.app.model.supports_disk_cache():
                        icon_data = self.icon_cache.get(self.app.model.base_data.icon_url)
                        self.manager.cache_to_disk(app=self.app.model,
                                                   icon_bytes=icon_data.get('bytes') if icon_data else None,
                                                   only_icon=False)
            except (requests.exceptions.ConnectionError, NoInternetException):
                success = False
                self.print(self.locale_keys['internet.required'])
            finally:
                self.signal_finished.emit(self.app if success else None)
                self.app = None


class AnimateProgress(QThread):

    signal_change = pyqtSignal(int)

    def __init__(self):
        super(AnimateProgress, self).__init__()
        self.progress_value = 0
        self.increment = 5
        self.stop = False

    def run(self):

        current_increment = self.increment

        while not self.stop:
            self.signal_change.emit(self.progress_value)

            if self.progress_value == 100:
                current_increment = -current_increment
            if self.progress_value == 0:
                current_increment = self.increment

            self.progress_value += current_increment

            time.sleep(0.05)

        self.progress_value = 0


class VerifyModels(QThread):

    signal_updates = pyqtSignal()

    def __init__(self, apps: List[ApplicationView] = None):
        super(VerifyModels, self).__init__()
        self.apps = apps

    def run(self):

        if self.apps:

            stop_at = datetime.utcnow() + timedelta(seconds=30)
            last_ready = 0

            while True:
                current_ready = 0

                for app in self.apps:
                    current_ready += 1 if app.model.status == ApplicationStatus.READY else 0

                if current_ready > last_ready:
                    last_ready = current_ready
                    self.signal_updates.emit()

                if current_ready == len(self.apps):
                    self.signal_updates.emit()
                    break

                if stop_at <= datetime.utcnow():
                    break

                time.sleep(0.1)

        self.apps = None


class RefreshApp(AsyncAction):

    def __init__(self, manager: ApplicationManager, app: ApplicationView = None):
        super(RefreshApp, self).__init__()
        self.app = app
        self.manager = manager
        self.root_password = None

    def run(self):

        if self.app:
            success = False

            try:
                success = self.manager.refresh(self.app.model, self.root_password, self)
            except (requests.exceptions.ConnectionError, NoInternetException):
                success = False
                self.signal_output.emit(self.locale_keys['internet.required'])
            finally:
                self.app = None
                self.signal_finished.emit(success)


class FindSuggestions(AsyncAction):

    def __init__(self, man: ApplicationManager):
        super(FindSuggestions, self).__init__()
        self.man = man

    def run(self):
        sugs = self.man.list_suggestions(limit=-1)
        self.notify_finished(sugs if sugs is not None else [])


class ListWarnings(QThread):

    signal_warnings = pyqtSignal(list)

    def __init__(self, man: ApplicationManager, locale_keys: dict):
        super(QThread, self).__init__()
        self.locale_keys = locale_keys
        self.man = man

    def run(self):
        warnings = self.man.list_warnings()
        if warnings:
            self.signal_warnings.emit(warnings)
import os
import socket
import sys
from liblo import Address
from PyQt5.QtCore import QObject, QProcess, QTimer
from PyQt5.QtWidgets import QApplication

import ray
from gui_signaler import Signaler
from gui_server_thread import GUIServerThread
from gui_tools import (CommandLineArgs, default_session_root, ErrDaemon,
                       _translate)

_instance = None


class DaemonManager(QObject):
    def __init__(self, session):
        QObject.__init__(self)
        self._session = session
        self._signaler = self._session._signaler

        self.executable = 'ray-daemon'
        self.process = QProcess()

        self.process.finished.connect(self.processFinished)
        if ray.QT_VERSION >= (5, 6):
            self.process.errorOccurred.connect(self.errorInProcess)
        self.process.setProcessChannelMode(QProcess.ForwardedChannels)

        self.announce_timer = QTimer()
        self.announce_timer.setInterval(2000)
        self.announce_timer.setSingleShot(True)
        self.announce_timer.timeout.connect(self.announceTimerOut)

        self.stopped_yet = False
        self.is_local = True
        self.launched_before = False
        self.address = None
        self.port = None
        self.url = ''

        self.is_announced = False
        self.is_nsm_locked = False

        self._signaler.daemon_announce.connect(self.receiveAnnounce)
        self._signaler.daemon_url_changed.connect(self.changeUrl)

        global _instance
        _instance = self

    def finishInit(self):
        self._main_win = self._session._main_win

    @staticmethod
    def instance():
        global _instance
        if not _instance:
            _instance = DaemonManager()
        return _instance

    def processFinished(self, exit_code, exit_status):
        if self.stopped_yet:
            QApplication.quit()
            return

        if not self._main_win.isHidden():
            self._main_win.daemonCrash()
            return

    def errorInProcess(self, error):
        self._main_win.daemonCrash()

    def changeUrl(self, new_url):
        try:
            self.setOscAddress(ray.getLibloAddress(new_url))
        except BaseException:
            return

        self.callDaemon()

    def callDaemon(self):
        if not self.address:
            # I don't know really why, but it works only with a timer
            QTimer.singleShot(5, self.showDaemonUrlWindow)
            return

        self.announce_timer.start()

        server = GUIServerThread.instance()
        if not server:
            sys.stderr.write(
                'GUI can not call daemon, GUI OSC server is missing.\n')
            return

        server.announce()

    def showDaemonUrlWindow(self):
        self._signaler.daemon_url_request.emit(ErrDaemon.NO_ERROR, self.url)

    def announceTimerOut(self):
        if self.launched_before:
            self._signaler.daemon_url_request.emit(
                ErrDaemon.NO_ANNOUNCE, self.url)
        else:
            sys.stderr.write(
                _translate(
                    'error',
                    "No announce from ray-daemon. RaySession can't works. Sorry.\n"))
            QApplication.quit()

    def receiveAnnounce(
            self,
            src_addr,
            version,
            server_status,
            options,
            session_root,
            is_net_free):
        self.announce_timer.stop()

        if version.split('.')[:1] != ray.VERSION.split('.')[:1]:
            # works only if the two firsts digits are the same (ex: 0.6)
            self._signaler.daemon_url_request.emit(
                ErrDaemon.WRONG_VERSION, self.url)
            self.disannounce(src_addr)
            return

        if CommandLineArgs.net_session_root and session_root != CommandLineArgs.net_session_root:
            self._signaler.daemon_url_request.emit(
                ErrDaemon.WRONG_ROOT, self.url)
            self.disannounce(src_addr)
            return

        if not is_net_free:
            self._signaler.daemon_url_request.emit(
                ErrDaemon.FORBIDDEN_ROOT, self.url)
            self.disannounce(src_addr)
            return

        if CommandLineArgs.out_daemon and server_status != ray.ServerStatus.OFF:
            self._signaler.daemon_url_request.emit(ErrDaemon.NOT_OFF, self.url)
            self.disannounce(src_addr)
            return

        self.is_announced = True
        self.address = src_addr
        self.port = src_addr.port
        self.url = src_addr.url
        self.session_root = session_root

        self.is_nsm_locked = options & ray.Option.NSM_LOCKED
        save_all_from_saved_client = options & ray.Option.SAVE_FROM_CLIENT
        bookmark_session_folder = options & ray.Option.BOOKMARK_SESSION

        if self.is_nsm_locked:
            self._signaler.daemon_nsm_locked.emit(True)
        elif CommandLineArgs.under_nsm:
            server = GUIServerThread.instance()
            server.toDaemon('/ray/server/set_nsm_locked')

        self._signaler.daemon_announce_ok.emit()
        self._signaler.daemon_options.emit(options)

    def disannounce(self, address=None):
        if not address:
            address = self.address

        if address:
            server = GUIServerThread.instance()
            server.disannounce(address)

        self.port = None
        self.url = ''
        del self.address
        self.address = None
        self.is_announced = False

    def setExternal(self):
        self.launched_before = True

    def setOscAddress(self, address):
        self.address = address
        self.launched_before = True
        self.port = self.address.port
        self.url = self.address.url

        self.is_local = bool(self.address.hostname == socket.gethostname())

    def setOscAddressViaUrl(self, url):
        self.setOscAddress(ray.getLibloAddress(url))

    def processIsRunning(self):
        return bool(self.process.state() == 2)

    def start(self):
        if self.launched_before:
            self.callDaemon()
            return

        server = GUIServerThread.instance()
        if not server:
            sys.stderr.write(
                "impossible for GUI to launch daemon. server missing.\n")

        # start process
        arguments = ['--gui-url', str(server.url),
                     '--osc-port', str(self.port),
                     '--session-root', CommandLineArgs.session_root]
        
        if CommandLineArgs.session:
            arguments.append('--session')
            arguments.append(CommandLineArgs.session)

        if CommandLineArgs.debug_only:
            arguments.append('--debug-only')
        elif CommandLineArgs.debug:
            arguments.append('--debug')

        if CommandLineArgs.config_dir:
            arguments.append('--config-dir')
            arguments.append(CommandLineArgs.config_dir)

        self.process.start('ray-daemon', arguments)
        #self.process.start('konsole', ['-e', 'ray-daemon'] + arguments)

    def stop(self):
        if self.launched_before:
            self.disannounce()
            QApplication.quit()
            return

        if self.processIsRunning():
            if not self.stopped_yet:
                self.process.terminate()
                self.stopped_yet = True
                QTimer.singleShot(5000, self.notEndedAfterWait)

    def notEndedAfterWait(self):
        sys.stderr.write('ray-daemon is still running, sorry !\n')
        QApplication.quit()

    def setNewOscAddress(self):
        if not (self.address or self.port):
            self.port = ray.getFreeOscPort()
            self.address = Address(self.port)

    def setNsmLocked(self):
        self.is_nsm_locked = True

    def isAnnounced(self):
        return self.is_announced

    def setDisannounced(self):
        server = GUIServerThread.instance()
        server.disannounce()

        self.port = None
        self.url = ''
        del self.address
        self.address = None
        self.is_announced = False

    def getUrl(self):
        if self.address:
            return self.address.url

        return ''

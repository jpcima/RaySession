#!/usr/bin/python3 -u

import argparse
import os
import sys
import time
import signal
import shutil
import subprocess
from liblo import ServerThread, Address, make_method, Message
from PyQt5.QtCore import (pyqtSignal, QObject, QTimer, QProcess, QSettings,
                          QLocale, QTranslator, QFile)
from PyQt5.QtWidgets import (QApplication, QDialog, QFileDialog, QMessageBox,
                             QMainWindow)
from PyQt5.QtXml import QDomDocument

import ray
import nsm_client
import ui_proxy_gui
import ui_proxy_copy

ERR_OK = 0
ERR_NO_PROXY_FILE = -1
ERR_NOT_ENOUGHT_LINES = -2
ERR_NO_EXECUTABLE = -3
ERR_WRONG_ARGUMENTS = -4
ERR_WRONG_SAVE_SIGNAL = -5
ERR_WRONG_STOP_SIGNAL = -6


save_signals = {'None': None,
                'SIGUSR1': signal.SIGUSR1,
                'SIGUSR2': signal.SIGUSR2,
                'SIGINT': signal.SIGINT}

stop_signals = {'SIGTERM': signal.SIGTERM,
                'SIGINT': signal.SIGINT,
                'SIGHUP': signal.SIGHUP}


def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        proxy.stopProcess()
        sys.exit()


def ifDebug(string):
    if debug:
        #print(string, file=sys.stderr)
        sys.stderr.write(string + '\n')


class ProxyCopyDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = ui_proxy_copy.Ui_Dialog()
        self.ui.setupUi(self)

        self.rename_file = False
        self.ui.pushButtonCopyRename.clicked.connect(self.setRenameFile)

    def setRenameFile(self):
        self.rename_file = True
        self.accept()

    def setFile(self, path):
        self.ui.labelFileNotInFolder.setText(
            _translate(
                'Dialog', '%s is not in proxy directory') %
            ('<strong>' + os.path.basename(path) + '</strong>'))


class ProxyDialog(QMainWindow):
    def __init__(self, executable=''):
        QMainWindow.__init__(self)
        self.ui = ui_proxy_gui.Ui_MainWindow()
        self.ui.setupUi(self)

        self.config_file = ''
        self.args_edited = False
        self.fields_allow_start = False
        self.process_is_running = False

        self.ui.comboSaveSig.addItems(['None', 'SIGUSR1', 'SIGUSR2', 'SIGINT'])
        self.ui.comboStopSig.addItems(['SIGTERM', 'SIGINT', 'SIGHUP'])
        self.ui.toolButtonBrowse.clicked.connect(self.browseFile)

        self.ui.lineEditExecutable.textEdited.connect(
            self.lineEditExecutableEdited)
        self.ui.lineEditArguments.textChanged.connect(
            self.lineEditArgumentsChanged)
        self.ui.lineEditConfigFile.textChanged.connect(
            self.lineEditConfigFileChanged)

        self.ui.comboSaveSig.currentTextChanged.connect(self.allowSaveTest)
        self.ui.toolButtonTestSave.clicked.connect(self.testSave)
        self.ui.toolButtonTestSave.setEnabled(False)

        self.ui.pushButtonStart.clicked.connect(self.startProcess)
        self.ui.pushButtonStop.clicked.connect(self.stopProcess)
        self.ui.pushButtonStop.setEnabled(False)

        self.ui.lineEditExecutable.setText(executable)
        self.lineEditExecutableEdited(executable)

        self.ui.labelError.setText('')

        proxy.process.started.connect(self.proxyStarted)
        proxy.process.finished.connect(self.proxyFinished)
        if ray.QT_VERSION >= (5, 6):
            proxy.process.errorOccurred.connect(self.proxyErrorInProcess)

    def checkAllowStart(self):
        self.fields_allow_start = True
        if not self.ui.lineEditExecutable.text():
            self.fields_allow_start = False

        if ray.shellLineToArgs(self.ui.lineEditArguments.text()) is None:
            self.fields_allow_start = False

        self.ui.pushButtonStart.setEnabled(
            bool(not self.process_is_running and self.fields_allow_start))

    def updateValuesFromProxyFile(self):
        proxy_file = proxy.proxy_file

        self.ui.lineEditExecutable.setText(proxy_file.executable)
        self.ui.lineEditConfigFile.setText(proxy_file.config_file)
        self.ui.lineEditArguments.setText(proxy_file.arguments_line)

        for sig_str in save_signals:
            if save_signals[sig_str] == proxy_file.save_signal:
                self.ui.comboSaveSig.setCurrentText(sig_str)
                break

        for sig_str in stop_signals:
            if stop_signals[sig_str] == proxy_file.stop_signal:
                self.ui.comboStopSig.setCurrentText(sig_str)
                break

        self.ui.checkBoxWaitWindow.setChecked(proxy_file.wait_window)

        self.checkAllowStart()

    def browseFile(self):
        config_file, ok = QFileDialog.getOpenFileName(
            self, _translate('Dialog', 'Select File to use as CONFIG_FILE'))
        if not ok:
            return

        if not config_file.startswith(os.getcwd() + '/'):
            qfile = QFile(config_file)
            if qfile.size() < 20971520:  # if file < 20Mb
                copy_dialog = ProxyCopyDialog()
                copy_dialog.setFile(config_file)
                copy_dialog.exec()

                if copy_dialog.result():
                    if copy_dialog.rename_file:
                        base, pt, extension = os.path.basename(
                            config_file).rpartition('.')

                        config_file = "%s.%s" % (proxy.session_name, extension)
                        if not base:
                            config_file = proxy.session_name
                    else:
                        config_file = os.path.basename(config_file)

                    qfile.copy(config_file)

        self.config_file = os.path.relpath(config_file)
        self.ui.lineEditConfigFile.setText(self.config_file)

    def lineEditExecutableEdited(self, text):
        self.checkAllowStart()

    def lineEditArgumentsChanged(self, text):
        self.checkAllowStart()
        if ray.shellLineToArgs(text) is not None:
            self.ui.lineEditArguments.setStyleSheet('')
        else:
            self.ui.lineEditArguments.setStyleSheet(
                'QLineEdit{background: red}')
            self.ui.pushButtonStart.setEnabled(False)

    def lineEditConfigFileChanged(self, text):
        if text and not self.ui.lineEditArguments.text():
            self.ui.lineEditArguments.setText('"$CONFIG_FILE"')
        elif not text and self.ui.lineEditArguments.text() == '"$CONFIG_FILE"':
            self.ui.lineEditArguments.setText('')

    def allowSaveTest(self, text=None):
        if text is None:
            text = self.ui.comboSaveSig.currentText()

        self.ui.toolButtonTestSave.setEnabled(
            bool(self.process_is_running and text != 'None'))

    def testSave(self):
        save_signal = save_signals[self.ui.comboSaveSig.currentText()]
        proxy.saveProcess(save_signal)

    def saveProxyFile(self):
        executable = self.ui.lineEditExecutable.text()
        config_file = self.ui.lineEditConfigFile.text()
        arguments_line = self.ui.lineEditArguments.text()
        save_signal = save_signals[self.ui.comboSaveSig.currentText()]
        stop_signal = stop_signals[self.ui.comboStopSig.currentText()]
        wait_window = self.ui.checkBoxWaitWindow.isChecked()

        proxy.proxy_file.saveFile(
            executable,
            config_file,
            arguments_line,
            save_signal,
            stop_signal,
            wait_window)

    def startProcess(self):
        self.saveProxyFile()

        if proxy.proxy_file.is_launchable:
            proxy.startProcess()

    def stopProcess(self):
        proxy.stopProcess(stop_signals[self.ui.comboStopSig.currentText()])

    def proxyStarted(self):
        self.process_is_running = True
        self.ui.pushButtonStart.setEnabled(False)
        self.ui.pushButtonStop.setEnabled(True)
        self.allowSaveTest()
        self.ui.labelError.setText('')

    def processTerminateShortly(self, duration):
        self.ui.labelError.setText('Process terminate in %f ms')

    def proxyFinished(self):
        self.process_is_running = False
        self.ui.pushButtonStart.setEnabled(self.fields_allow_start)
        self.ui.pushButtonStop.setEnabled(False)
        self.allowSaveTest()
        self.ui.labelError.setText('')

    def proxyErrorInProcess(self):
        self.ui.labelError.setText(
            _translate(
                'Dialog',
                'Executable failed to launch ! It\'s maybe not present on system.'))
        if not self.isVisible():
            self.show()

    def closeEvent(self, event):
        server.sendToDaemon('/nsm/client/gui_is_hidden')
        settings.setValue(
            'ProxyGui%s/geometry' %
            proxy.full_client_id,
            self.saveGeometry())
        settings.setValue(
            'ProxyGui%s/WindowState' %
            proxy.full_client_id, self.saveState())
        settings.sync()

        if self.fields_allow_start:
            self.saveProxyFile()

        QMainWindow.closeEvent(self, event)

        # Quit if process is not running yet
        if not proxy.process.state() == QProcess.Running:
            sys.exit(0)

    def showEvent(self, event):
        server.sendToDaemon('/nsm/client/gui_is_shown')

        if settings.value('ProxyGui%s/geometry' % proxy.full_client_id):
            self.restoreGeometry(
                settings.value(
                    'ProxyGui%s/geometry' %
                    proxy.full_client_id))
        if settings.value('ProxyGui%s/WindowState' % proxy.full_client_id):
            self.restoreState(
                settings.value(
                    'ProxyGui%s/WindowState' %
                    proxy.full_client_id))

        self.updateValuesFromProxyFile()

        QMainWindow.showEvent(self, event)
##########################


class Proxy(QObject):
    def __init__(self, executable=''):
        QObject.__init__(self)
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.ForwardedChannels)
        self.process.finished.connect(self.processFinished)

        self.proxy_file = None
        self.project_path = None
        self.session_name = None
        self.full_client_id = None

        self.executable = executable
        self.arguments = []
        self.arguments_line = ''
        self.config_file = None
        self.save_signal = None
        self.stop_signal = signal.SIGTERM
        self.label = None

        self.wait_window = False

        self.timer_save = QTimer()
        self.timer_save.setSingleShot(True)
        self.timer_save.setInterval(300)
        self.timer_save.timeout.connect(self.timerSaveFinished)

        self.timer_open = QTimer()
        self.timer_open.setSingleShot(True)
        self.timer_open.setInterval(500)
        self.timer_open.timeout.connect(self.timerOpenFinished)

        self.is_finishable = False
        self.timer_close = QTimer()
        self.timer_close.setSingleShot(True)
        self.timer_close.setInterval(2500)
        self.timer_close.timeout.connect(self.timerCloseFinished)
        self.timer_close.start()
        self.process_start_time = time.time()

        self.timer_window = QTimer()
        self.timer_window.setInterval(100)
        self.timer_window.timeout.connect(self.checkWindow)
        self.timer_window_n = 0

        signaler.server_sends_open.connect(self.initialize)
        signaler.server_sends_save.connect(self.saveProcess)
        signaler.show_optional_gui.connect(self.showOptionalGui)
        signaler.hide_optional_gui.connect(self.hideOptionalGui)

    def isRunning(self):
        return bool(self.process.state() == QProcess.Running)

    def checkWindow(self):
        self.timer_window_n += 1

        if self.timer_window_n > 600:
            # 600 x 50ms = 30s max until ray-proxy replyOpen to Session Manager
            self.checkWindowEnded()
            return

        try:
            # get all windows and their PID with wmctrl
            wmctrl_all = subprocess.check_output(
                ['wmctrl', '-l', '-p']).decode()
        except BaseException:
            self.checkWindowEnded()
            return

        if not wmctrl_all:
            self.checkWindowEnded()
            return

        all_lines = wmctrl_all.split('\n')
        pids = []

        # get all windows pids
        for line in all_lines:
            if not line:
                continue

            line_sep = line.split(' ')
            non_empt = []
            for el in line_sep:
                if el:
                    non_empt.append(el)

            if len(non_empt) >= 3 and non_empt[2].isdigit():
                pids.append(int(non_empt[2]))
            else:
                # window manager seems to not work correctly with wmctrl, so
                # replyOpen now
                self.checkWindowEnded()
                return

        parent_pid = self.process.pid()

        # check in pids if one comes from this ray-proxy
        for pid in pids:
            if pid < parent_pid:
                continue

            ppid = pid

            while ppid != parent_pid and ppid > 1:
                try:
                    ppid = int(subprocess.check_output(
                        ['ps', '-o', 'ppid=', '-p', str(ppid)]))
                except BaseException:
                    self.checkWindowEnded()
                    return

            if ppid == parent_pid:
                # a window appears with a pid child of this ray-proxy,
                # replyOpen
                QTimer.singleShot(200, self.checkWindowEnded)
                break

    def checkWindowEnded(self):
        self.timer_window.stop()
        server.openReply()

    def processFinished(self, exit_code):
        if self.is_finishable:
            if not proxy_dialog.isVisible():
                sys.exit(0)
        else:
            duration = time.time() - self.process_start_time
            proxy_dialog.processTerminateShortly(duration)
            # proxy_dialog.show()

    def initialize(self, project_path, session_name, full_client_id):
        self.project_path = project_path
        self.session_name = session_name
        self.full_client_id = full_client_id

        server.sendGuiState(False)

        if not os.path.exists(project_path):
            os.mkdir(project_path)

        os.chdir(project_path)

        proxy_dialog.setWindowTitle(self.full_client_id)

        self.proxy_file = ProxyFile(project_path, self.executable)
        self.proxy_file.readFile()

        proxy_dialog.updateValuesFromProxyFile()

        if not self.proxy_file.is_launchable:
            server.openReply()
            proxy_dialog.show()
            return

        self.startProcess()

    def startProcess(self):
        os.environ['NSM_CLIENT_ID'] = self.full_client_id
        os.environ['RAY_SESSION_NAME'] = self.session_name

        # enable environment vars in config_file
        config_file = os.path.expandvars(self.proxy_file.config_file)
        os.environ['CONFIG_FILE'] = config_file

        # Useful for launching with specifics arguments clients NSM compatible
        os.unsetenv('NSM_URL')

        arguments_line = os.path.expandvars(self.proxy_file.arguments_line)
        arguments = ray.shellLineToArgs(arguments_line)

        self.process.start(self.proxy_file.executable, arguments)
        self.timer_open.start()

    def saveProcess(self, save_signal=None):
        if not save_signal:
            save_signal = self.proxy_file.save_signal

        if self.isRunning() and save_signal:
            os.kill(self.process.processId(), save_signal)

        self.timer_save.start()

    def stopProcess(self, signal=signal.SIGTERM):
        if signal is None:
            return

        if not self.isRunning():
            return

        os.kill(self.process.processId(), signal)

    def timerSaveFinished(self):
        server.saveReply()

    def timerOpenFinished(self):
        if self.proxy_file.wait_window:
            self.timer_window.start()
        else:
            server.openReply()

        if self.isRunning() and proxy_dialog.isVisible():
            proxy_dialog.close()

    def timerCloseFinished(self):
        self.is_finishable = True

    def stop(self):
        if self.process.state:
            self.process.terminate()

    def showOptionalGui(self):
        proxy_dialog.show()

    def hideOptionalGui(self):
        if not proxy_dialog.isHidden():
            proxy_dialog.close()


class ProxyFile(object):
    def __init__(self, project_path, executable=''):
        self.file = None
        self.path = "%s/ray-proxy.xml" % project_path

        self.executable = executable
        self.arguments_line = ''
        self.config_file = ''
        self.args_line = ''
        self.save_signal = None
        self.stop_signal = signal.SIGTERM
        self.wait_window = False

        self.is_launchable = False

    def readFile(self):
        self.is_launchable = False
        try:
            file = open(self.path, 'r')
        except BaseException:
            return

        xml = QDomDocument()
        xml.setContent(file.read())

        content = xml.documentElement()

        if content.tagName() != "RAY-PROXY":
            file.close()
            return

        cte = content.toElement()
        self.executable = cte.attribute('executable')
        self.config_file = cte.attribute('config_file')
        self.arguments_line = cte.attribute('arguments')
        save_signal = cte.attribute('save_signal')
        stop_signal = cte.attribute('stop_signal')

        wait_window = cte.attribute('wait_window')

        if wait_window.isdigit():
            self.wait_window = bool(int(wait_window))
        else:
            self.wait_window = False

        file.close()

        if save_signal.isdigit():
            for sg in save_signals.values():
                if not sg:
                    continue

                if int(save_signal) == int(sg):
                    self.save_signal = int(save_signal)
                    break

        elif save_signal in save_signals.keys():
            if save_signal == 'None':
                self.save_signal = None
            else:
                self.save_signal = int(save_signals[save_signal])

        if stop_signal.isdigit():
            for sg in stop_signals.values():
                if not sg:
                    continue

                if int(stop_signal) == int(sg):
                    self.stop_signal = int(stop_signal)
                    break

        elif stop_signal in stop_signals.keys():
            if stop_signal == 'None':
                self.stop_signal = None
            else:
                self.stop_signal = int(stop_signals[stop_signal])

        if not self.executable:
            return

        arguments = ray.shellLineToArgs(self.arguments_line)
        if arguments is None:
            return

        self.is_launchable = True

    def saveFile(
            self,
            executable,
            config_file,
            arguments_line,
            save_signal,
            stop_signal,
            wait_window):
        try:
            file = open(self.path, 'w')
        except BaseException:
            return

        if not save_signal:
            save_signal = 0

        xml = QDomDocument()
        p = xml.createElement('RAY-PROXY')
        p.setAttribute('VERSION', ray.VERSION)
        p.setAttribute('executable', executable)
        p.setAttribute('arguments', arguments_line)
        p.setAttribute('config_file', config_file)
        p.setAttribute('save_signal', str(int(save_signal)))
        p.setAttribute('stop_signal', str(int(save_signal)))
        p.setAttribute('wait_window', wait_window)

        xml.appendChild(p)

        contents = "<?xml version='1.0' encoding='UTF-8'?>\n"
        contents += "<!DOCTYPE RAY-PROXY>\n"
        contents += xml.toString()

        file.write(contents)
        file.close()

        self.readFile()


if __name__ == '__main__':
    NSM_URL = os.getenv('NSM_URL')
    if not NSM_URL:
        sys.stderr.write('Could not register as NSM client.\n')
        sys.exit()

    daemon_address = ray.getLibloAddress(NSM_URL)

    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', default='')
    parser.add_argument('--debug',
                        '-d',
                        action='store_true',
                        help='see all OSC messages')
    parser.add_argument('-v', '--version', action='version',
                        version=ray.VERSION)
    parsed_args = parser.parse_args()

    debug = parsed_args.debug
    executable = parsed_args.executable

    signal.signal(signal.SIGINT, signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)

    app = QApplication(sys.argv)
    app.setApplicationName("RaySession")
    # app.setApplicationVersion(ray.VERSION)
    app.setOrganizationName("RaySession")
    app.setQuitOnLastWindowClosed(False)
    settings = QSettings()

    # Translation process
    locale = QLocale.system().name()
    appTranslator = QTranslator()
    
    if appTranslator.load(
        "%s/locale/raysession_%s" %
        (os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    sys.argv[0]))),
         locale)):
        app.installTranslator(appTranslator)
    _translate = app.translate

    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    signaler = nsm_client.NSMSignaler()

    proxy = Proxy(executable)
    proxy_dialog = ProxyDialog()

    server = nsm_client.NSMThread('ray-proxy', signaler,
                                  daemon_address, debug)
    server.start()
    server.announce('Ray Proxy', ':optional-gui:', 'ray-proxy')

    app.exec()

    settings.sync()
    server.stop()

    del server
    del proxy
    del app

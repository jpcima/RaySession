#!/usr/bin/python3 -u

import argparse
import os
import signal
import sys
import unicodedata

from PyQt5.QtCore import (QCoreApplication, QTimer, QSettings, 
                          QStandardPaths, QLocale, QTranslator)

import ray
from daemon_tools import (initDaemonTools, RS, getCodeRoot,
                          CommandLineArgs, ArgParser, Terminal)
from osc_server_thread import OscServerThread
from multi_daemon_file import MultiDaemonFile
from signaler import Signaler
from session  import SignaledSession

def signalHandler(sig, frame):
    if sig in (signal.SIGINT, signal.SIGTERM):
        session.terminate()


if __name__ == '__main__':
    #add RaySession/src/bin to $PATH
    ray.addSelfBinToPath()
    
    #check arguments
    parser = ArgParser()
    
    #create app
    app = QCoreApplication(sys.argv)
    app.setApplicationName("RaySession")
    app.setOrganizationName("RaySession")
    
    #
    initDaemonTools()
    
    ### Translation process
    locale = QLocale.system().name()
    appTranslator = QTranslator()
    
    if appTranslator.load("%s/locale/raysession_%s"
                            % (getCodeRoot(), locale)):
        app.installTranslator(appTranslator)
        
    _translate = app.translate
    
    #manage session_root
    session_root = CommandLineArgs.session_root
    if not session_root:
        session_root = "%s/%s" % (os.getenv('HOME'), 
                                  _translate('daemon', 
                                             'Ray Network Sessions'))
    
    #make session_root folder if needed
    if not os.path.isdir(session_root):
        if os.path.exists(session_root):
            sys.stderr.write(
                "%s exists and is not a dir, please choose another path !\n"
                    % session_root)
            sys.exit(1)
        
        try:
            os.makedirs(session_root)
        except:
            sys.stderr.write("impossible to make dir %s , aborted !\n"
                             % session_root)
            sys.exit(1)
    
    
    #create session
    session  = SignaledSession(session_root)
    
    #create and start server
    if CommandLineArgs.findfreeport:
        server = OscServerThread(
                    session,
                    ray.getFreeOscPort(CommandLineArgs.osc_port))
    else:
        if ray.isOscPortFree(CommandLineArgs.osc_port):
            server = OscServerThread(session, CommandLineArgs.osc_port)
        else:
            sys.stderr.write(
                _translate('daemon', 
                           'port %i is not free, try another one\n')
                    % CommandLineArgs.osc_port)
            sys.exit()
    server.start()
    
    #announce server to GUI
    if CommandLineArgs.gui_url:
        server.announceGui(CommandLineArgs.gui_url.url)
        
    #print server url
    Terminal.message('URL : %s' % ray.getNetUrl(server.port))
    Terminal.message('      %s' % server.url)
    Terminal.message('ROOT: %s' % CommandLineArgs.session_root)
    
    #create or update multi_daemon_file in /tmp
    multi_daemon_file = MultiDaemonFile(session, server)
    multi_daemon_file.update()
    
    #clean bookmarks created by crashed daemons
    session.bookmarker.clean(multi_daemon_file.getAllSessionPaths())
    
    #load session asked from command line
    if CommandLineArgs.session:
        session.serverOpenSessionAtStart(CommandLineArgs.session)
    
    #connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT,  signalHandler)
    signal.signal(signal.SIGTERM, signalHandler)
    
    #needed for SIGINT and SIGTERM
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    
    #start app
    app.exec()
    #app is stopped
    
    #update multi_daemon_file without this server
    multi_daemon_file.quit()
    
    #save RS.settings
    RS.settings.setValue('daemon/non_active_list', RS.non_active_clients)
    RS.settings.setValue('daemon/save_all_from_saved_client', 
                      server.option_save_from_client)
    RS.settings.setValue('daemon/bookmark_session_folder', 
                      server.option_bookmark_session)
    RS.settings.setValue('daemon/desktops_memory', server.option_desktops_memory)
    RS.settings.sync()
    
    #stop the server
    server.stop()
    
    del server
    del session
    del app

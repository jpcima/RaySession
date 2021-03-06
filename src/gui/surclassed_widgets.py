from PyQt5.QtWidgets import (QLineEdit, QStackedWidget, QLabel, QToolButton,
                             QFrame)
from PyQt5.QtGui import QFont, QFontDatabase, QFontMetrics, QPalette
from PyQt5.QtCore import Qt, QTimer, pyqtSignal


class HideGuiButton(QToolButton):
    toggleGui = pyqtSignal()

    def __init__(self, parent):
        QToolButton.__init__(self, parent)

        basecolor = self.palette().base().color().name()
        textcolor = self.palette().buttonText().color().name()
        textdbcolor = self.palette().brush(
            QPalette.Disabled, QPalette.WindowText).color().name()

        style = "QToolButton{border-radius: 2px ;border-left: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textcolor + ", stop:0.35 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textcolor + ")" \
            + ";border-right: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textcolor + ", stop:0.25 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textcolor + ")" \
            + ";border-top: 1px solid " + textcolor \
            + ";border-bottom : 1px solid " + textcolor \
            +  "; background-color: " + basecolor + "; font-size: 11px" + "}"\
            + "QToolButton::checked{background-color: " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textcolor + ", stop:0.25 " + basecolor + ", stop:0.85 " \
            + basecolor + ", stop:1 " + textcolor + ")" \
            + "; margin-top: 0px; margin-left: 0px " + "}" \
            + "QToolButton::disabled{;border-left: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textdbcolor + ", stop:0.25 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textdbcolor + ")" \
            + ";border-right: 1px solid " \
            + "qlineargradient(spread:pad, x1:0, y1:0, x2:0, y2:1, stop:0 " \
            + textdbcolor + ", stop:0.25 " + basecolor + ", stop:0.75 " \
            + basecolor + ", stop:1 " + textdbcolor + ")" \
            + ";border-top: 1px solid " + textdbcolor \
            + ";border-bottom : 1px solid " + textdbcolor \
            + "; background-color: " + basecolor + "}"

        self.setStyleSheet(style)

    def mousePressEvent(self, event):
        self.toggleGui.emit()
        # and not toggle button, the client will emit a gui state that will
        # toggle this button


class OpenSessionFilterBar(QLineEdit):
    updownpressed = pyqtSignal(int)

    def __init__(self, parent):
        QLineEdit.__init__(self)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.updownpressed.emit(event.key())
        QLineEdit.keyPressEvent(self, event)
        
        
class CustomLineEdit(QLineEdit):
    def __init__(self, parent):
        QLineEdit.__init__(self)
        self.parent = parent

    def mouseDoubleClickEvent(self, event):
        self.parent.mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self.parent.name_changed.emit(self.text())
            self.parent.setCurrentIndex(0)
            return

        QLineEdit.keyPressEvent(self, event)


class SessionFrame(QFrame):
    def __init__(self, parent):
        QFrame.__init__(self)
        

class StackedSessionName(QStackedWidget):
    name_changed = pyqtSignal(str)

    def __init__(self, parent):
        QStackedWidget.__init__(self)
        self.is_editable = True

        self.label_widget = QLabel()
        self.label_widget.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.label_widget.setStyleSheet("QLabel {font-weight : bold}")

        self.line_edit_widget = CustomLineEdit(self)
        self.line_edit_widget.setAlignment(Qt.AlignHCenter)

        self.addWidget(self.label_widget)
        self.addWidget(self.line_edit_widget)

        self.setCurrentIndex(0)

    def mouseDoubleClickEvent(self, event):
        if self.currentIndex() == 1:
            self.setCurrentIndex(0)
            self.name_changed.emit(self.line_edit_widget.text())
            return

        elif self.currentIndex() == 0 and self.is_editable:
            self.setCurrentIndex(1)
            return

        QStackedWidget.mouseDoubleClickEvent(self, event)

    def setEditable(self, editable):
        self.is_editable = editable

        if not editable:
            self.setCurrentIndex(0)

    def setText(self, text):
        self.label_widget.setText(text)
        self.line_edit_widget.setText(text)

        self.setCurrentIndex(0)

    def toggleEdit(self):
        if not self.is_editable:
            self.setCurrentIndex(0)
            return

        if self.currentIndex() == 0:
            self.setCurrentIndex(1)
            self.line_edit_widget.setFocus(Qt.OtherFocusReason)
        else:
            self.setCurrentIndex(0)

    def setOnEdit(self):
        if not self.is_editable:
            return

        self.setCurrentIndex(1)
        

class StatusBar(QLineEdit):
    copyAborted = pyqtSignal()

    def __init__(self, parent):
        QLineEdit.__init__(self)
        self.next_texts = []
        self.timer = QTimer()
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.showNextText)

        self.ubuntu_font = QFont(
            QFontDatabase.applicationFontFamilies(0)[0], 8)
        self.ubuntu_font_cond = QFont(
            QFontDatabase.applicationFontFamilies(1)[0], 8)
        self.ubuntu_font.setBold(True)
        self.ubuntu_font_cond.setBold(True)

        self.basecolor = self.palette().base().color().name()
        self.bluecolor = self.palette().highlight().color().name()
        
        # ui_client_slot.py will display "stopped" status.
        # we need to not stay on this status text
        # especially at client switch because widget is recreated.
        self._first_text_done = False

    def showNextText(self):
        if self.next_texts:
            next_text = self.next_texts[0]
            self.next_texts.__delitem__(0)
            self.setText(next_text, True)
        else:
            self.timer.stop()
            
    def setFontForText(self, text):
        if QFontMetrics(self.ubuntu_font).width(text) > (self.width() - 10):
            self.setFont(self.ubuntu_font_cond)
        else:
            self.setFont(self.ubuntu_font)

    def setText(self, text, from_timer=False):
        if not self._first_text_done:
            self.setFontForText(text)
            QLineEdit.setText(self, text)
            self._first_text_done = True
            return
        
        if text and not from_timer:
            if self.timer.isActive():
                self.next_texts.append(text)
                return
            self.timer.start()

        if not text:
            self.next_texts.clear()

        self.setFontForText(text)

        self.setStyleSheet('')

        QLineEdit.setText(self, text)

    def setProgress(self, progress):
        if not 0.0 <= progress <= 1.0:
            return

        pre_progress = progress - 0.03
        if pre_progress < 0:
            pre_progress = 0

        style = "QLineEdit{background-color: " \
                + "qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0," \
                + "stop:0 %s, stop:%f %s, stop:%f %s, stop:1 %s)}" \
                    % (self.bluecolor, pre_progress, self.bluecolor,
                       progress, self.basecolor, self.basecolor)

        self.setStyleSheet(style)

    def mousePressEvent(self, event):
        self.copyAborted.emit()


class StatusBarNegativ(StatusBar):
    def __init__(self, parent):
        StatusBar.__init__(self, parent)

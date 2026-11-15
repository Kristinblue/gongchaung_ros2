#include <QApplication>
#include <QColor>
#include <QCloseEvent>
#include <QComboBox>
#include <QDir>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFontDatabase>
#include <QFormLayout>
#include <QFrame>
#include <QGuiApplication>
#include <QHBoxLayout>
#include <QHostAddress>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QKeyEvent>
#include <QLabel>
#include <QClipboard>
#include <QPaintEvent>
#include <QPainter>
#include <QMenu>
#include <QNetworkAccessManager>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QPlainTextEdit>
#include <QPointer>
#include <QProcess>
#include <QPushButton>
#include <QRegularExpression>
#include <QScreen>
#include <QScrollBar>
#include <QSettings>
#include <QSpinBox>
#include <QSplitter>
#include <QStandardPaths>
#include <QTcpServer>
#include <QTextCharFormat>
#include <QTabWidget>
#include <QTimer>
#include <QToolButton>
#include <QTextCursor>
#include <QToolTip>
#include <QUrlQuery>
#include <QVBoxLayout>
#include <functional>

// 显示 SSH 远端命令的输出，并把提示符后的输入交给 Client。
class Terminal : public QPlainTextEdit {
public:
  std::function<void(const QString &)> onCommand;
  std::function<void()> onInterrupt;

  explicit Terminal(QWidget *parent = nullptr) : QPlainTextEdit(parent) {
    setObjectName("output");
    setReadOnly(true);
    setTextInteractionFlags(Qt::TextSelectableByMouse | Qt::TextSelectableByKeyboard);
    setAcceptDrops(false);
    viewport()->setAcceptDrops(false);
    setMaximumBlockCount(2000);
    base_.setForeground(QColor("#d4d4d4"));
    connect(&blink_, &QTimer::timeout, this, [this] {
      blinkOn_ = !blinkOn_;
      if (hasFocus()) viewport()->update(cursorRect());
    });
    blink_.start(530);
  }

  void setPrompt(const QString &text) { prompt_ = text; }
  void setTestPrompt(bool enabled) {
    if (enabled == testPrompt_) return;
    testPrompt_ = enabled;
    resetHistoryPosition();
  }
  void waitForOutput() {
    if (ready_) {
      auto cursor = promptCursor_;
      cursor.movePosition(QTextCursor::End, QTextCursor::KeepAnchor);
      cursor.removeSelectedText();
    }
    ready_ = false;
    busy_ = true;
    resetHistoryPosition();
  }
  void reset() {
    ready_ = busy_ = false;
    promptCursor_ = {};
    clear();
    resetHistoryPosition();
  }
  void showNotice(const QString &text) {
    reset();
    writeText(text, base_);
  }
  void showPrompt() { finish(); }
  void writeData(QString data) {
    if (!data.endsWith('\n')) data += '\n';
    ansi(data);
  }
  void finish() {
    if (ready_) return;
    busy_ = false;
    const auto prompt = (testPrompt_ ? QString("cmd>") : prompt_) + " ";
    writeText(prompt, promptFormat());
    promptCursor_ = QTextCursor(document());
    promptCursor_.movePosition(QTextCursor::End);
    promptCursor_.setPosition(promptCursor_.position() - prompt.size());
    promptLength_ = prompt.size();
    ready_ = true;
    if (!textCursor().hasSelection()) moveCursor(QTextCursor::End);
  }

protected:
  void paintEvent(QPaintEvent *event) override {
    QPlainTextEdit::paintEvent(event);
    if (!ready_ || !hasFocus() || !blinkOn_ || textCursor().hasSelection()) return;
    auto rect = cursorRect();
    rect.setWidth(2);
    QPainter(viewport()).fillRect(rect, QColor("#d4d4d4"));
  }

  void keyPressEvent(QKeyEvent *key) override {
    if (key->matches(QKeySequence::Copy)) {
      if (textCursor().hasSelection()) copy();
      else if (busy_ && onInterrupt) onInterrupt();
      return;
    }
    if (!ready_) {
      QPlainTextEdit::keyPressEvent(key);
      return;
    }
    if (key->modifiers() == Qt::ControlModifier && key->key() == Qt::Key_L) {
      const auto draft = commandText();
      reset();
      finish();
      insertInput(draft);
      return;
    }
    switch (key->key()) {
      case Qt::Key_Up: recall(-1); return;
      case Qt::Key_Down: recall(1); return;
      case Qt::Key_Left:
        if (!textCursor().hasSelection() && textCursor().position() == inputStart()) return;
        break;
      case Qt::Key_Return:
      case Qt::Key_Enter: submit(); return;
      case Qt::Key_Home:
      case Qt::Key_End: {
        auto cursor = textCursor();
        cursor.setPosition(key->key() == Qt::Key_Home ? inputStart() : document()->characterCount() - 1,
                           key->modifiers().testFlag(Qt::ShiftModifier) ? QTextCursor::KeepAnchor : QTextCursor::MoveAnchor);
        setTextCursor(cursor);
        return;
      }
      case Qt::Key_Backspace:
      case Qt::Key_Delete: {
        auto cursor = inputCursor();
        if (cursor.hasSelection()) cursor.removeSelectedText();
        else if (key->key() == Qt::Key_Delete) cursor.deleteChar();
        else if (cursor.position() > inputStart()) cursor.deletePreviousChar();
        setTextCursor(cursor);
        return;
      }
      default: break;
    }
    if (key->matches(QKeySequence::Paste)) {
      insertInput(QApplication::clipboard()->text());
    } else if (!key->text().isEmpty() && key->text().front().isPrint() &&
               !key->modifiers().testFlag(Qt::ControlModifier)) {
      insertInput(key->text());
    } else {
      QPlainTextEdit::keyPressEvent(key);
    }
  }

private:
  int inputStart() const { return promptCursor_.position() + promptLength_; }

  // 光标选中旧输出时还能复制，编辑命令时只允许更改提示符后面的文字。
  QTextCursor inputCursor() const {
    auto cursor = textCursor();
    if (cursor.selectionStart() < inputStart()) cursor.movePosition(QTextCursor::End);
    return cursor;
  }

  void insertInput(QString text) {
    text.replace('\r', ' ').replace('\n', ' ');
    auto cursor = inputCursor();
    cursor.insertText(text, base_);
    setTextCursor(cursor);
    ensureCursorVisible();
  }

  QString commandText() const {
    auto cursor = promptCursor_;
    cursor.setPosition(inputStart());
    cursor.movePosition(QTextCursor::End, QTextCursor::KeepAnchor);
    return cursor.selectedText();
  }

  QStringList &history() { return testPrompt_ ? testHistory_ : shellHistory_; }

  void resetHistoryPosition() {
    historyIndex_ = history().size();
    draft_.clear();
  }

  void recall(int step) {
    const auto &entries = history();
    if (historyIndex_ == entries.size()) draft_ = commandText();
    historyIndex_ = qBound(qsizetype(0), historyIndex_ + step, entries.size());
    auto cursor = promptCursor_;
    cursor.setPosition(inputStart());
    cursor.movePosition(QTextCursor::End, QTextCursor::KeepAnchor);
    setTextCursor(cursor);
    insertInput(historyIndex_ == entries.size() ? draft_ : entries[historyIndex_]);
  }

  void submit() {
    const auto command = commandText();
    if (!command.trimmed().isEmpty() && !onCommand) return;
    ready_ = false;
    writeText("\n", base_);
    if (command.trimmed().isEmpty()) {
      finish();
      return;
    }
    auto &entries = history();
    if (entries.isEmpty() || entries.last() != command) entries.append(command);
    if (entries.size() > 100) entries.removeFirst();
    waitForOutput();
    onCommand(command);
  }

  static QTextCharFormat promptFormat() {
    QTextCharFormat format;
    format.setForeground(QColor("#35c46a"));
    format.setFontWeight(QFont::DemiBold);
    return format;
  }

  void writeText(const QString &text, const QTextCharFormat &format) {
    auto *scroll = verticalScrollBar();
    const bool follow = scroll->value() == scroll->maximum() && !textCursor().hasSelection();
    QTextCursor cursor = ready_ ? promptCursor_ : QTextCursor(document());
    if (!ready_) cursor.movePosition(QTextCursor::End);
    cursor.insertText(text, format);
    if (follow) scroll->setValue(scroll->maximum());
  }

  // 远端输出可能带终端颜色控制码，转换成 Qt 的文字格式再显示。
  void ansi(const QString &data) {
    QTextCharFormat format;
    format.setForeground(QColor("#d4d4d4"));
    auto *scroll = verticalScrollBar();
    const bool follow = scroll->value() == scroll->maximum() && !textCursor().hasSelection();
    QTextCursor cursor = ready_ ? promptCursor_ : QTextCursor(document());
    if (!ready_) cursor.movePosition(QTextCursor::End);
    int i = 0;
    while (i < data.size()) {
      if (data[i] == QChar(0x1b)) {
        if (i + 1 < data.size() && data[i + 1] == '[') {
          int j = i + 2;
          QString params;
          while (j < data.size() && (data[j].isDigit() || data[j] == ';')) params += data[j++];
          if (j < data.size()) {
            if (data[j] == 'm') applySgr(params, format);
            i = j + 1;
            continue;
          }
        } else if (i + 1 < data.size() && data[i + 1] == ']') {
          int j = i + 2;
          while (j < data.size() && data[j] != QChar(7)) ++j;
          i = j + 1;
          continue;
        }
        ++i;
        continue;
      }
      const int start = i;
      while (i < data.size() && data[i] != QChar(0x1b)) ++i;
      cursor.insertText(data.mid(start, i - start), format);
    }
    if (follow) scroll->setValue(scroll->maximum());
  }

  static void applySgr(const QString &params, QTextCharFormat &format) {
    const auto parts = params.isEmpty() ? QStringList{"0"} : params.split(';');
    for (const auto &part : parts) {
      bool ok = false;
      const int code = part.isEmpty() ? 0 : part.toInt(&ok);
      if (!ok) continue;
      if (code == 0) {
        format = QTextCharFormat();
        format.setForeground(QColor("#d4d4d4"));
      } else if (code == 1) {
        format.setFontWeight(QFont::Bold);
      } else if (code == 22) {
        format.setFontWeight(QFont::Normal);
      } else if (code == 3) {
        format.setFontItalic(true);
      } else if (code == 23) {
        format.setFontItalic(false);
      } else if (code == 4) {
        format.setFontUnderline(true);
      } else if (code == 24) {
        format.setFontUnderline(false);
      } else if (code == 39) {
        format.setForeground(QColor("#d4d4d4"));
      } else if (code >= 30 && code <= 37) {
        static const char *colors[] = {"#555b66", "#e06c75", "#98c379", "#e5c07b",
                                       "#61afef", "#c678dd", "#56b6c2", "#dcdfe4"};
        format.setForeground(QColor(colors[code - 30]));
      } else if (code >= 90 && code <= 97) {
        static const char *bright[] = {"#7f848e", "#ff7b86", "#b5e890", "#ffd68a",
                                       "#7cc4ff", "#e29bf0", "#6fd7e3", "#ffffff"};
        format.setForeground(QColor(bright[code - 90]));
      }
    }
  }

  QString prompt_{"$"};
  QString draft_;
  QStringList shellHistory_, testHistory_;
  qsizetype historyIndex_{0};
  bool busy_{false};
  bool ready_{false};
  bool testPrompt_{false};
  QTextCursor promptCursor_;
  int promptLength_{0};
  bool blinkOn_{true};
  QTimer blink_;
  QTextCharFormat base_;
};

// Windows 客户端。HTTP 负责预览和设置，另一条 SSH 会话负责执行手动输入的命令。
class Client : public QWidget {
public:
  Client() {
    setObjectName("root");
    setWindowTitle("工创赛客户端");
    setMinimumSize(520, 340);
    http_.setProxy(QNetworkProxy::NoProxy);
    ssh_.setProcessChannelMode(QProcess::MergedChannels);
    shell_.setProcessChannelMode(QProcess::MergedChannels);

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 10, 12, 12);
    layout->setSpacing(8);

    auto *bar = new QFrame;
    bar->setObjectName("card");
    auto *connection = new QHBoxLayout(bar);
    connection->setContentsMargins(10, 6, 10, 6);
    connection->setSpacing(8);
    auto *caption = new QLabel("连接");
    caption->setObjectName("caption");
    mode_->addItems({"pio", "pio-relay", "pio-wired"});
    connect_->setObjectName("primary");
    status_->setObjectName("status");
    connection->addWidget(caption);
    connection->addWidget(mode_, 0);
    connection->addWidget(connect_);
    auto *tests = new QMenu(previewStart_);
    auto *approachTest = tests->addAction("运行靠近测试 · approach_test_node", this, [this] { runPreview("start approach"); });
    auto *cameraTest = tests->addAction("运行摄像头测试 · camera_test_node", this, [this] { runPreview("start camera_test"); });
    auto *serialTests = tests->addMenu("运行串口测试 · serial_test_node");
    tests->addSeparator();
    tests->addAction("结束测试", this, [this] {
      if (serialTest_) execute("quit");
      else runPreview("start preview");
    });
    connect(tests, &QMenu::aboutToShow, this, [this, approachTest, cameraTest, serialTests] {
      for (auto *action : {approachTest, cameraTest, serialTests->menuAction()}) action->setEnabled(!serialTest_);
    });
    previewStart_->setObjectName("testMenu");
    previewStart_->setText("测试节点  ▼");
    tests->setObjectName("testChoices");
    previewStart_->setMenu(tests);
    previewStart_->setPopupMode(QToolButton::InstantPopup);
    connection->addWidget(previewStart_);
    connection->addSpacing(6);
    connection->addWidget(status_, 1);
    layout->addWidget(bar);

    auto *split = new QSplitter(Qt::Horizontal);
    split->setChildrenCollapsible(false);
    split->setHandleWidth(8);

    auto *left = new QFrame;
    left->setObjectName("card");
    auto *preview = new QVBoxLayout(left);
    preview->setContentsMargins(10, 10, 10, 10);
    preview->setSpacing(8);
    image_->setAlignment(Qt::AlignCenter);
    image_->setMinimumSize(220, 124);
    image_->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Ignored);
    image_->setStyleSheet("background:#fbfcfe;border:1px solid #eef1f6;border-radius:10px;color:#45546a;font-size:16px;");
    stageLabel_->setObjectName("stage");
    stageLabel_->setWordWrap(true);
    preview->addWidget(stageLabel_);
    preview->addWidget(image_, 1);
    auto *settings = new QHBoxLayout;
    settings->setSpacing(8);
    quality_->setRange(25, 90);
    quality_->setValue(65);
    confidence_->setRange(0., 1.);
    confidence_->setDecimals(2);
    confidence_->setSingleStep(.05);
    confidence_->setValue(.6);
    settings->addWidget(new QLabel("JPEG 质量"));
    settings->addWidget(quality_);
    settings->addSpacing(6);
    settings->addWidget(new QLabel("YOLO 置信度"));
    settings->addWidget(confidence_);
    settings->addWidget(apply_);
    settings->addStretch();
    preview->addLayout(settings);

    auto *right = new QFrame;
    right->setObjectName("terminal");
    auto *terminal = new QVBoxLayout(right);
    terminal->setContentsMargins(12, 10, 12, 10);
    terminal->setSpacing(0);
    auto fixed = QFontDatabase::systemFont(QFontDatabase::FixedFont);
    fixed.setPointSize(11);
    term_->setFont(fixed);
    terminal->addWidget(term_, 1);

    split->addWidget(left);
    auto *rightTabs = new QTabWidget;
    rightTabs->setObjectName("rightTabs");
    rightTabs->addTab(right, "终端");
    serialTests->addAction("模拟串口", this, [this, rightTabs] {
      rightTabs->setCurrentIndex(0);
      startSerialTest();
    });
    serialTests->addAction("实车串口 · /dev/ttyS6", this, [this, rightTabs] {
      rightTabs->setCurrentIndex(0);
      startSerialTest("/dev/ttyS6");
    });
    auto *serialPage = new QWidget;
    serialPage->setObjectName("serialPage");
    auto *serialLayout = new QVBoxLayout(serialPage);
    serialLayout->setContentsMargins(14, 14, 14, 14);
    serialLabel_->setObjectName("serialStatus");
    serialLayout->addWidget(serialLabel_);
    auto *serialFields = new QFormLayout;
    serialFields->setHorizontalSpacing(14);
    serialFields->setVerticalSpacing(8);
    serialFields->addRow("队伍", teamLabel_);
    serialFields->addRow("导航角度", angleLabel_);
    for (auto *label : {teamLabel_, angleLabel_}) {
      label->setObjectName("serialValue");
      label->setTextInteractionFlags(Qt::TextSelectableByMouse);
      label->setWordWrap(true);
    }
    serialLayout->addLayout(serialFields);
    auto *serialTools = new QHBoxLayout;
    serialDirection_->addItems({"全部", "TX", "RX"});
    serialCommand_->addItems({"全部", "01", "02", "03", "04", "05", "06"});
    serialTools->addWidget(new QLabel("方向"));
    serialTools->addWidget(serialDirection_);
    serialTools->addWidget(new QLabel("命令"));
    serialTools->addWidget(serialCommand_);
    serialTools->addStretch(1);
    serialTools->addWidget(serialClear_);
    serialLayout->addLayout(serialTools);
    connect(serialDirection_, &QComboBox::currentTextChanged, this, [this] { renderSerial(); });
    connect(serialCommand_, &QComboBox::currentTextChanged, this, [this] { renderSerial(); });
    connect(serialClear_, &QPushButton::clicked, this, [this] {
      // 只清显示和本地缓存；seq 保留，所以旧帧不会在下一次轮询又冒出来。
      serialLines_.clear();
      serialFrames_->clear();
    });
    serialFrames_->setReadOnly(true);
    serialFrames_->setLineWrapMode(QPlainTextEdit::NoWrap);
    serialFrames_->setObjectName("serialFrames");
    serialFrames_->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
    serialLayout->addWidget(serialFrames_, 1);
    rightTabs->addTab(serialPage, "串口");
    split->addWidget(rightTabs);
    split->setStretchFactor(0, 3);
    split->setStretchFactor(1, 2);
    split->setSizes({360, 220});
    layout->addWidget(split, 1);

    QSettings saved;
    const int savedMode = mode_->findText(saved.value("connection/alias", "pio").toString());
    mode_->setCurrentIndex(savedMode < 0 ? 0 : savedMode);
    if (mode_->currentText().startsWith("pio"))
      term_->setPrompt("orangepi@orangepi5plus:~$");
    term_->showNotice("未连接");
    connect(connect_, &QPushButton::clicked, this, [this] {
      if (active_) disconnectServer();
      else connectServer();
    });
    connect(&poll_, &QTimer::timeout, this, [this] { poll(); });
    connect(apply_, &QPushButton::clicked, this, [this] { apply(); });
    term_->onCommand = [this](const QString &text) { execute(text); };
    term_->onInterrupt = [this] { shell_.kill(); };
    connect(&ssh_, &QProcess::readyRead, this, [this] {
      const auto text = QString::fromUtf8(ssh_.readAll()).trimmed();
      if (!text.isEmpty()) sshError_ = text;
    });
    connect(&ssh_, &QProcess::started, this, [this] {
      updateControls();
      term_->showNotice("连接中…");
      who_.start(sshPath_, sshArgs_ + QStringList{"--", target_, "whoami; hostname"});
    });
    connect(&who_, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
      if (!active_) return;
      const auto lines = QString::fromUtf8(who_.readAll()).split('\n', Qt::SkipEmptyParts);
      if (code == 0 && lines.size() >= 2)
        term_->setPrompt(lines[0].trimmed() + "@" + lines[1].trimmed() + ":~$");
      else
        term_->setPrompt(target_);
      if (!pending_ && !serialTest_) {
        term_->reset();
        term_->showPrompt();
      }
    });
    connect(&ssh_, &QProcess::finished, this, [this](int, QProcess::ExitStatus) {
      if (active_) {
        auto reason = sshError_.isEmpty() ? QString("SSH 已断开") : sshError_;
        if (target_ == "pio") reason = "无线直连失败，可检查 SSH 配置或切换 pio-wired / pio-relay · " + reason;
        disconnectServer(reason);
      }
    });
    connect(&ssh_, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
      if (error == QProcess::FailedToStart && active_) disconnectServer(ssh_.errorString());
    });
    connect(&shell_, &QProcess::started, this, [this] {
      shellBuffer_.clear();
      shellReady_ = false;
      shell_.write("printf '\\n__GC_READY__\\n'\n");
    });
    // callback：SSH 有输出就读取。命令结束标记可能分几次到达，所以先攒到 shellBuffer_。
    connect(&shell_, &QProcess::readyRead, this, [this] {
      const auto output = shell_.readAll();
      logTerminal(output);
      shellBuffer_ += output;
      if (!shellReady_) {
        const QByteArray ready = "\n__GC_READY__";
        const int at = shellBuffer_.indexOf(ready);
        if (at < 0) return;
        const int end = shellBuffer_.indexOf('\n', at + ready.size());
        if (end < 0) return;
        shellBuffer_.remove(0, end + 1);
        shellReady_ = true;
        updateControls();
      }
      static const QByteArray marker = "\n__GC_DONE__";
      const int at = shellBuffer_.indexOf(marker);
      if (at < 0) {
        // Python 的 input() 输出提示符后等待输入，此时将终端交给测试节点。
        if (serialTest_ && pending_ && shellBuffer_.endsWith("cmd> ")) {
          shellBuffer_.chop(5);
          if (!shellBuffer_.isEmpty()) term_->writeData(QString::fromUtf8(shellBuffer_));
          shellBuffer_.clear();
          pending_ = false;
          term_->setTestPrompt(true);
          term_->finish();
          updateControls();
        }
        return;
      }
      const int end = shellBuffer_.indexOf('\n', at + marker.size());
      if (end < 0) return;
      const auto commandOutput = shellBuffer_.left(at);
      shellBuffer_.remove(0, end + 1);
      if (!pending_) return;
      pending_ = false;
      serialTest_ = false;
      term_->setTestPrompt(false);
      if (!commandOutput.isEmpty()) term_->writeData(QString::fromUtf8(commandOutput));
      term_->finish();
      updateControls();
    });
    connect(&shell_, &QProcess::finished, this, [this](int, QProcess::ExitStatus) {
      if (active_) disconnectServer("SSH 会话已断开");
    });
    updateControls();
  }

protected:
  void resizeEvent(QResizeEvent *event) override {
    QWidget::resizeEvent(event);
    showFrame();
  }

  void closeEvent(QCloseEvent *event) override {
    disconnectServer();
    shell_.kill();
    if (shell_.state() != QProcess::NotRunning) shell_.waitForFinished(500);
    if (ssh_.state() != QProcess::NotRunning) ssh_.waitForFinished(500);
    QWidget::closeEvent(event);
  }

private:
  QUrl url(const QString &path) const {
    return QUrl(QString("http://127.0.0.1:%1%2").arg(localPort_).arg(path));
  }

  void updateControls() {
    mode_->setEnabled(!active_);
    connect_->setText(active_ ? "断开" : "连接");
    previewStart_->setEnabled(shellReady_ && !pending_);
    quality_->setEnabled(online_);
    confidence_->setEnabled(online_ && hasDetector_);
    apply_->setEnabled(online_ && !setting_);
  }

  // 用当前选中的别名调用系统 OpenSSH，主机、用户名和密钥等由本机 SSH 配置决定。
  void connectServer() {
    if (ssh_.state() != QProcess::NotRunning) {
      status_->setText("正在关闭上一条 SSH 连接，请稍后再试");
      return;
    }
    sshPath_ = QStandardPaths::findExecutable("ssh");
    if (sshPath_.isEmpty()) {
      status_->setText("系统中未找到 OpenSSH 客户端");
      return;
    }
    QTcpServer local;
    if (!local.listen(QHostAddress::LocalHost)) {
      status_->setText(local.errorString());
      return;
    }
    localPort_ = local.serverPort();
    local.close();
    target_ = mode_->currentText();
    previewRequested_ = false;
    sshError_.clear();
    // 只保留最近一条连接的终端记录。收到输出就写入，排查时可以直接读取。
    const auto logDir = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
    terminalLog_.close();
    if (!logDir.isEmpty() && QDir().mkpath(logDir)) {
      terminalLog_.setFileName(logDir + "/ssh-terminal.log");
      if (terminalLog_.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        logTerminal(("SSH " + target_ + "\n").toUtf8());
      }
    }

    QSettings saved;
    saved.setValue("connection/alias", target_);
    active_ = true;
    status_->setText("正在连接 " + target_);
    updateControls();
    // 把电脑上的临时端口转发到派上的 127.0.0.1:18080。下面的 HTTP 请求只访问这个本地端口。
    ssh_.start(sshPath_, sshArgs_ + QStringList{"-o", "ExitOnForwardFailure=yes",
      "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
      "-N", "-L", QString("127.0.0.1:%1:127.0.0.1:18080").arg(localPort_),
      "--", target_});
    shellBuffer_.clear();
    pending_ = false;
    shellReady_ = false;
    shell_.start(sshPath_, sshArgs_ + QStringList{"-T", "--", target_});
    poll_.start(750);
    poll();
  }

  void disconnectServer(const QString &message = "未连接") {
    active_ = online_ = hasDetector_ = videoAvailable_ = false;
    poll_.stop();
    for (const auto &reply : {video_, statusReply_, setting_})
      if (reply) reply->abort();
    ssh_.kill();
    shell_.kill();
    who_.kill();
    pending_ = false;
    shellBuffer_.clear();
    shellReady_ = false;
    serialTest_ = false;
    serialLines_.clear();
    serialSeq_ = -1;
    serialFrames_->clear();
    frame_ = {};
    buffer_.clear();
    image_->setPixmap(QPixmap());
    image_->setText("等待画面");
    term_->setPrompt("$");
    term_->setTestPrompt(false);
    term_->showNotice("未连接");
    status_->setText(message);
    stageLabel_->setText("阶段  —");
    showSerial();
    updateControls();
  }

  // 定时请求 /status。服务响应有效才算预览服务在线，有视频时再打开 /video。
  void poll() {
    if (!active_ || statusReply_) return;
    QNetworkRequest request(url("/status"));
    request.setTransferTimeout(2500);
    auto *reply = http_.get(request);
    statusReply_ = reply;
    connect(reply, &QNetworkReply::finished, this, [this, reply] {
      statusReply_.clear();
      const auto data = QJsonDocument::fromJson(reply->readAll()).object();
      reply->deleteLater();
      if (!active_) return;
      if (reply->error() != QNetworkReply::NoError || !data.contains("jpeg_quality")) {
        online_ = videoAvailable_ = false;
        status_->setText(shellReady_ ? "等待画面服务" : "正在连接香橙派");
        stageLabel_->setText("阶段  —");
        showSerial();
        if (shellReady_ && !pending_ && !serialTest_ && !previewRequested_) runPreview("ensure-preview");
        if (video_) video_->abort();
        clearVideo();
      } else {
        if (!online_) quality_->setValue(data.value("jpeg_quality").toInt());
        const auto confidence = data.value("confidence");
        if (!hasDetector_ && confidence.isDouble()) confidence_->setValue(confidence.toDouble());
        hasDetector_ = confidence.isDouble();
        online_ = true;
        const auto stage = data.value("task").toObject().value("stage").toString("preview");
        const auto testNode = data.value("test_node").toString();
        stageLabel_->setText("阶段  " + (testNode.isEmpty() ? stage : testNode));
        showSerial(data.value("serial").toObject());
        videoAvailable_ = data.value("video_available").toBool();
        status_->setText(videoAvailable_ ? "已连接" : "已连接 · 最近 2 秒未收到新画面");
        if (videoAvailable_) {
          if (!video_) startVideo();
        } else {
          if (video_) video_->abort();
          clearVideo();
        }
      }
      if (serialTest_) stageLabel_->setText("阶段  serial_test_node");
      updateControls();
    });
  }

  void showSerial(const QJsonObject &serial = {}) {
    const bool connected = serial.value("connected").toBool();
    const bool simulated = serial.value("simulated").toBool();
    serialLabel_->setText(simulated ? "串口模拟 · 未接硬件" : connected ? "串口已连接" : "串口未连接");
    const auto team = serial.value("team").toString();
    teamLabel_->setText(connected && !team.isEmpty() ? (team == "red" ? "红方" : "蓝方") : "—");
    angleLabel_->setText(connected && serial.contains("angle_deg")
      ? QString::number(serial.value("angle_deg").toInt()) + "°" : "—");
    QStringList frames;
    for (const auto &frame : serial.value("frames").toArray()) frames.append(frame.toString());
    const qint64 seq = serial.value("seq").toInteger(-1);
    if (frames.isEmpty()) {
      serialSeq_ = -1;
      if (!serialLines_.isEmpty()) {
        serialLines_.clear();
        serialFrames_->clear();
      }
      return;
    }
    if (serialSeq_ >= 0 && seq >= serialSeq_) {
      // seq 是服务端累计帧数，两次轮询之间新来的帧一定在列表末尾。
      const int fresh = static_cast<int>(qMin<qint64>(seq - serialSeq_, frames.size()));
      serialLines_ += frames.mid(frames.size() - fresh);
    } else {
      serialLines_ = frames;
    }
    serialSeq_ = seq;
    while (serialLines_.size() > 300) serialLines_.removeFirst();
    renderSerial();
  }

  void renderSerial() {
    const QString direction = serialDirection_->currentText();
    const QString command = serialCommand_->currentText();
    QStringList shown;
    for (const auto &line : serialLines_) {
      if (direction != "全部" && !line.startsWith(direction + " ")) continue;
      if (command != "全部" && commandOf(line) != command) continue;
      shown.append(line);
    }
    auto *scroll = serialFrames_->verticalScrollBar();
    const bool atEnd = scroll->value() == scroll->maximum();
    serialFrames_->setPlainText(shown.join('\n'));
    if (atEnd) scroll->setValue(scroll->maximum());
  }

  // 帧格式：TX [SIM] AA 55 06 00 00 05，AA 55 后面第一个字节是命令位。
  static QString commandOf(const QString &line) {
    const auto parts = line.split(' ', Qt::SkipEmptyParts);
    const int at = parts.indexOf("AA");
    return at >= 0 && at + 2 < parts.size() ? parts[at + 2] : QString();
  }

  void startVideo() {
    QNetworkRequest request(url("/video"));
    request.setTransferTimeout(5000);
    auto *reply = http_.get(request);
    video_ = reply;
    buffer_.clear();
    // callback：一次收到的网络数据可能不够一张图，也可能有几张。按 Content-Length 拆包，只显示最新一张完整图。
    connect(reply, &QNetworkReply::readyRead, this, [this, reply] {
      buffer_ += reply->readAll();
      QByteArray newest;
      while (true) {
        const auto headerEnd = buffer_.indexOf("\r\n\r\n");
        if (headerEnd < 0) break;
        const auto header = buffer_.left(headerEnd);
        const auto lengthAt = header.indexOf("Content-Length: ");
        bool ok = false;
        const int length = lengthAt < 0 ? 0 : header.mid(lengthAt + 16).split('\r').first().toInt(&ok);
        const auto end = headerEnd + 4 + length;
        if (!header.startsWith("--frame\r\n") || !ok || length <= 0 || length > 2 * 1024 * 1024) {
          reply->abort();
          return;
        }
        if (buffer_.size() < end + 2) break;
        newest = buffer_.mid(headerEnd + 4, length);
        buffer_.remove(0, end + 2);
      }
      if (buffer_.size() > 2 * 1024 * 1024 + 1024) { reply->abort(); return; }
      if (!newest.isEmpty() && frame_.loadFromData(newest, "JPEG")) showFrame();
    });
    connect(reply, &QNetworkReply::finished, this, [this, reply] {
      video_.clear();
      clearVideo();
      reply->deleteLater();
    });
  }

  void apply() {
    if (!online_ || setting_) return;
    QUrlQuery fields;
    fields.addQueryItem("jpeg_quality", QString::number(quality_->value()));
    if (hasDetector_) fields.addQueryItem("confidence", QString::number(confidence_->value()));
    QNetworkRequest request(url("/settings"));
    request.setRawHeader("X-Gongchuang-Client", "qt");
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/x-www-form-urlencoded");
    request.setTransferTimeout(3000);
    auto *reply = http_.post(request, fields.toString(QUrl::FullyEncoded).toUtf8());
    setting_ = reply;
    updateControls();
    connect(reply, &QNetworkReply::finished, this, [this, reply] {
      setting_.clear();
      const auto data = QJsonDocument::fromJson(reply->readAll()).object();
      if (active_) {
        if (reply->error() == QNetworkReply::NoError) {
          quality_->setValue(data.value("jpeg_quality").toInt(quality_->value()));
          if (data.value("confidence").isDouble()) confidence_->setValue(data.value("confidence").toDouble());
          apply_->setToolTip("设置已生效");
        } else {
          apply_->setToolTip(data.value("error").toString(reply->errorString()));
        }
        QToolTip::showText(apply_->mapToGlobal(QPoint(0, apply_->height())), apply_->toolTip(), apply_);
      }
      reply->deleteLater();
      updateControls();
    });
  }

  // 远端执行完会输出 __GC_DONE__ 和退出码，收到标记后才允许输入下一条命令。
  void execute(const QString &text) {
    if (text.trimmed().isEmpty() || !active_ || !shellReady_ || shell_.state() != QProcess::Running || pending_) {
      term_->finish();
      return;
    }
    if (serialTest_) {
      pending_ = true;
      term_->waitForOutput();
      logTerminal(("cmd> " + text + "\n").toUtf8());
      shell_.write((text + "\n").toUtf8());
      updateControls();
      return;
    }
    auto remote = text;
    if (QRegularExpression("^ls(\\s|$)").match(text).hasMatch() && !text.contains("--color"))
      remote.replace(0, 2, "ls --color=always");
    term_->waitForOutput();
    pending_ = true;
    logTerminal(("$ " + text + "\n").toUtf8());
    updateControls();
    shell_.write((remote + "\nprintf '\\n__GC_DONE__%s\\n' $?\n").toUtf8());
  }

  void startSerialTest(const QString &device = {}) {
    if (!shellReady_ || pending_ || serialTest_) return;
    term_->setFocus();
    term_->waitForOutput();
    serialTest_ = pending_ = true;
    stageLabel_->setText("阶段  serial_test_node");
    updateControls();
    // 结束标记与启动命令在同一行解析，避免测试节点把它读成第一条输入。
    const auto command = QStringLiteral(
      "test_ready() { [ -x \"$1/install/tests_pkg/lib/tests_pkg/serial_test_node\" ]; }; "
      "ws=\"$HOME/my_ws/gongchuang_ros2\"; "
      "if ! test_ready \"$ws\"; then ws=\"$HOME/.local/share/gongchuang_ros2_sync\"; fi; "
      "if test_ready \"$ws\"; then bash \"$ws/tools/run.sh\" serial %1; "
      "else echo '请先在香橙派编译串口测试节点'; false; fi; "
      "printf '\\n__GC_DONE__%s\\n' $?\n").arg(device);
    shell_.write(command.toUtf8());
  }

  void runPreview(const QString &action) {
    previewRequested_ = true;
    execute(QStringLiteral(
      "if [ -x \"$HOME/.local/bin/gongchuang-preview\" ]; then "
      "bash \"$HOME/.local/bin/gongchuang-preview\" %1; "
      "else bash \"$HOME/my_ws/gongchuang_ros2/tools/preview.sh\" %1; fi").arg(action));
  }

  void logTerminal(const QByteArray &bytes) {
    if (terminalLog_.isOpen()) {
      terminalLog_.write(bytes);
      terminalLog_.flush();
    }
  }

  void clearVideo() {
    frame_ = {};
    image_->setPixmap(QPixmap());
    if (online_ && !videoAvailable_) image_->setText("无视频输入");
    else image_->setText(videoAvailable_ ? "正在重连视频" : "等待画面");
  }

  void showFrame() {
    if (!frame_.isNull())
      image_->setPixmap(QPixmap::fromImage(frame_).scaled(image_->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
  }

  QComboBox *mode_{new QComboBox};
  QSpinBox *quality_{new QSpinBox};
  QDoubleSpinBox *confidence_{new QDoubleSpinBox};
  QPushButton *connect_{new QPushButton("连接")}, *apply_{new QPushButton("应用设置")};
  QToolButton *previewStart_{new QToolButton};
  QLabel *stageLabel_{new QLabel("阶段  —")};
  QLabel *serialLabel_{new QLabel("串口未连接")};
  QLabel *teamLabel_{new QLabel("—")}, *angleLabel_{new QLabel("—")};
  QPlainTextEdit *serialFrames_{new QPlainTextEdit};
  QComboBox *serialDirection_{new QComboBox}, *serialCommand_{new QComboBox};
  QPushButton *serialClear_{new QPushButton("清除")};
  QStringList serialLines_;
  qint64 serialSeq_{-1};
  QLabel *image_{new QLabel("等待画面")}, *status_{new QLabel("未连接")};
  Terminal *term_{new Terminal};
  QNetworkAccessManager http_;
  QPointer<QNetworkReply> video_, statusReply_, setting_;
  QProcess ssh_, shell_, who_;
  QFile terminalLog_;
  QTimer poll_;
  QByteArray buffer_, shellBuffer_;
  bool pending_{false};
  bool serialTest_{false};
  bool shellReady_{false};
  bool previewRequested_{false};
  QImage frame_;
  QString target_, sshPath_, sshError_;
  const QStringList sshArgs_{"-o", "BatchMode=yes", "-o", "ConnectTimeout=5"};
  int localPort_{18080};
  bool active_{false}, online_{false}, hasDetector_{false}, videoAvailable_{false};
};

int main(int argc, char **argv) {
  QApplication app(argc, argv);
  app.setOrganizationName("Gongchuang");
  app.setApplicationName("GongchuangClient");
  app.setStyleSheet(R"(
    #root { background: #f4f6f9; }
    QFrame#card { background: #ffffff; border: 1px solid #e3e7ee; border-radius: 12px; }
    QLabel { background: transparent; color: #1f2328; }
    QLabel#caption { color: #6b7480; font-weight: 600; }
    QLabel#status { color: #404b5d; }
    QLabel#stage { background: #e6efff; color: #14346b; border: 1px solid #afc7f2;
      border-radius: 8px; padding: 7px 10px; font-size: 17px; font-weight: 700; }
    QToolButton#testMenu { background: #e6efff; color: #14346b; border: 1px solid #afc7f2;
      border-radius: 8px; padding: 6px 10px; font-size: 15px; font-weight: 600; }
    QToolButton#testMenu:hover, QToolButton#testMenu:pressed { background: #ccdefd; }
    QToolButton#testMenu:disabled { background: #eef1f6; color: #536078; }
    QToolButton#testMenu::menu-indicator { image: none; width: 0px; }
    QMenu#testChoices { background: #ffffff; color: #172334; border: 1px solid #afbdd1; font-size: 15px; }
    QMenu#testChoices::item { padding: 8px 14px; }
    QMenu#testChoices::item:selected { background: #dbe8ff; color: #14346b; }
    QTabWidget#rightTabs::pane { border: 1px solid #d1d9e6; background: #ffffff; }
    QTabBar::tab { background: #edf1f7; color: #38465d; padding: 7px 13px; font-size: 15px; }
    QTabBar::tab:selected { background: #dbe8ff; color: #14346b; font-weight: 700; }
    QWidget#serialPage { background: #ffffff; }
    QWidget#serialPage QLabel { color: #36445a; font-size: 15px; }
    QWidget#serialPage QLabel#serialStatus { color: #14346b; font-size: 18px; font-weight: 700; padding-bottom: 7px; }
    QWidget#serialPage QLabel#serialValue { color: #172334; font-size: 17px; font-weight: 700; }
    QPushButton { background: #ffffff; border: 1px solid #d7dce4; border-radius: 8px; padding: 6px 14px; color: #1f2328; }
    QPushButton:hover { border-color: #2f6fed; color: #2f6fed; }
    QPushButton:pressed { background: #eef3ff; }
    QPushButton:disabled { color: #a8b0bb; border-color: #e7eaf0; }
    QPushButton#primary { background: #2f6fed; border: 1px solid #2f6fed; color: #ffffff; font-weight: 600; }
    QPushButton#primary:hover { background: #255fd6; border-color: #255fd6; color: #ffffff; }
    QPushButton#primary:disabled { background: #c9d6f4; border-color: #c9d6f4; }
    QComboBox, QSpinBox, QDoubleSpinBox { background: #ffffff; border: 1px solid #d7dce4; border-radius: 8px; padding: 5px 8px; color: #1f2328; selection-background-color: #2f6fed; }
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2f6fed; }
    QComboBox QAbstractItemView { background: #ffffff; color: #1f2328; border: 1px solid #d7dce4; selection-background-color: #2f6fed; selection-color: #ffffff; }
    QComboBox QAbstractItemView::item { color: #1f2328; padding: 4px 8px; }
    QComboBox QAbstractItemView::item:selected { background: #2f6fed; color: #ffffff; }
    QFrame#terminal { background: #1e1e1e; border: 1px solid #2b2b2b; border-radius: 12px; }
    QPlainTextEdit#serialFrames { background: #f7f9fc; color: #18263a;
      border: 1px solid #c5d1e2; padding: 6px; font-size: 15px; }
    QPlainTextEdit#output { background: transparent; border: none; padding: 2px; color: #d4d4d4; selection-background-color: #2f6fed; }
    QSplitter::handle { background: transparent; }
    QToolTip { background: #ffffff; color: #1f2328; border: 1px solid #d7dce4; }
  )");
  Client client;
  const auto available = QGuiApplication::primaryScreen()->availableGeometry();
  client.resize(qMin(1220, int(available.width() * 0.96)), qMin(760, int(available.height() * 0.92)));
  client.show();
  return app.exec();
}

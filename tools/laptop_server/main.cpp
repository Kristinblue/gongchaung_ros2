#include <QApplication>
#include <QClipboard>
#include <QColor>
#include <QCloseEvent>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFontDatabase>
#include <QFrame>
#include <QGuiApplication>
#include <QHBoxLayout>
#include <QHostAddress>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QKeyEvent>
#include <QLabel>
#include <QNetworkAccessManager>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QPaintEvent>
#include <QPainter>
#include <QPlainTextEdit>
#include <QPointer>
#include <QProcess>
#include <QPushButton>
#include <QRegularExpression>
#include <QScreen>
#include <QSettings>
#include <QSpinBox>
#include <QSplitter>
#include <QStandardPaths>
#include <QTcpServer>
#include <QTextCharFormat>
#include <QTimer>
#include <QTextCursor>
#include <QToolTip>
#include <QUrlQuery>
#include <QVBoxLayout>
#include <functional>

// 简单的行内终端：提示符、输入、输出都在同一个文本区，支持常见 ANSI 颜色。
// 显示 SSH 远端命令的输出，并把输入的一行命令交给 Client。
class Terminal : public QPlainTextEdit {
public:
  std::function<void(const QString &)> onCommand;
  std::function<void()> onInterrupt;

  explicit Terminal(QWidget *parent = nullptr) : QPlainTextEdit(parent) {
    setReadOnly(true);
    setFrameShape(QFrame::NoFrame);
    setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    setFocusPolicy(Qt::StrongFocus);
    setCursorWidth(2);
    base_ = QTextCharFormat();
    base_.setForeground(QColor("#d4d4d4"));
    blink_.setInterval(530);
    connect(&blink_, &QTimer::timeout, this, [this] {
      blinkOn_ = !blinkOn_;
      viewport()->update();
    });
    blink_.start();
  }

  void setPrompt(const QString &text) { prompt_ = text; }
  void reset() {
    clear();
    line_.clear();
    busy_ = false;
    ready_ = false;
  }
  void showNotice(const QString &text) {
    reset();
    QTextCharFormat format;
    format.setForeground(QColor("#6b7480"));
    writeText(text, format);
  }
  void showPrompt() {
    ready_ = true;
    const int colon = prompt_.indexOf(':');
    const int dollar = prompt_.lastIndexOf('$');
    if (colon > 0 && dollar > colon) {
      writeText(prompt_.left(colon), promptFormat());
      QTextCharFormat pathFormat;
      pathFormat.setForeground(QColor("#569cd6"));
      writeText(prompt_.mid(colon, dollar - colon), pathFormat);
      writeText(prompt_.mid(dollar) + " ", base_);
    } else {
      writeText(prompt_ + " ", promptFormat());
    }
    line_.clear();
  }
  void writeData(const QString &data) { ansi(data); }
  void finish() {
    busy_ = false;
    if (!toPlainText().endsWith('\n')) writeText("\n", base_);
    showPrompt();
  }

protected:
  void paintEvent(QPaintEvent *event) override {
    QPlainTextEdit::paintEvent(event);
    if (!ready_ || !hasFocus() || !blinkOn_) return;
    QPainter painter(viewport());
    auto rect = cursorRect();
    rect.setWidth(2);
    painter.fillRect(rect, QColor("#d4d4d4"));
  }

  void focusInEvent(QFocusEvent *event) override {
    QPlainTextEdit::focusInEvent(event);
    viewport()->update();
  }

  void focusOutEvent(QFocusEvent *event) override {
    QPlainTextEdit::focusOutEvent(event);
    viewport()->update();
  }

  void mousePressEvent(QMouseEvent *event) override {
    QPlainTextEdit::mousePressEvent(event);
    auto cursor = textCursor();
    cursor.movePosition(QTextCursor::End);
    setTextCursor(cursor);
    viewport()->update();
  }

  void keyPressEvent(QKeyEvent *event) override {
    if (event->matches(QKeySequence::Copy)) {
      QPlainTextEdit::keyPressEvent(event);
      return;
    }
    if (!ready_) return;
    if (busy_) {
      if (event->key() == Qt::Key_C && (event->modifiers() & Qt::ControlModifier)) {
        if (onInterrupt) onInterrupt();
      }
      return;
    }
    if (event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter) {
      const auto command = line_;
      writeText("\n", base_);
      line_.clear();
      if (command.trimmed().isEmpty()) {
        showPrompt();
      } else if (onCommand) {
        busy_ = true;
        onCommand(command);
      }
      return;
    }
    if (event->key() == Qt::Key_Backspace) {
      if (!line_.isEmpty()) {
        line_.chop(1);
        auto cursor = textCursor();
        cursor.movePosition(QTextCursor::End);
        cursor.deletePreviousChar();
        setTextCursor(cursor);
      }
      return;
    }
    if (event->key() == Qt::Key_L && (event->modifiers() & Qt::ControlModifier)) {
      clear();
      line_.clear();
      showPrompt();
      return;
    }
    if (event->key() == Qt::Key_V && (event->modifiers() & Qt::ControlModifier)) {
      for (const QChar ch : QGuiApplication::clipboard()->text()) {
        if (ch.isPrint()) {
          writeText(QString(ch), base_);
          line_ += ch;
        }
      }
      return;
    }
    const auto text = event->text();
    if (!text.isEmpty() && text[0].isPrint()) {
      writeText(text, base_);
      line_ += text;
    }
  }

private:
  static QTextCharFormat promptFormat() {
    QTextCharFormat format;
    format.setForeground(QColor("#35c46a"));
    format.setFontWeight(QFont::DemiBold);
    return format;
  }

  void writeText(const QString &text, const QTextCharFormat &format) {
    auto cursor = textCursor();
    cursor.movePosition(QTextCursor::End);
    cursor.insertText(text, format);
    setTextCursor(cursor);
    ensureCursorVisible();
  }

  // 远端输出可能带终端颜色控制码，转换成 Qt 的文字格式再显示。
  void ansi(const QString &data) {
    QTextCharFormat format;
    format.setForeground(QColor("#d4d4d4"));
    auto cursor = textCursor();
    cursor.movePosition(QTextCursor::End);
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
    setTextCursor(cursor);
    ensureCursorVisible();
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
  QString line_;
  bool busy_{false};
  bool ready_{false};
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
    image_->setStyleSheet("background:#fbfcfe;border:1px solid #eef1f6;border-radius:10px;color:#98a1ae;");
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
    term_->setObjectName("output");
    term_->setMaximumBlockCount(2000);
    auto fixed = QFontDatabase::systemFont(QFontDatabase::FixedFont);
    fixed.setPointSize(11);
    term_->setFont(fixed);
    terminal->addWidget(term_, 1);

    split->addWidget(left);
    split->addWidget(right);
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
    connect(previewStart_, &QPushButton::clicked, this, [this] {
      execute(QStringLiteral(
        "if [ -x \"$HOME/.local/bin/gongchuang-preview\" ]; then "
        "bash \"$HOME/.local/bin/gongchuang-preview\" start; "
        "else bash \"$HOME/my_ws/gongchuang_ros2/tools/preview.sh\" start; fi"));
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
      term_->reset();
      term_->showPrompt();
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
      shellBuffer_ += shell_.readAll();
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
      if (at < 0) return;
      const int end = shellBuffer_.indexOf('\n', at + marker.size());
      if (end < 0) return;
      const auto output = shellBuffer_.left(at);
      shellBuffer_.remove(0, end + 1);
      if (!pending_) return;
      pending_ = false;
      if (!output.isEmpty()) term_->writeData(QString::fromUtf8(output));
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
    previewStart_->setEnabled(active_ && shellReady_ && !pending_ && !online_);
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
    sshError_.clear();

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
    active_ = online_ = hasDetector_ = false;
    poll_.stop();
    for (const auto &reply : {video_, statusReply_, setting_})
      if (reply) reply->abort();
    ssh_.kill();
    shell_.kill();
    who_.kill();
    pending_ = false;
    shellBuffer_.clear();
    shellReady_ = false;
    frame_ = {};
    buffer_.clear();
    image_->setPixmap(QPixmap());
    image_->setText("等待画面");
    term_->setPrompt("$");
    term_->showNotice("未连接");
    status_->setText(message);
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
        online_ = false;
        status_->setText(shellReady_ ? "等待画面服务，可点击「启动预览」" : "正在连接香橙派");
        if (video_) video_->abort();
      } else {
        if (!online_) quality_->setValue(data.value("jpeg_quality").toInt());
        const auto confidence = data.value("confidence");
        if (!hasDetector_ && confidence.isDouble()) confidence_->setValue(confidence.toDouble());
        hasDetector_ = confidence.isDouble();
        online_ = true;
        const auto stage = data.value("task").toObject().value("stage").toString("preview");
        const bool available = data.value("video_available").toBool();
        status_->setText("已连接 · 阶段：" + stage);
        if (available) {
          if (!video_) startVideo();
        } else {
          if (video_) video_->abort();
          clearVideo();
        }
      }
      updateControls();
    });
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
    if (text.trimmed().isEmpty() || !active_ || shell_.state() != QProcess::Running || pending_) {
      term_->finish();
      return;
    }
    auto remote = text;
    if (QRegularExpression("^ls(\\s|$)").match(text).hasMatch() && !text.contains("--color"))
      remote.replace(0, 2, "ls --color=always");
    pending_ = true;
    updateControls();
    shell_.write((remote + "\nprintf '\\n__GC_DONE__%s\\n' $?\n").toUtf8());
  }

  void clearVideo() {
    frame_ = {};
    image_->setPixmap(QPixmap());
    image_->setText(online_ ? "无视频输入" : "等待画面");
  }

  void showFrame() {
    if (!frame_.isNull())
      image_->setPixmap(QPixmap::fromImage(frame_).scaled(image_->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
  }

  QComboBox *mode_{new QComboBox};
  QSpinBox *quality_{new QSpinBox};
  QDoubleSpinBox *confidence_{new QDoubleSpinBox};
  QPushButton *connect_{new QPushButton("连接")}, *apply_{new QPushButton("应用设置")};
  QPushButton *previewStart_{new QPushButton("启动预览")};
  QLabel *image_{new QLabel("等待画面")}, *status_{new QLabel("未连接")};
  Terminal *term_{new Terminal};
  QNetworkAccessManager http_;
  QPointer<QNetworkReply> video_, statusReply_, setting_;
  QProcess ssh_, shell_, who_;
  QTimer poll_;
  QByteArray buffer_, shellBuffer_;
  bool pending_{false};
  bool shellReady_{false};
  QImage frame_;
  QString target_, sshPath_, sshError_;
  const QStringList sshArgs_{"-o", "BatchMode=yes", "-o", "ConnectTimeout=5"};
  int localPort_{18080};
  bool active_{false}, online_{false}, hasDetector_{false};
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
    QLabel#status { color: #5a6472; }
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

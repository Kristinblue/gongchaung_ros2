#include <QApplication>
#include <QCloseEvent>
#include <QComboBox>
#include <QDesktopServices>
#include <QDoubleSpinBox>
#include <QFontDatabase>
#include <QHostAddress>
#include <QHBoxLayout>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QNetworkAccessManager>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QPlainTextEdit>
#include <QPointer>
#include <QProcess>
#include <QPushButton>
#include <QRegularExpression>
#include <QSettings>
#include <QSpinBox>
#include <QStandardPaths>
#include <QTabWidget>
#include <QTcpServer>
#include <QTimer>
#include <QTextCursor>
#include <QToolTip>
#include <QUrlQuery>
#include <QVBoxLayout>
#include <utility>

class Client : public QWidget {
public:
  Client() {
    setWindowTitle("工创赛客户端");
    resize(940, 690);
    http_.setProxy(QNetworkProxy::NoProxy);
    ssh_.setProcessChannelMode(QProcess::MergedChannels);
    command_.setProcessChannelMode(QProcess::MergedChannels);

    auto *layout = new QVBoxLayout(this);
    auto *connection = new QHBoxLayout;
    mode_->addItems({"本地预览", "有线 SSH", "阿里云中转"});
    connection->addWidget(mode_);
    connection->addWidget(host_, 1);
    port_->setRange(1, 65535);
    port_->setValue(18080);
    connection->addWidget(new QLabel("服务端口"));
    connection->addWidget(port_);
    connection->addWidget(connect_);
    layout->addLayout(connection);
    layout->addWidget(status_);

    auto *tabs = new QTabWidget;
    layout->addWidget(tabs, 1);
    auto *video = new QWidget;
    auto *preview = new QVBoxLayout(video);
    image_->setAlignment(Qt::AlignCenter);
    image_->setMinimumSize(320, 180);
    image_->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Ignored);
    image_->setStyleSheet("background:#141920;color:#d5dde7");
    preview->addWidget(image_, 1);
    auto *settings = new QHBoxLayout;
    quality_->setRange(25, 90);
    quality_->setValue(65);
    confidence_->setRange(0., 1.);
    confidence_->setDecimals(2);
    confidence_->setSingleStep(.05);
    confidence_->setValue(.6);
    settings->addWidget(new QLabel("JPEG 质量"));
    settings->addWidget(quality_);
    settings->addWidget(new QLabel("YOLO 置信度"));
    settings->addWidget(confidence_);
    settings->addWidget(apply_);
    settings->addStretch();
    settings->addWidget(browser_);
    preview->addLayout(settings);
    tabs->addTab(video, "预览与设置");

    auto *shell = new QWidget;
    auto *shellLayout = new QVBoxLayout(shell);
    output_->setReadOnly(true);
    output_->setMaximumBlockCount(1000);
    output_->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
    shellLayout->addWidget(output_);
    auto *line = new QHBoxLayout;
    input_->setPlaceholderText("输入香橙派上的命令");
    line->addWidget(input_, 1);
    line->addWidget(execute_);
    line->addWidget(cancel_);
    shellLayout->addLayout(line);
    tabs->addTab(shell, "SSH 命令");

    QSettings saved;
    mode_->setCurrentIndex(saved.value("mode", 0).toInt());
    port_->setValue(saved.value("port", 18080).toInt());
    setHost();
    connect(mode_, &QComboBox::currentIndexChanged, this, [this] { setHost(); });
    connect(connect_, &QPushButton::clicked, this, [this] {
      if (active_) disconnectServer();
      else connectServer();
    });
    connect(&poll_, &QTimer::timeout, this, [this] { poll(); });
    connect(apply_, &QPushButton::clicked, this, [this] { apply(); });
    connect(browser_, &QPushButton::clicked, this, [this] { QDesktopServices::openUrl(url("/")); });
    connect(&ssh_, &QProcess::readyRead, this, [this] {
      const auto text = QString::fromUtf8(ssh_.readAll()).trimmed();
      if (!text.isEmpty()) sshError_ = text;
    });
    connect(&ssh_, &QProcess::started, this, [this] { updateControls(); });
    connect(&ssh_, &QProcess::finished, this, [this](int, QProcess::ExitStatus) {
      if (active_) disconnectServer(sshError_.isEmpty() ? "SSH 已断开" : sshError_);
    });
    connect(&ssh_, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
      if (error == QProcess::FailedToStart && active_) disconnectServer(ssh_.errorString());
    });
    connect(execute_, &QPushButton::clicked, this, [this] { execute(); });
    connect(input_, &QLineEdit::returnPressed, this, [this] { execute(); });
    connect(cancel_, &QPushButton::clicked, &command_, &QProcess::kill);
    connect(&command_, &QProcess::readyRead, this, [this] {
      output_->moveCursor(QTextCursor::End);
      output_->insertPlainText(QString::fromUtf8(command_.readAll()));
    });
    connect(&command_, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
      output_->appendPlainText(QString("退出码 %1").arg(code));
      updateControls();
    });
    connect(&command_, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
      if (error == QProcess::FailedToStart) {
        output_->appendPlainText(command_.errorString());
        updateControls();
      }
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
    command_.kill();
    if (command_.state() != QProcess::NotRunning) command_.waitForFinished(500);
    if (ssh_.state() != QProcess::NotRunning) ssh_.waitForFinished(500);
    QWidget::closeEvent(event);
  }

private:
  QUrl url(const QString &path) const {
    return QUrl(QString("http://127.0.0.1:%1%2").arg(localPort_).arg(path));
  }

  void setHost() {
    if (!mode_->currentIndex()) host_->setText("localhost");
    else {
      QSettings saved;
      host_->setText(saved.value(QString("ssh/%1").arg(mode_->currentIndex()),
        mode_->currentIndex() == 1 ? "pio" : "pio-relay").toString());
    }
    updateControls();
  }

  void updateControls() {
    mode_->setEnabled(!active_);
    host_->setEnabled(!active_ && mode_->currentIndex());
    port_->setEnabled(!active_);
    connect_->setText(active_ ? "断开" : "连接");
    browser_->setEnabled(online_);
    quality_->setEnabled(online_);
    confidence_->setEnabled(online_ && hasDetector_);
    apply_->setEnabled(online_ && !setting_);
    const bool remote = active_ && mode_->currentIndex() && ssh_.state() == QProcess::Running;
    execute_->setEnabled(remote && command_.state() == QProcess::NotRunning);
    input_->setEnabled(remote);
    cancel_->setEnabled(command_.state() != QProcess::NotRunning);
  }

  void connectServer() {
    target_ = host_->text().trimmed();
    localPort_ = port_->value();
    const int mode = mode_->currentIndex();
    if (mode) {
      static const QRegularExpression destination("^(?:[A-Za-z0-9_.-]+@)?[A-Za-z0-9][A-Za-z0-9_.-]*$");
      if (!destination.match(target_).hasMatch()) {
        status_->setText("请输入 SSH 别名或 用户@地址");
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
      sshError_.clear();
      ssh_.start(sshPath_, {"-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
        "-N", "-L", QString("127.0.0.1:%1:127.0.0.1:%2").arg(localPort_).arg(port_->value()),
        "--", target_});
    }
    QSettings saved;
    saved.setValue("mode", mode);
    saved.setValue("port", port_->value());
    if (mode) saved.setValue(QString("ssh/%1").arg(mode), target_);
    active_ = true;
    status_->setText("正在连接");
    updateControls();
    poll_.start(750);
    poll();
  }

  void disconnectServer(const QString &message = "未连接") {
    active_ = online_ = hasDetector_ = false;
    poll_.stop();
    for (const auto &reply : {video_, statusReply_, setting_})
      if (reply) reply->abort();
    ssh_.kill();
    command_.kill();
    frame_ = {};
    buffer_.clear();
    image_->setPixmap(QPixmap());
    image_->setText("等待画面");
    status_->setText(message);
    updateControls();
  }

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
        status_->setText("等待 HTTP 服务");
        if (video_) video_->abort();
      } else {
        if (!online_) quality_->setValue(data.value("jpeg_quality").toInt());
        const auto confidence = data.value("confidence");
        if (!hasDetector_ && confidence.isDouble()) confidence_->setValue(confidence.toDouble());
        hasDetector_ = confidence.isDouble();
        online_ = true;
        const auto stage = data.value("task").toObject().value("stage").toString("preview");
        status_->setText("已连接 · 阶段：" + stage + (frame_.isNull() ? " · 等待图像" : ""));
        if (!video_) startVideo();
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
      frame_ = {};
      image_->setPixmap(QPixmap());
      image_->setText("等待画面");
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

  void execute() {
    const auto text = input_->text().trimmed();
    if (text.isEmpty() || !execute_->isEnabled()) return;
    output_->appendPlainText("$ " + text);
    command_.start(sshPath_, {"-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "--", target_, text});
    updateControls();
  }

  void showFrame() {
    if (!frame_.isNull())
      image_->setPixmap(QPixmap::fromImage(frame_).scaled(image_->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
  }

  QComboBox *mode_{new QComboBox};
  QLineEdit *host_{new QLineEdit}, *input_{new QLineEdit};
  QSpinBox *port_{new QSpinBox}, *quality_{new QSpinBox};
  QDoubleSpinBox *confidence_{new QDoubleSpinBox};
  QPushButton *connect_{new QPushButton("连接")}, *apply_{new QPushButton("应用设置")},
    *browser_{new QPushButton("浏览器摄像头")}, *execute_{new QPushButton("执行")}, *cancel_{new QPushButton("关闭命令连接")};
  QLabel *image_{new QLabel("等待画面")}, *status_{new QLabel("未连接")};
  QPlainTextEdit *output_{new QPlainTextEdit};
  QNetworkAccessManager http_;
  QPointer<QNetworkReply> video_, statusReply_, setting_;
  QProcess ssh_, command_;
  QTimer poll_;
  QByteArray buffer_;
  QImage frame_;
  QString target_, sshPath_, sshError_;
  int localPort_{18080};
  bool active_{false}, online_{false}, hasDetector_{false};
};

int main(int argc, char **argv) {
  QApplication app(argc, argv);
  app.setOrganizationName("Gongchuang");
  app.setApplicationName("GongchuangClient");
  Client client;
  client.show();
  return app.exec();
}

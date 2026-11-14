# 项目说明
这是2027工创赛的代码仓库，这里只包含上位机部分
当前使用电脑的摄像头做验证，整个项目未开发完，从前一阶段纯python代码迁移过来的。

## 环境说明
- 香橙派系统：Ubuntu Jammy ARM64 / ROS 2 Humble
- 电脑：Windows + WSL2 Ubuntu 22.04 / ROS 2 Humble
- 语言：主要是c++

## 整体文件夹说明
```text
.
├─ src/       四个 ROS 2 功能包
├─ tools/     编译、启动、实验、日志和迁移前源码
├─ build/     本地编译中间文件
├─ install/   本地编译结果
├─ README.md
└─ AGENTS.md
```
### 源码
四个功能包，具体见[源码里的 README](src/README.md)。
### 电脑客户端
qt框架做的，在这里面可以看到画面，更改一些值，显示代码的执行阶段，其他功能后续再加


虽然我已经有了好几种连接方式，有线无线都有，应该不会出问题，但还是保底的下位机加单独香橙派就能完成整个任务，电脑能控制是最好的，

### 日志
在 `tools/logs/` 按照日期记录改动等。
### 实验
对比一些方法，得到更高效率
- 找安全区的方法
-

## 使用说明

从仓库根目录执行 `bash tools/build.sh` 和 `bash tools/run.sh`，在 Windows 打开 [本地预览](http://localhost:18080)。依赖安装、手机摄像头和香橙派启动见[源码说明](src/README.md)。

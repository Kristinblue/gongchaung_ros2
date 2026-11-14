"""封装的非阻塞类，借此再学习下多线程：一个是锁，另一个是事件，之前都是用布尔变量维护开启与否
摄像头后台采集，把采集到的放入一个线程中，主程序中取出
这样就不会等取出一帧后才能处理

只保留最新帧缓存，取完清除
不过可能会有个忙等待的问题，就是最新帧已经被处理完，读取线程还没读到，主循环可以在none的时候加一点延时

"""

import threading


class Camera:
    """
    把opencv的videoCapture再封装一下
   
    内部自己一直读，_capture，构造对象后这个线程就一直循环，除非报错
    外部取latest，并且拿到的永远是最新的，且，只会！处！理！一！次！如果没有新的到来，返回none，所以主程序要做好非空准备

    """

    def __init__(self, cap):
        """接管摄像头并启动采集线程。
        Args:
            cap: 已打开并完成参数设置的 cv2.VideoCapture。
        """
        if not cap.isOpened():
            cap.release()
            raise RuntimeError("[Camera]摄像头打开失败")
        self._cap =cap
        self._frame = None
        #线程相关
        self._lock = threading.Lock()
        self._stop = threading.Event() #停止采集信号，true的时候表示需要停止
        self._thread = threading.Thread(target = self._capture , name = "Camera",daemon = True)
        # 守护。保证正常退出的时候能关闭资源，发生异常也能
        self._thread.start()

    def _capture(self):
        """
        一直读，读一次缓存一次
        """
        try :
            while not self._stop.is_set() :
                ret , frame = self._cap.read()
                if not ret or frame is None:
                    print("[Camera]采集画面失败，采集已停止")
                    break

                #加锁存帧
                with self._lock :
                    self._frame = frame
        except Exception as e :
            print(f"[Camerea] 采集异常:{e}")
        finally:
            #采集线程退出
            self._stop.set()
            with self._lock:
                self._frame = None
            self._cap.release()

    def latest(self):
        """非阻塞获取一张新帧，不复制像素。

        Returns:
            frame: 新的缓存
        """
        # 加锁取帧
        with self._lock:
            if self._stop.is_set():
                print("[Camera]已关闭")
                return None
            frame = self._frame
            # 取完就清除缓存，原因在开头
            self._frame = None
            return frame


    def close(self, timeout=2.0):
        """主程序调用，发送停止请求
        通知线程退出，等待线程自行释放摄像头。

        Args:
            timeout: 等待秒数，默认 2 秒。

        Raises:
            RuntimeError: 驱动仍阻塞在读帧，未能按时关闭。
        """
        self._stop.set() 
        self._thread.join(timeout)#让主线程等待采集线程结束包括finally里面的释放资源
        # 再检查下线程是否结束
        if self._thread.is_alive():
            raise RuntimeError("[Camera]读取线程关闭超时")

"""主程序入口。"""
from src.application.task_controller import Task
from src.application.display import draw_frame
from src.application.my_cmd import MyCMD
from utils.usb_camera import Camera
from utils.my_ui import MyUI
import cv2
import time

# 常量
WIDTH = 1280
HEIGHT = 720
FPS = 60
FOURCC = "MJPG"
TIME_DEBUG = False


def main() -> None:
    """打开摄像头，循环处理每一帧。"""

    cap = cv2.VideoCapture(0)
    # 参数直接使用 OpenCV 设置，可按实际摄像头删改。
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cam = None
    task = None
    cmd = None
    ui = None

    try:
        if not cap.isOpened():
            raise RuntimeError("USB 摄像头打开失败")

        cam = Camera(cap)
        cmd = MyCMD()
        task = Task(int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), cmd, time_debug=TIME_DEBUG)
        ui = MyUI(fullscreen=True)
        ui.add_button("退出",ui.quit,rect=(1020,20,120,50))
        ui.add_shortcut("Esc",ui.quit)

        while ui.is_running():
            ui.process_events()
            if not ui.is_running():
                break
            img = cam.latest()
            if img is None:
                task.process_frame(None)
                time.sleep(0.002)
                continue

            task.process_frame(img)
            ui.show(draw_frame(img,task))

    except KeyboardInterrupt:
        print("[Main] 收到退出请求")
    finally:
        try:
            if task is not None:
                task.close()
            elif cmd is not None:
                cmd.close()
        finally:
            try:
                if cam is not None:
                    cam.close()
                else:
                    cap.release()
            finally:
                if ui is not None:
                    ui.close()


if __name__ == "__main__":
    import argparse

    argparse.ArgumentParser(description="香橙派摄像头算法入口").parse_args()
    main()

# code：动作类型，使用下面定义的具名常量
# value：动作参数，不同命令的单位不同
# STRAIGHT、TURN 为像素误差
# TURN_ANGLE、CAMERA 为角度
# STRAIGHT_DIS 为厘米
uint8 code
int16 value #最大32767

# 动作命令位的取值，和 communication_pkg/my_cmd.py 对应。
# 这些是消息常量，只参与编译，不会进串口帧，下位机协议不变。最终发送的1是规定的字节流
uint8 GET_FLAG=0
uint8 STRAIGHT=1
uint8 TURN=2
uint8 GRAB=3
uint8 CAMERA=4
uint8 TURN_ANGLE=5
uint8 ANGLE_CALIB=6
uint8 STRAIGHT_DIS=7
uint8 STOP=8

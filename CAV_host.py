import os
import sys
import subprocess
import socket
import time
import cv2
import numpy as np
import mss
import mss.windows
from threading import Thread, Event, Lock
import ctypes

ctypes.windll.user32.SetProcessDPIAware()

class CAVHost:
    def __init__(self):
        self.resolutions = {
            1: (256, 144),
            2: (320, 180),
            3: (416, 234),
            4: (640, 360)
        }
        self.qualities = {
            1: 95,
            2: 85,
            3: 70,
            4: 50
        }
        self.selected_res = (320, 180)
        self.selected_quality = 85
        self.selected_fps = 30
        
        self.running = False
        self.stop_event = Event()
        self.frame_count = 0
        self.start_time = 0
        self.fps_lock = Lock()
        self.current_fps = 0
        self.current_bandwidth = 0
        self.data_sent = 0
        
        self.tcp_socket = None
        self.client_socket = None
        self.encode_param = None
        
    def check_adb_installed(self):
        try:
            result = subprocess.run(['adb', 'version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                print("[✓] ADB 已安装")
                return True
            else:
                print("[✗] ADB 未安装，请先安装 Android SDK")
                return False
        except FileNotFoundError:
            print("[✗] ADB 未安装或未添加到环境变量")
            return False
        except subprocess.TimeoutExpired:
            print("[✗] ADB 超时，请检查 ADB 安装")
            return False
    
    def check_device_connected(self):
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().split('\n')
            devices = [line.split('\t')[0] for line in lines if '\tdevice' in line]
            if devices:
                print(f"[✓] 检测到设备: {', '.join(devices)}")
                return True
            else:
                print("[✗] 未检测到连接的设备，请确保手机已开启 USB 调试并连接")
                return False
        except Exception as e:
            print(f"[✗] 检测设备失败: {str(e)}")
            return False
    
    def setup_adb_forward(self):
        try:
            subprocess.run(['adb', 'forward', '--remove', 'tcp:6000'], capture_output=True, timeout=3)
            result = subprocess.run(['adb', 'forward', 'tcp:6000', 'tcp:6000'], capture_output=True, timeout=5)
            if result.returncode == 0:
                print("[✓] ADB 端口转发已设置 (tcp:6000)")
                return True
            else:
                print("[✗] ADB 端口转发设置失败")
                return False
        except Exception as e:
            print(f"[✗] 设置端口转发失败: {str(e)}")
            return False
    
    def get_device_info(self):
        try:
            result = subprocess.run(['adb', 'shell', 'getprop', 'ro.product.model'], capture_output=True, text=True, timeout=3)
            model = result.stdout.strip()
            result = subprocess.run(['adb', 'shell', 'getprop', 'ro.build.version.release'], capture_output=True, text=True, timeout=3)
            version = result.stdout.strip()
            print(f"[✓] 设备型号: {model}")
            print(f"[✓] Android 版本: {version}")
        except Exception as e:
            print(f"[!] 获取设备信息失败: {str(e)}")
    
    def show_menu(self):
        print("\n" + "="*50)
        print("           CAV 主机端 - 低延迟屏幕转发")
        print("="*50)
        print(f" 当前配置:")
        print(f"   分辨率: {self.selected_res[0]}x{self.selected_res[1]}")
        print(f"   JPEG 画质: {self.selected_quality}%")
        print(f"   帧率: {self.selected_fps} FPS")
        print("\n 菜单选项:")
        print(" 1. 设置分辨率")
        print(" 2. 设置 JPEG 画质")
        print(" 3. 设置帧率")
        print(" 4. 开始转发")
        print(" 5. 退出")
        print("="*50)
        
    def select_resolution(self):
        print("\n 选择分辨率:")
        print(" 1. 256x144")
        print(" 2. 320x180")
        print(" 3. 416x234")
        print(" 4. 640x360")
        try:
            choice = int(input(" 请输入选项 (1-4): "))
            if choice in self.resolutions:
                self.selected_res = self.resolutions[choice]
                print(f" [✓] 分辨率已设置为 {self.selected_res[0]}x{self.selected_res[1]}")
            else:
                print(" [✗] 无效选项")
        except ValueError:
            print(" [✗] 请输入有效数字")
    
    def select_quality(self):
        print("\n 选择 JPEG 画质:")
        print(" 1. 95% (高质量)")
        print(" 2. 85% (平衡)")
        print(" 3. 70% (中等)")
        print(" 4. 50% (低质量)")
        try:
            choice = int(input(" 请输入选项 (1-4): "))
            if choice in self.qualities:
                self.selected_quality = self.qualities[choice]
                print(f" [✓] JPEG 画质已设置为 {self.selected_quality}%")
            else:
                print(" [✗] 无效选项")
        except ValueError:
            print(" [✗] 请输入有效数字")
    
    def select_fps(self):
        try:
            fps = int(input("\n 请输入帧率 (1-500): "))
            if 1 <= fps <= 500:
                self.selected_fps = fps
                print(f" [✓] 帧率已设置为 {self.selected_fps} FPS")
            else:
                print(" [✗] 帧率必须在 1-500 之间")
        except ValueError:
            print(" [✗] 请输入有效数字")
    
    def fps_counter(self):
        while not self.stop_event.is_set():
            time.sleep(1)
            with self.fps_lock:
                elapsed = time.time() - self.start_time if self.start_time > 0 else 1
                self.current_fps = self.frame_count / elapsed
                self.current_bandwidth = self.data_sent / (1024 * 1024)
                self.frame_count = 0
                self.data_sent = 0
                self.start_time = time.time()
    
    def capture_and_send(self):
        frame_interval = 1.0 / self.selected_fps
        self.encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.selected_quality]
        
        last_time = time.perf_counter()
        accumulated_sleep = 0.0
        
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            sct.compression_level = 0
            
            while not self.stop_event.is_set():
                current_time = time.perf_counter()
                elapsed = current_time - last_time
                
                if elapsed >= frame_interval:
                    last_time = current_time
                    
                    try:
                        sct_img = sct.grab(monitor)
                        
                        frame = np.frombuffer(sct_img.rgb, dtype=np.uint8)
                        frame = frame.reshape((sct_img.height, sct_img.width, 3))
                        
                        frame = cv2.resize(frame, self.selected_res, interpolation=cv2.INTER_NEAREST)
                        
                        _, jpeg_data = cv2.imencode('.jpg', frame, self.encode_param)
                        
                        data_size = len(jpeg_data)
                        header = data_size.to_bytes(4, byteorder='big')
                        
                        if self.client_socket:
                            try:
                                self.client_socket.sendall(header + jpeg_data)
                                with self.fps_lock:
                                    self.frame_count += 1
                                    self.data_sent += data_size
                            except Exception:
                                self.client_socket = None
                                break
                                
                    except Exception as e:
                        pass
                    
                    current_time = time.perf_counter()
                    processing_time = current_time - last_time
                    sleep_time = frame_interval - processing_time - accumulated_sleep
                    
                    if sleep_time > 0.0001:
                        time.sleep(sleep_time)
                        accumulated_sleep = 0
                    else:
                        accumulated_sleep += processing_time - frame_interval
    
    def run_tcp_server(self):
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.tcp_socket.settimeout(0.5)
        
        try:
            self.tcp_socket.bind(('127.0.0.1', 6000))
            self.tcp_socket.listen(1)
            print("[✓] TCP 服务器已启动，监听端口 6000")
            
            while not self.stop_event.is_set():
                try:
                    self.client_socket, addr = self.tcp_socket.accept()
                    self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
                    self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
                    print(f" [✓] 手机端已连接: {addr}")
                    
                    if not self.running:
                        self.running = True
                        self.start_time = time.time()
                        capture_thread = Thread(target=self.capture_and_send)
                        capture_thread.daemon = True
                        capture_thread.start()
                        
                except socket.timeout:
                    continue
                except Exception as e:
                    if not self.stop_event.is_set():
                        print(f" [✗] TCP 错误: {str(e)}")
                        
        except Exception as e:
            print(f" [✗] 启动 TCP 服务器失败: {str(e)}")
    
    def start_forwarding(self):
        print("\n[*] 正在启动屏幕转发...")
        
        if not self.check_adb_installed():
            return
        
        if not self.check_device_connected():
            return
        
        if not self.setup_adb_forward():
            return
        
        self.get_device_info()
        
        self.stop_event.clear()
        self.frame_count = 0
        self.data_sent = 0
        self.current_fps = 0
        self.current_bandwidth = 0
        
        fps_thread = Thread(target=self.fps_counter)
        fps_thread.daemon = True
        fps_thread.start()
        
        server_thread = Thread(target=self.run_tcp_server)
        server_thread.daemon = True
        server_thread.start()
        
        print("\n[✓] 转发已启动，按 Ctrl+C 停止")
        print("-"*50)
        
        try:
            while True:
                time.sleep(0.5)
                with self.fps_lock:
                    if self.current_fps > 0:
                        print(f"\r 实时帧率: {self.current_fps:.1f} FPS | 带宽: {self.current_bandwidth:.2f} MB/s", end='')
        except KeyboardInterrupt:
            print("\n\n[*] 正在停止转发...")
            self.stop_event.set()
            time.sleep(0.2)
            
            if self.client_socket:
                try:
                    self.client_socket.shutdown(socket.SHUT_RDWR)
                    self.client_socket.close()
                except:
                    pass
                self.client_socket = None
            if self.tcp_socket:
                try:
                    self.tcp_socket.close()
                except:
                    pass
                self.tcp_socket = None
                
            print("[✓] 转发已停止")
    
    def main(self):
        print("="*50)
        print("        CAV - 低延迟屏幕转发系统 (主机端)")
        print("="*50)
        print(" 原理: 主机捕获屏幕 -> JPEG压缩 -> TCP发送 -> ADB转发")
        print(" 主机不直接连接网络，所有流量通过 USB")
        print("="*50)
        
        while True:
            self.show_menu()
            try:
                choice = int(input(" 请输入选项 (1-5): "))
                
                if choice == 1:
                    self.select_resolution()
                elif choice == 2:
                    self.select_quality()
                elif choice == 3:
                    self.select_fps()
                elif choice == 4:
                    self.start_forwarding()
                elif choice == 5:
                    print(" [✓] 退出程序")
                    break
                else:
                    print(" [✗] 无效选项，请输入 1-5")
            except ValueError:
                print(" [✗] 请输入有效数字")
            except KeyboardInterrupt:
                print("\n [✓] 退出程序")
                break

if __name__ == "__main__":
    try:
        host = CAVHost()
        host.main()
    except Exception as e:
        print(f"\n[✗] 程序异常退出: {str(e)}")
        sys.exit(1)
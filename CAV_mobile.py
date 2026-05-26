import socket
import select
import threading
import time
import struct
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.uix.image import Image
from kivy.core.window import Window
from kivy.config import Config

Config.set('graphics', 'fullscreen', 'auto')
Config.set('graphics', 'show_cursor', 'false')

class CAVMobileApp(App):
    def build(self):
        self.title = 'CAV'
        self.tcp_socket = None
        self.udp_socket = None
        self.client_socket = None
        self.running = False
        self.stop_event = threading.Event()
        
        self.frame_count = 0
        self.start_time = 0
        self.current_fps = 0
        self.current_bandwidth = 0
        self.data_received = 0
        
        self.target_ip = '192.168.1.100'
        self.target_port = 6001
        
        self.buffer = b''
        self.expected_size = None
        self.last_frame_time = 0
        
        self.layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        
        self.image_widget = Image(size_hint=(1, 0.7))
        self.layout.add_widget(self.image_widget)
        
        status_layout = BoxLayout(orientation='horizontal', size_hint=(1, 0.1))
        self.status_label = Label(text='状态: 停止', color=(1, 0, 0, 1))
        self.fps_label = Label(text='帧率: 0 FPS')
        self.bandwidth_label = Label(text='带宽: 0 MB/s')
        status_layout.add_widget(self.status_label)
        status_layout.add_widget(self.fps_label)
        status_layout.add_widget(self.bandwidth_label)
        self.layout.add_widget(status_layout)
        
        input_layout = BoxLayout(orientation='horizontal', size_hint=(1, 0.1), spacing=5)
        self.ip_input = TextInput(text=self.target_ip, hint_text='目标 IP', size_hint=(0.5, 1))
        self.port_input = TextInput(text=str(self.target_port), hint_text='端口', size_hint=(0.3, 1))
        input_layout.add_widget(self.ip_input)
        input_layout.add_widget(self.port_input)
        self.layout.add_widget(input_layout)
        
        button_layout = BoxLayout(orientation='horizontal', size_hint=(1, 0.1), spacing=10)
        self.start_button = Button(text='开始转发', on_press=self.start_forwarding)
        self.stop_button = Button(text='停止转发', on_press=self.stop_forwarding, disabled=True)
        button_layout.add_widget(self.start_button)
        button_layout.add_widget(self.stop_button)
        self.layout.add_widget(button_layout)
        
        Clock.schedule_interval(self.update_ui, 0.5)
        
        return self.layout
    
    def update_ui(self, dt):
        if self.running:
            elapsed = time.time() - self.start_time if self.start_time > 0 else 1
            self.current_fps = self.frame_count / elapsed
            self.current_bandwidth = self.data_received / (1024 * 1024)
            self.fps_label.text = f'帧率: {self.current_fps:.1f} FPS'
            self.bandwidth_label.text = f'带宽: {self.current_bandwidth:.2f} MB/s'
            self.frame_count = 0
            self.data_received = 0
            self.start_time = time.time()
    
    def start_forwarding(self, instance):
        try:
            self.target_ip = self.ip_input.text.strip()
            self.target_port = int(self.port_input.text.strip())
            
            if not self.validate_ip(self.target_ip):
                self.status_label.text = '错误: 无效 IP 地址'
                self.status_label.color = (1, 0, 0, 1)
                return
            
            if not (1 <= self.target_port <= 65535):
                self.status_label.text = '错误: 端口必须在 1-65535 之间'
                self.status_label.color = (1, 0, 0, 1)
                return
            
            self.running = True
            self.stop_event.clear()
            self.frame_count = 0
            self.data_received = 0
            self.start_time = time.time()
            self.buffer = b''
            self.expected_size = None
            
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.tcp_socket.settimeout(1.0)
            
            try:
                self.tcp_socket.bind(('0.0.0.0', 6000))
                self.tcp_socket.listen(1)
            except Exception as e:
                self.status_label.text = f'错误: 绑定端口失败 {str(e)}'
                self.status_label.color = (1, 0, 0, 1)
                return
            
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            
            thread = threading.Thread(target=self.tcp_listener)
            thread.daemon = True
            thread.start()
            
            self.start_button.disabled = True
            self.stop_button.disabled = False
            self.status_label.text = '状态: 运行中'
            self.status_label.color = (0, 1, 0, 1)
            
        except ValueError:
            self.status_label.text = '错误: 端口必须是数字'
            self.status_label.color = (1, 0, 0, 1)
        except Exception as e:
            self.status_label.text = f'错误: {str(e)}'
            self.status_label.color = (1, 0, 0, 1)
    
    def stop_forwarding(self, instance):
        self.running = False
        self.stop_event.set()
        
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
        
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass
            self.udp_socket = None
        
        self.start_button.disabled = False
        self.stop_button.disabled = True
        self.status_label.text = '状态: 停止'
        self.status_label.color = (1, 0, 0, 1)
        self.fps_label.text = '帧率: 0 FPS'
        self.bandwidth_label.text = '带宽: 0 MB/s'
    
    def validate_ip(self, ip):
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            if not part.isdigit():
                return False
            if not 0 <= int(part) <= 255:
                return False
        return True
    
    def tcp_listener(self):
        while self.running and not self.stop_event.is_set():
            try:
                self.client_socket, addr = self.tcp_socket.accept()
                self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
                self.client_socket.setblocking(False)
                
                thread = threading.Thread(target=self.handle_client)
                thread.daemon = True
                thread.start()
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.status_label.text = f'错误: {str(e)}'
                    self.status_label.color = (1, 0, 0, 1)
                break
    
    def handle_client(self):
        buffer = b''
        
        while self.running and not self.stop_event.is_set():
            try:
                ready, _, _ = select.select([self.client_socket], [], [], 0.005)
                
                if ready:
                    data = self.client_socket.recv(16384)
                    if not data:
                        break
                    
                    buffer += data
                    
                    while len(buffer) >= 4:
                        if len(buffer) >= 4:
                            expected_size = struct.unpack('!I', buffer[:4])[0]
                            buffer = buffer[4:]
                            
                            if len(buffer) >= expected_size:
                                jpeg_data = buffer[:expected_size]
                                buffer = buffer[expected_size:]
                                
                                self.frame_count += 1
                                self.data_received += len(jpeg_data)
                                
                                try:
                                    self.udp_socket.sendto(jpeg_data, (self.target_ip, self.target_port))
                                except Exception:
                                    pass
                                
                                Clock.schedule_once(lambda dt, d=jpeg_data: self.update_image(d), 0)
                        else:
                            break
    
            except Exception:
                break
        
        self.client_socket = None
    
    def update_image(self, jpeg_data):
        try:
            texture = Texture.create()
            texture.blit_buffer(jpeg_data, colorfmt='rgb', bufferfmt='ubyte')
            texture.flip_vertical()
            self.image_widget.texture = texture
        except Exception:
            pass

if __name__ == '__main__':
    CAVMobileApp().run()
#啟動程式前，需下載plyer與pillow
"輸入：pip install plyer/pip install Pillow"


import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import socket
import threading
import json
import base64
import os
from datetime import datetime
from plyer import notification
from PIL import Image, ImageTk 
import io # 處理 Byte 資料

# --- 主題設定 ---
LIGHT_THEME = {'bg': '#f0f0f0', 
               'fg': 'black', 
               'text_bg': 'white', 
               'text_fg': 'black', 
               'btn_bg': '#e1e1e1', 
               'list_bg': 'white', 
               'highlight': 'blue', 
               'meta_fg': 'gray'}
DARK_THEME = {'bg': '#2e2e2e', 
              'fg': '#d3d3d3', 
              'text_bg': '#3e3e3e', 
              'text_fg': '#ffffff', 
              'btn_bg': '#4e4e4e', 
              'list_bg': '#3e3e3e', 
              'highlight': '#4da6ff', 
              'meta_fg': '#888888'}


class ChatClient:
    # --- 程式啟動初始化 ---
    def __init__(self, root):
        self.root = root
        self.root.title("Python Socket Chat Room")
        self.root.geometry("1280x800")
        
        self.nickname = ""
        self.sock = None
        self.is_connected = False
        self.target_private_user = None
        self.image_references = [] # 用來存圖片參照
        self.image_data_store = {} # 用來存 Base64 原圖資料
        self.is_dark_mode = True 
        self.current_theme = DARK_THEME

        # --- UI 建置 (簡化顯示) ---
        self.top_bar = tk.Frame(root); self.top_bar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        tk.Button(self.top_bar, text="切換主題", command=self.toggle_theme).pack(side=tk.LEFT)
        tk.Button(self.top_bar, text="斷線離開", command=self.safe_exit, bg='#ff6666', fg='white').pack(side=tk.RIGHT)

        self.login_frame = tk.Frame(root); self.login_frame.pack(pady=50)
        self.create_login_ui() 

        self.main_frame = tk.Frame(root)
        self.chat_area = scrolledtext.ScrolledText(self.main_frame, state='disabled', width=65)
        self.chat_area.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.right_frame = tk.Frame(self.main_frame); self.right_frame.grid(row=0, column=1, sticky="ns", padx=10)
        self.user_listbox = tk.Listbox(self.right_frame, height=25); self.user_listbox.pack(pady=5, fill=tk.Y)
        self.user_listbox.bind('<<ListboxSelect>>', self.on_user_select)
        self.lbl_status = tk.Label(self.right_frame, text="模式: 廣播"); self.lbl_status.pack(pady=20)

        self.bottom_frame = tk.Frame(self.main_frame); self.bottom_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        self.entry_msg = tk.Entry(self.bottom_frame); self.entry_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.entry_msg.bind("<Return>", lambda e: self.send_message())
        tk.Button(self.bottom_frame, text="發送", command=self.send_message).pack(side=tk.LEFT)
        tk.Button(self.bottom_frame, text="圖片", command=self.send_image).pack(side=tk.LEFT)
        
        self.main_frame.grid_columnconfigure(0, weight=1); self.main_frame.grid_rowconfigure(0, weight=1)
        self.apply_theme()
        self.root.protocol("WM_DELETE_WINDOW", self.safe_exit)

    # --- 登入介面 ---
    def create_login_ui(self):
        labels = ["Server IP:", "Server Port:", "暱稱:"]
        self.entries = {}
        defaults = ["127.0.0.1", "6000", ""]
        for i, text in enumerate(labels):
            tk.Label(self.login_frame, text=text, font=("Arial", 12)).grid(row=i, column=0, sticky="e")
            e = tk.Entry(self.login_frame, font=("Arial", 12))
            if defaults[i]: e.insert(0, defaults[i])
            e.grid(row=i, column=1, padx=5, pady=5)
            self.entries[i] = e
        self.entry_ip, self.entry_port, self.entry_nickname = self.entries[0], self.entries[1], self.entries[2]
        tk.Button(self.login_frame, text="連線進入", command=self.connect_server, font=("Arial", 12), bg="#4da6ff", fg="white").grid(row=3, column=0, columnspan=2, pady=20, sticky="ew")
    
    def recv_message(self):
        f = self.sock.makefile(encoding='utf-8')
        while self.is_connected:
            try:
                text = f.readline()
                if not text:
                    break
                msg = json.loads(text)
    
                msg_type = msg.get('type')
                nickname = msg.get('nickname', 'Unknown')
                sender = msg.get('sender', nickname)
                msg_time = msg.get('time', datetime.now().strftime('%Y/%m/%d %H:%M'))
                is_history = msg.get('is_history', False)
                
                notify_content = None # 初始化為 None

                if msg_type == 2: # 登入成功
                    self.append_chat("系統", "登入成功！")
                
                if msg_type == 4: continue 
                
                # --- 一般廣播 (Type 3) ---
                if msg_type == 3:
                    content = msg['message']
                    self.append_chat(sender, content, time_str=msg_time)
                    notify_content = content # 

                # --- Type 5: 廣播訊息與系統指令 ---
                if msg['type'] == 5:
                    action = msg.get('action')
                    
                    # 1. 處理踢人
                    if action == 'kick':
                        messagebox.showwarning("通知", "你已被管理員踢出聊天室")
                        self.safe_exit()
                        return
                        
                    # 2. 處理伺服器關閉
                    elif action == 'shutdown':
                        self.append_chat("系統", "伺服器已關閉，程式將在 10 秒後結束...", highlight=True)
                        self.entry_msg.config(state='disabled')
                        self.root.after(10000, self.safe_exit)
                        return

                    # 3. 處理人數已滿
                    elif action == 'full':
                        messagebox.showwarning("連線失敗", "伺服器人數已滿，請稍後再試。")
                        self.safe_exit()
                        return

                    # 4. 一般聊天訊息 (必須要有這段，不然會收不到訊息)
                    else:
                        sender = msg['nickname']
                        content = msg['message']
                        msg_time = msg.get('time', datetime.now().strftime('%Y/%m/%d %H:%M'))
                        self.append_chat(sender, content, time_str=msg_time)
                        if sender != self.nickname and not is_history:
                            self.show_notification(f"{sender} 說", content)
 
                if msg_type == 6: # 更新名單
                    self.update_user_list(msg['users'])

                # --- 私訊 (Type 7) ---
                if msg['type'] == 7:
                    sender = msg.get('sender', '未知使用者') 
                    content = msg.get('message', '')
                    msg_time = msg.get('time', datetime.now().strftime('%Y/%m/%d %H:%M'))
                    
                    
                    self.append_chat(sender, f"[來自 {sender} 的私訊] {content}", time_str=msg_time, highlight=True)

                    if not is_history:
                        self.show_notification(f"私訊: {sender}", content)
                # --- 圖片 (Type 9) ---
                if msg_type == 9:
                    self.append_chat(sender, "傳送了一張圖片", time_str=msg_time)
                    self.display_image(msg['image_data'])
                    notify_content = "傳送了一張圖片"
                    
                    if not is_history:
                        self.show_notification(f": {sender}", '傳送了一張圖片')

                # --- 統一通知判斷 ---
                if notify_content:
                    if sender != self.nickname and sender != '系統' and not is_history:
                        self.show_notification(f"來自 {sender}", notify_content)

            except Exception as e:
                print(f"[Error] 接收訊息錯誤: {e}")
                self.root.after(0, lambda: messagebox.showerror("斷線", "與伺服器的連線已中斷"))
                break
        self.is_connected = False
            

    # --- 內容顯示到聊天視窗 ---
    def append_chat(self, sender, message, time_str="", highlight=False, is_image=False, image_data=None):
        self.chat_area.config(state='normal')
        
        # 插入標頭 (名字 + 時間)
        if not time_str: time_str = datetime.now().strftime('%Y/%m/%d %H:%M')
        header = f"{sender}  {time_str}\n"
        
        # 定義標籤樣式
        self.chat_area.tag_config("meta", foreground=self.current_theme['meta_fg'], font=("Arial", 9))
        self.chat_area.tag_config("content", foreground=self.current_theme['text_fg'], font=("Arial", 11))
        self.chat_area.tag_config("highlight", foreground=self.current_theme['highlight'], font=("Arial", 11, "bold"))
        
        self.chat_area.insert(tk.END, header, "meta")

        # 插入內容 (文字或圖片)
        if is_image and image_data:
            self.display_image(image_data) # 圖片會自己換行
        else:
            tag = "highlight" if highlight else "content"
            self.chat_area.insert(tk.END, f"{message}\n\n", tag) # 多加一個換行讓版面寬鬆點

        self.chat_area.see(tk.END)
        self.chat_area.config(state='disabled')

    # --- 顯示縮圖 ---
    def display_image(self, b64):
        try:
            # 1. 將 Base64 轉回 Bytes，再用 PIL 開啟
            image_bytes = base64.b64decode(b64)
            img = Image.open(io.BytesIO(image_bytes))
            
            # 2. 計算縮圖 (保持長寬比)
            # 這裡用 thumbnail 方法，比原本的 subsample 更聰明且畫質更好
            max_size = (300, 300) # 設定最大寬高
            img_thumb = img.copy() # 複製一份來做縮圖，保留 img 為原圖
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(img)
            
            # 3. 生成唯一 Tag ID (用時間戳記+隨機數，或是簡單的計數)
            # 這裡我們利用 image_references 的長度來當作唯一 ID
            img_id = f"img_{len(self.image_references)}"
            
            # 4. 存原圖資料 (為了點擊放大時使用)
            self.image_references.append(tk_img) # 防止被垃圾回收
            self.image_data_store[img_id] = b64 # 存 Base64 字串
            # 5. 顯示在聊天室
            self.chat_area.config(state='normal')
            # --- 改用 Label 包裝圖片 ---
            # 建立一個 Label，裡面放圖片，並直接設定手指游標 (cursor="hand2")
            # bg="white" 可以依據你的主題調整，或是設為聊天室背景色
            img_label = tk.Label(self.chat_area, image=tk_img, bg=self.current_theme['text_bg'], cursor="hand2")
            img_label.image = tk_img
            # 直接綁定點擊事件到這個 Label 上
            img_label.bind("<Button-1>", lambda e, tag=img_id: self.open_full_image(tag))
            # 使用 window_create 把這個 Label 塞進聊天室文字框
            self.chat_area.window_create(tk.END, window=img_label)

            self.chat_area.insert(tk.END, "\n\n") 
            self.chat_area.see(tk.END)
            self.chat_area.config(state='disabled')

        except Exception as e:
            print(f"圖片顯示錯誤: {e}")
    # --- 點擊圖片放大 ---        
    def open_full_image(self, img_tag):
        """點擊圖片後彈出視窗顯示原圖"""
        b64_data = self.image_data_store.get(img_tag)
        if not b64_data: return
        try:
            # 建立新視窗 (Toplevel)
            top = tk.Toplevel(self.root)
            top.title("圖片預覽")
            
            # 讀取原圖
            image_bytes = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(image_bytes))
            
            # 處理過大圖片 (如果原圖比螢幕還大，稍微縮一下，不然視窗會爆開)
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            
            # 如果圖片寬或高超過螢幕的 80%，就縮放
            if img.width > screen_width * 0.8 or img.height > screen_height * 0.8:
                ratio = min(screen_width * 0.8 / img.width, screen_height * 0.8 / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            tk_img = ImageTk.PhotoImage(img)
            
            # 顯示圖片
            lbl = tk.Label(top, image=tk_img, bg="black")
            lbl.image = tk_img # 重要：保留參照
            lbl.pack(fill=tk.BOTH, expand=True)
            
            # 點擊視窗任意處關閉
            lbl.bind("<Button-1>", lambda e: top.destroy())

        except Exception as e:
            messagebox.showerror("錯誤", f"無法開啟圖片: {e}")
    # --- 發送文字訊息 ---
    def send_message(self):
        text = self.entry_msg.get()
        if not text: return
        if len(text) > 200: return messagebox.showwarning("警告", "訊息過長")
        
        current_time = datetime.now().strftime('%Y/%m/%d %H:%M')
        
        try:
            if self.target_private_user: # 判斷私訊
                msg = {'type': 7, 
                       'target': self.target_private_user, 
                       'message': text, 
                       'sender': self.nickname, 
                       'time': current_time}
                self.sock.sendall((json.dumps(msg)+'\n').encode('utf-8'))
                self.append_chat("我", f"[發送私訊給 {self.target_private_user}] {text}", time_str=current_time, highlight=True)
            else:
                msg = {'type': 3, 
                       'nickname': self.nickname, 
                       'message': text, 
                       'time': current_time}
                self.sock.sendall((json.dumps(msg)+'\n').encode('utf-8'))
                self.append_chat("我", text, time_str=current_time)
            
            self.entry_msg.delete(0, tk.END)
        except Exception as e: self.append_chat("系統", f"發送失敗: {e}")
        
        
    def send_image(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.gif")])
        if not path: return
        
        # 1. 檢查檔案大小
        MAX_SIZE = 10 * 1024 * 1024 # 10MB
        file_size = os.path.getsize(path)
        
        if file_size > MAX_SIZE:
            return messagebox.showwarning("警告", "圖片過大 (限制 10MB)")
        
        current_time = datetime.now().strftime('%Y/%m/%d %H:%M')
        
        try:
            # 2. 使用 Pillow 讀取並處理圖片
            img = Image.open(path)
            
            # 如果圖片很大 (例如超過 1MB)，我們進行壓縮再傳送
            # 這樣可以讓 10MB 的照片變成 1-2MB，肉眼幾乎看不出差別，但傳輸快很多
            img_byte_arr = io.BytesIO()
            
            # 判斷格式: 如果是 PNG/GIF (有透明度或動圖) 就不壓縮品質，直接轉 Bytes
            if img.format in ['PNG', 'GIF']:
                img.save(img_byte_arr, format=img.format)
            else:
                # JPG 圖片：設定品質為 70 (大幅減少體積)
                # convert('RGB') 是為了防止存成 JPG 時因為透明度報錯
                img = img.convert('RGB')
                img.save(img_byte_arr, format='JPEG', quality=70)
            
            img_byte_arr = img_byte_arr.getvalue()
            # 3. 轉 Base64
            data = base64.b64encode(img_byte_arr).decode()
            msg = {'type': 9, 
                   'nickname': self.nickname, 
                   'image_data': data, 
                   'time': current_time}
            self.sock.sendall((json.dumps(msg)+'\n').encode('utf-8'))
            self.append_chat("我", "傳送了一張圖片", time_str=current_time, is_image=True, image_data=data)
        except: pass

    # 連線
    def connect_server(self):
        ip, port, name = self.entry_ip.get(), self.entry_port.get(), self.entry_nickname.get()
        if not ip or not port or not name: return messagebox.showerror("錯誤", "欄位不可為空")
        self.nickname = name
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((ip, int(port)))
            self.sock.settimeout(None)
            self.sock.sendall((json.dumps({'type': 1, 'nickname': name})+'\n').encode('utf-8'))
            self.is_connected = True
            threading.Thread(target=self.recv_message, daemon=True).start()
            self.login_frame.pack_forget()
            self.main_frame.pack(fill=tk.BOTH, expand=True)
            self.root.title(f"聊天室 - {self.nickname}")
        except Exception as e: messagebox.showerror("連線失敗", str(e))

    def update_user_list(self, users):
        self.user_listbox.delete(0, tk.END)
        for u in users: self.user_listbox.insert(tk.END, u)
        # --- 當私訊對象離開時自動換回廣播 ---
        if self.target_private_user and (self.target_private_user not in users):
            self.target_private_user = None 
            self.lbl_status.config(text="模式: 廣播 (自動切換)", fg=self.current_theme['fg'])
            self.append_chat("系統", "私訊對象已離線")

    # --- 切換主題 ---
    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.current_theme = DARK_THEME if self.is_dark_mode else LIGHT_THEME
        self.apply_theme()

    # --- 切換主題時刷新畫面顏色 ---
    def apply_theme(self):
        theme = self.current_theme
        self.root.config(bg=theme['bg'])
        for w in [self.top_bar, self.login_frame, self.main_frame, self.right_frame, self.bottom_frame]: w.config(bg=theme['bg'])
        for w in [self.entry_ip, self.entry_port, self.entry_nickname, self.entry_msg]: w.config(bg=theme['text_bg'], fg=theme['text_fg'], insertbackground=theme['text_fg'])
        for w in self.login_frame.winfo_children(): 
            if isinstance(w, tk.Label): w.config(bg=theme['bg'], fg=theme['fg'])
        self.lbl_status.config(bg=theme['bg'], fg=theme['fg'])
        self.chat_area.config(bg=theme['text_bg'], fg=theme['text_fg'])
        self.user_listbox.config(bg=theme['list_bg'], fg=theme['text_fg'])
        self.chat_area.tag_config("meta", foreground=theme['meta_fg'])
        self.chat_area.tag_config("content", foreground=theme['text_fg'])
        self.chat_area.tag_config("highlight", foreground=theme['highlight'])

    # --- 選擇私訊對象 ---
    def on_user_select(self, e):
        sel = self.user_listbox.curselection()
        if sel:
            target = self.user_listbox.get(sel[0])
            if target == self.nickname:# 點到自己取消私訊功能
                self.target_private_user = None
                self.lbl_status.config(text="模式: 廣播", fg=self.current_theme['fg'])
                self.user_listbox.selection_clear(0, tk.END)
            else:
                self.target_private_user = target
                self.lbl_status.config(text=f"私訊: {target}", fg=self.current_theme['highlight'])
                self.root.after(50, lambda: self.entry_msg.focus_set())
        else:
            self.target_private_user = None
            self.lbl_status.config(text="模式: 廣播", fg=self.current_theme['fg'])
    
    # --- 安全關閉程式 ---
    def safe_exit(self):
        self.is_connected = False
        if self.sock: 
            try: self.sock.close() 
            except: pass
        self.root.destroy()
        os._exit(0)

    # --- 桌面通知 ---
    def show_notification(self, t, m):
        try:
        # 測試用：印出一行字證明程式有跑到這裡
            print(f"[Debug] 準備發送通知: {t} - {m}") 
            
            notification.notify(title=t, message=m, timeout=3)
            
        except Exception as e:
            # 把 pass 改成 print，讓錯誤現形
            print(f"[Error] 通知發送失敗: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    ChatClient(root)
    root.mainloop()

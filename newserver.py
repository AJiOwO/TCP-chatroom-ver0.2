import socket
import threading
import json
import time
import sqlite3
from datetime import datetime
import os

BIND_IP = '0.0.0.0'
BIND_PORT = 6000
MAX_HISTORY_SEND = 10
DB_NAME = 'chat_record.db'

client_list = []

# 資料庫鎖：防止多執行緒同時寫入導致資料遺失
db_lock = threading.Lock() 

# --- 初始化資料庫 ---
def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                json_content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    print(f"資料庫 {DB_NAME} 連線成功")

# --- 儲存訊息 ---
def save_message(json_str):
    try:
        with db_lock: #確保寫入時不會被其他人打斷
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO messages (json_content) VALUES (?)", (json_str,))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"儲存失敗: {e}")

# --- 讀取歷史訊息 ---
def get_recent_messages(limit=10):
    "讀取歷史訊息 (加入鎖保護)"
    messages = []
    try:
        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            query = f"SELECT json_content FROM (SELECT json_content, id FROM messages ORDER BY id DESC LIMIT ?) ORDER BY id ASC"
            c.execute(query, (limit,))
            rows = c.fetchall()
            messages = [row[0] for row in rows]
            conn.close()
    except Exception as e:
        print(f"讀取失敗: {e}")
    return messages

# --- Type 6: 更新名單 ---
def broadcast_user_list():
    nicknames = [c['nickname'] for c in client_list]
    msgdict = {'type': 6, 
               'users': nicknames}
    data = (json.dumps(msgdict) + '\n').encode('utf-8')
    for client in client_list:
        try: client['socket'].sendall(data)
        except: pass
        
# --- Type 5: 發送系統公告 ---
def kick_client_by_name(target_name):
    global client_list
    target_client = next((c for c in client_list if c['nickname'] == target_name), None)
    if target_client:
        print(f"踢除: {target_name}")
        try:
            target_client['socket'].sendall((json.dumps({'type': 5,'message': '你已被踢出聊天室'})+'\n').encode('utf-8'))
            time.sleep(0.1)
            target_client['socket'].close()
        
        except: pass
        if target_client in client_list: client_list.remove(target_client)
        broadcast_user_list()
        
        sys_msg = {'type': 5, 
                   'nickname': '系統', 
                   'message': f'{target_name} 已被踢出'}
        data = (json.dumps(sys_msg)+'\n').encode('utf-8')
        for c in client_list:
            try: c['socket'].sendall(data)
            except: pass
            
# --- 管理員控制台 ---
def admin_console():
    print("--- Server Started ---")
    """管理員後台指令執行緒"""
    print("--- 管理員控制台啟動 ---")
    print("指令: /kick <名字>  (踢人)")
    print("指令: /list         (查看名單)")
    print("指令: /stop         (關閉伺服器)")
    
    while True:
        try:
            cmd = input()
            
            if cmd.startswith('/kick '):
                parts = cmd.split(' ', 1)
                if len(parts) > 1: 
                    kick_client_by_name(parts[1].strip())
                else:
                    print("格式錯誤，請輸入: /kick 名字")
            if cmd == '/list':
                print([c['nickname'] for c in client_list])
            if cmd == '/stop':
                print("正在清除歷史紀錄...")
                # 連線資料庫並刪除所有資料
                with db_lock:
                    conn = sqlite3.connect(DB_NAME)
                    c = conn.cursor()
                    c.execute("DELETE FROM messages") # 刪除所有訊息
                    # c.execute("VACUUM") # 可選：釋放空間
                    conn.commit()
                    conn.close()
                    print("歷史紀錄已清除。")
                
                print("正在關閉伺服器...")
                # 1. 廣播通知
                sys_msg = {'type': 5, 'nickname': '系統', 'message': '伺服器即將關閉，請自行離線。'}
                data = (json.dumps(sys_msg)+'\n').encode('utf-8')
                for c in client_list:
                    try: c['socket'].sendall(data)
                    except: pass
                
                # 2. 強制結束程式 (包含所有執行緒)
                print("伺服器關閉。")
                os._exit(0)
            
        except Exception as e:
            print(f"Console Error: {e}")

def recv_message(new_sock, sockname):
    global client_list
    nickname = ''
    try:
        while True:
            f = new_sock.makefile(encoding='utf-8')
            text = f.readline()
            if not text: break
            
            message = json.loads(text)
            
            # --- Type 1: 登入 ---
            if message['type'] == 1:
                nickname = message['nickname']
                client_list.append({'nickname': nickname, 'socket': new_sock})
                new_sock.sendall((json.dumps({'type': 2}) + '\n').encode('utf-8'))
                time.sleep(0.05)
                
                # 回放歷史紀錄 (加入 is_history 標籤)
                recent_history = get_recent_messages(MAX_HISTORY_SEND)
                for json_str in recent_history:
                    # 需要把儲存的 JSON 字串解開，標籤，再包裝
                    hist_msg = json.loads(json_str)
                    hist_msg['is_history'] = True # 告訴 Client 這是歷史訊息
                    new_sock.sendall((json.dumps(hist_msg) + '\n').encode('utf-8'))
                
                time.sleep(0.1)
                broadcast_user_list()
                time.sleep(0.05)
                
                sys_msg = {'type': 5, 
                           'nickname': '系統', 
                           'message': f'{nickname} 加入了聊天室'}
                broadcast_data = (json.dumps(sys_msg) + '\n').encode('utf-8')
                for c in client_list:
                    try: c['socket'].sendall(broadcast_data)
                    except: pass

            # --- Type 3 :訊息處理 ---
            if message['type'] == 3:
                # 1. 回傳 Type 4 給發送者 
                new_sock.sendall((json.dumps({'type': 4}) + '\n').encode('utf-8'))
                
                # 2. 準備轉發給其他人的 Type 5 封包
                # 取得當前時間並格式化
                current_time = datetime.now().strftime('%Y/%m/%d %H:%M')
                
                msgdict = {
                    'type': 5,
                    'nickname': message['nickname'],
                    'message': message['message'],
                    'time': current_time  # 將時間加入封包
                }
                save_message(json.dumps(msgdict))
                
                data = (json.dumps(msgdict) + '\n').encode('utf-8')
                # 廣播給其他人
                for client in client_list:
                    if client['socket'] != new_sock:
                        try: client['socket'].sendall(data)
                        except: pass
            
            # --- Type 7: 私訊 ---
            if message['type'] == 7:
                message['time'] = datetime.now().strftime('%Y/%m/%d %H:%M')
                target = message['target']
                
                pm_data = (json.dumps(message) + '\n').encode('utf-8')
                for client in client_list:
                    if client['nickname'] == target:
                        try: client['socket'].sendall(pm_data)
                        except: pass
                        break
                new_sock.sendall(pm_data)
            # --- Type 9: 收到圖片訊息 ---
            if message['type'] == 9:
                current_time = datetime.now().strftime('%Y/%m/%d %H:%M')
                msgdict = {
                    'type': 9,
                    'nickname': message['nickname'],
                    'image_data': message['image_data'],
                    'time': current_time
                }
                save_message(json.dumps(msgdict))
                data = (json.dumps(msgdict) + '\n').encode('utf-8')
                
                # 廣播給其他人
                for client in client_list:
                    if client['socket'] != new_sock:
                        try: client['socket'].sendall(data)
                        except: pass

    except (ConnectionResetError, ConnectionAbortedError):
        print(f"[{nickname or sockname}] 已斷線 (正常離線)")
    except Exception as e:
        print(f"Err: {e}")
    finally:
        dead = next((c for c in client_list if c['socket'] == new_sock), None)
        if dead: 
            client_list.remove(dead)
            # 1. 更新名單
            broadcast_user_list()
            
            # 2. 廣播離開訊息
            if nickname:
                print(f'{nickname} 離開了')
                sys_msg = {
                    'type': 5, 
                    'nickname': '系統', 
                    'message': f'{nickname} 離開了聊天室',
                    'time': datetime.now().strftime('%Y/%m/%d %H:%M')
                }
                data = (json.dumps(sys_msg)+'\n').encode('utf-8')
                for c in client_list:
                    try: c['socket'].sendall(data)
                    except: pass
        
        new_sock.close()

if __name__ == '__main__':
    init_db()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((BIND_IP, BIND_PORT))
    sock.listen(5)
    print(f'Server listening at {BIND_IP}:{BIND_PORT}')
    threading.Thread(target=admin_console, daemon=True).start()
    while True:
        c, a = sock.accept()
        threading.Thread(target=recv_message, args=(c, a), daemon=True).start()
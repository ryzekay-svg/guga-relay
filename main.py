import socket
import threading
import json
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# O Render injeta a porta HTTP na variável PORT (geralmente 10000)
PORT_HTTP = int(os.environ.get("PORT", 10000))

# Servidor HTTP simples para passar no Health Check do Render
class DummyHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return # Silencia os logs do HTTP no terminal

def iniciar_servidor_http():
    server = HTTPServer(('0.0.0.0', PORT_HTTP), DummyHTTPHandler)
    server.serve_forever()

# --- CÓDIGO DO SEU RELAY (TCP) ---
HOST = '0.0.0.0'
PORT_CONTROL = 5000
PORT_VIDEO = 5005
PORT_AUDIO = 5007

clientes_conectados = {}
painel_conectado = None
lock = threading.Lock()

def gerenciar_ponte_dados(socket_origem, socket_destino):
    try:
        while True:
            dados = socket_origem.recv(65536)
            if not dados:
                break
            socket_destino.sendall(dados)
    except:
        pass
    finally:
        try: socket_origem.close()
        except: pass
        try: socket_destino.close()
        except: pass

def escutar_controle():
    global painel_conectado
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT_CONTROL))
    server.listen(20)
    print(f"[RELAY] Controle ativo na porta {PORT_CONTROL}")

    while True:
        conn, addr = server.accept()
        try:
            raw_ident = conn.recv(1024).decode('utf-8', errors='ignore').strip()
            if not raw_ident:
                conn.close()
                continue

            dados = json.loads(raw_ident)
            tipo = dados.get("tipo_conexao")

            if tipo == "CLIENTE":
                id_cliente = dados.get("id_pc")
                with lock:
                    clientes_conectados[id_cliente] = {
                        "socket_control": conn,
                        "socket_video": None,
                        "socket_audio": None,
                        "nome": dados.get("nome_pc", "PC Remoto"),
                        "addr": addr
                    }
                print(f"[RELAY] Novo cliente online: {id_cliente} ({dados.get('nome_pc')})")

            elif tipo == "PAINEL":
                with lock:
                    painel_conectado = conn
                print("[RELAY] Painel de Controle conectado!")
                lista = [{"id": k, "nome": v["nome"]} for k, v in clientes_conectados.items()]
                conn.sendall((json.dumps({"tipo": "LISTA_CLIENTES", "clientes": lista}) + "\n").encode('utf-8'))

            elif tipo == "PAINEL_STREAM":
                id_alvo = dados.get("id_alvo")
                canal = dados.get("canal")
                with lock:
                    cliente = clientes_conectados.get(id_alvo)
                
                if cliente:
                    sock_cliente = cliente["socket_video"] if canal == "video" else cliente["socket_audio"]
                    if sock_cliente:
                        threading.Thread(target=gerenciar_ponte_dados, args=(conn, sock_cliente), daemon=True).start()
                        threading.Thread(target=gerenciar_ponte_dados, args=(sock_cliente, conn), daemon=True).start()

        except Exception as e:
            print(f"[RELAY ERRO]: {e}")

def escutar_midia(porta, tipo_midia):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, porta))
    server.listen(20)
    print(f"[RELAY] Canal de {tipo_midia} ativo na porta {porta}")

    while True:
        conn, addr = server.accept()
        try:
            raw = conn.recv(1024).decode('utf-8', errors='ignore').strip()
            dados = json.loads(raw)
            id_cliente = dados.get("id_pc")
            
            with lock:
                if id_cliente in clientes_conectados:
                    if tipo_midia == "video":
                        clientes_conectados[id_cliente]["socket_video"] = conn
                    else:
                        clientes_conectados[id_cliente]["socket_audio"] = conn
        except:
            pass

if __name__ == "__main__":
    # Inicia o servidor HTTP para o Render não dar erro
    threading.Thread(target=iniciar_servidor_http, daemon=True).start()
    
    # Inicia as portas TCP do seu Relay
    threading.Thread(target=escutar_controle, daemon=True).start()
    threading.Thread(target=escutar_midia, args=(PORT_VIDEO, "video"), daemon=True).start()
    threading.Thread(target=escutar_midia, args=(PORT_AUDIO, "audio"), daemon=True).start()
    
    while True:
        time.sleep(1)

# -*- coding: utf-8 -*-
"""Tu propio servidor de IA con GPU gratis en la nube (Kaggle): la nube hace el trabajo pesado, no tu PC.

Noviark genera un cuaderno de Kaggle listo para ejecutar que:
  1. instala Ollama y descarga el modelo elegido en la GPU gratuita de Kaggle (2 × T4 = 32 GB de VRAM, el doble que tu PC),
  2. pone delante un pequeño guardián con contraseña (token) para que nadie más use tu servidor,
  3. abre un túnel seguro de Cloudflare y muestra la URL y el token para pegarlos en Noviark.
Límites de Kaggle (pueden cambiar): cuenta verificada con teléfono para usar GPU e internet, ~30 h de GPU por semana,
sesiones de hasta 12 h. La URL cambia cada vez que reinicias el cuaderno. Revisa las condiciones de uso de Kaggle.
"""
import json
import secrets

MODELOS = {
    "qwen3-coder:30b": "Qwen3-Coder 30B (el mejor para programar como agente; usa las 2 GPU)",
    "gpt-oss:20b": "GPT-OSS 20B (razona bien y usa herramientas; cabe en 1 GPU)",
    "qwen3:32b": "Qwen3 32B (general, piensa; usa las 2 GPU)",
    "devstral:24b": "Devstral 24B (agente de programación de Mistral)",
    "gemma3:27b": "Gemma 3 27B (ve imágenes)",
}

PROXY = r'''
import os, requests
from flask import Flask, request, Response
TOKEN = os.environ["NOVIQ_TOKEN"]
app = Flask(__name__)
@app.route("/", defaults={"p": ""}, methods=["GET", "POST", "DELETE"])
@app.route("/<path:p>", methods=["GET", "POST", "DELETE"])
def proxy(p):
    if request.headers.get("Authorization", "") != "Bearer " + TOKEN:
        return {"error": "token inválido"}, 401
    r = requests.request(request.method, "http://127.0.0.1:11434/" + p, data=request.get_data(),
                         headers={"Content-Type": request.headers.get("Content-Type", "application/json")}, stream=True, timeout=900)
    return Response(r.iter_content(chunk_size=None), status=r.status_code, content_type=r.headers.get("content-type"))
app.run(host="127.0.0.1", port=8000, threaded=True)
'''


def cuaderno(modelo="qwen3-coder:30b", token=None):
    token = token or secrets.token_urlsafe(24)
    modelo = modelo if modelo in MODELOS else "qwen3-coder:30b"

    def code(src):
        return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": src}

    def mdc(src):
        return {"cell_type": "markdown", "metadata": {}, "source": src}
    cells = [
        mdc(f"# Servidor de IA para Noviark ({modelo})\n"
            "1. Arriba a la derecha: **Settings → Accelerator → GPU T4 x2** y **Internet → On** (necesitas la cuenta verificada con teléfono).\n"
            "2. Pulsa **Run All**. Al final aparecerán la **URL** y el **token**: pégalos en Noviark → 🎁 IA gratis → *Servidor GPU en la nube*.\n"
            "3. Deja esta pestaña abierta mientras trabajas. La URL cambia cada vez que reinicias."),
        code("import subprocess, os, time\n"
             "subprocess.run('curl -fsSL https://ollama.com/install.sh | sh', shell=True, check=True)\n"
             "env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11434', OLLAMA_CONTEXT_LENGTH='32768', OLLAMA_FLASH_ATTENTION='1',\n"
             "           OLLAMA_KEEP_ALIVE='-1', OLLAMA_SCHED_SPREAD='1')\n"
             "ollama = subprocess.Popen(['ollama', 'serve'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
             "time.sleep(6)\n"
             f"subprocess.run(['ollama', 'pull', '{modelo}'], check=True)\n"
             f"print('✔ Modelo {modelo} listo en la GPU')"),
        code("import subprocess, os\n"
             "subprocess.run('pip install -q flask requests', shell=True)\n"
             f"open('proxy.py', 'w').write({PROXY!r})\n"
             f"os.environ['NOVIQ_TOKEN'] = {token!r}\n"
             "proxy = subprocess.Popen(['python', 'proxy.py'], env=dict(os.environ))\n"
             "print('✔ Guardián con token en marcha')"),
        code("import subprocess, re, time\n"
             "subprocess.run('wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared && chmod +x cloudflared', shell=True, check=True)\n"
             "tun = subprocess.Popen(['./cloudflared', 'tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8000'], stderr=subprocess.PIPE, text=True)\n"
             "url = None\n"
             "for line in tun.stderr:\n"
             "    m = re.search(r'https://[\\w-]+\\.trycloudflare\\.com', line)\n"
             "    if m:\n"
             "        url = m.group(0); break\n"
             "print('\\n' + '=' * 60)\n"
             "print('URL para Noviark  :', url)\n"
             f"print('Token para Noviark:', {token!r})\n"
             "print('=' * 60)"),
        code("# Mantiene el servidor vivo mientras la pestaña esté abierta\n"
             "import time\n"
             "while True:\n"
             "    time.sleep(60)"),
    ]
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    return json.dumps(nb, ensure_ascii=False, indent=1), token

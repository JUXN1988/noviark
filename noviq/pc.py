# -*- coding: utf-8 -*-
"""Control del PC (Windows) con el MISMO esquema que el navegador:
   1. LEER:   «elementos» lista los controles de la ventana activa con una referencia [eN] (UI Automation),
              «ventanas» lista las ventanas abiertas.
   2. ACTUAR: clic / escribir / teclas sobre esa referencia (o coordenadas), abrir programas, enfocar ventanas.
   3. VERIFICAR: volver a leer «elementos» (o «captura» si hace falta ver la pantalla).

Funciona sin instalar nada (PowerShell + UI Automation de Windows). Si además está conectado Windows-MCP
(🖥 PC y tareas → Activar), el agente del PC usa sus herramientas, que son más completas.
"""
import json
import re
import subprocess
import time

from .config import IS_WINDOWS

NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

PS_HEAD = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type @"
using System; using System.Runtime.InteropServices;
public class NvW {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, int d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[NvW]::SetProcessDPIAware() | Out-Null
"""

PS_ELEMENTOS = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$h = [NvW]::GetForegroundWindow()
$root = [System.Windows.Automation.AutomationElement]::FromHandle($h)
"VENTANA|" + $root.Current.Name + "|" + $root.Current.ClassName
$tipos = @('Button','Edit','MenuItem','ListItem','TabItem','CheckBox','RadioButton','ComboBox','Hyperlink','TreeItem','Document','DataItem','SplitButton','Menu','Text','Slider','Spinner')
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$i = 0
foreach ($e in $all) {
  try {
    $c = $e.Current
    if ($c.IsOffscreen) { continue }
    $t = $c.ControlType.ProgrammaticName -replace 'ControlType\.', ''
    if ($tipos -notcontains $t) { continue }
    $r = $c.BoundingRectangle
    if ($r.IsEmpty -or $r.Width -le 1 -or $r.Height -le 1) { continue }
    $n = ($c.Name -replace '[\r\n|]', ' ')
    if ($t -eq 'Text' -and -not $n) { continue }
    $v = ''
    try { $vp = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); $v = ($vp.Current.Value -replace '[\r\n|]', ' ') } catch {}
    if ($v.Length -gt 60) { $v = $v.Substring(0, 60) + '…' }
    $i++
    "e$i|$t|$n|$v|$([int]($r.X + $r.Width / 2))|$([int]($r.Y + $r.Height / 2))|$($c.IsEnabled)"
    if ($i -ge __MAX__) { break }
  } catch {}
}
"""

PS_VENTANAS = r"""
Get-Process | Where-Object { $_.MainWindowTitle } | Sort-Object StartTime -Descending -ErrorAction SilentlyContinue |
  Select-Object -First 40 | ForEach-Object { "$($_.Id)|$($_.ProcessName)|$($_.MainWindowTitle -replace '[\r\n|]',' ')" }
"""


def _ps(script, timeout=40):
    if not IS_WINDOWS:
        raise RuntimeError("El control del PC integrado solo funciona en Windows.")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_HEAD + script],
                       capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    out = r.stdout.decode("utf-8", "replace").strip()
    err = r.stderr.decode("utf-8", "replace").strip()
    if r.returncode != 0 and not out:
        raise RuntimeError(err[-600:] or f"PowerShell terminó con código {r.returncode}")
    return out


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


SPECIAL = set("+^%~(){}[]")
KEYMAP = {"enter": "{ENTER}", "intro": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}", "escape": "{ESC}", "backspace": "{BACKSPACE}",
          "borrar": "{BACKSPACE}", "supr": "{DELETE}", "delete": "{DELETE}", "arriba": "{UP}", "up": "{UP}", "abajo": "{DOWN}",
          "down": "{DOWN}", "izquierda": "{LEFT}", "left": "{LEFT}", "derecha": "{RIGHT}", "right": "{RIGHT}", "inicio": "{HOME}",
          "home": "{HOME}", "fin": "{END}", "end": "{END}", "espacio": " ", "space": " ", "pgup": "{PGUP}", "pgdn": "{PGDN}"}
MODS = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+", "mayus": "+"}


def to_sendkeys(combo):
    """'ctrl+s' → '^s', 'alt+f4' → '%{F4}', 'enter' → '{ENTER}'. Si ya viene en formato SendKeys, se respeta."""
    c = combo.strip()
    if re.search(r"[\^%+]\S|\{\w+\}", c) and "+" not in c.replace("{+}", ""):
        return c
    out = []
    for part in re.split(r"\s+", c):
        keys = part.split("+")
        mods = "".join(MODS[k.lower()] for k in keys[:-1] if k.lower() in MODS)
        k = keys[-1]
        kl = k.lower()
        if kl in KEYMAP:
            k = KEYMAP[kl]
        elif re.fullmatch(r"f\d{1,2}", kl):
            k = "{" + kl.upper() + "}"
        elif len(k) == 1 and k in SPECIAL:
            k = "{" + k + "}"
        else:
            k = kl if mods else k
        out.append(mods + k)
    return "".join(out)


def _refs(ctx):
    return ctx.conv.setdefault("_pc_refs", {})


def elementos(ctx, maximo=120):
    out = _ps(PS_ELEMENTOS.replace("__MAX__", str(int(maximo))), timeout=45)
    lines = out.splitlines()
    refs, show = {}, []
    title = ""
    for ln in lines:
        p = ln.split("|")
        if p[0] == "VENTANA":
            title = p[1] if len(p) > 1 else ""
            continue
        if len(p) >= 7 and p[0].startswith("e"):
            ref, tipo, nombre, valor, x, y, en = p[:7]
            refs[ref] = {"x": int(x), "y": int(y), "tipo": tipo, "nombre": nombre}
            s = f"[{ref}] {tipo} «{nombre}»" + (f" = «{valor}»" if valor else "") + ("" if en == "True" else " (desactivado)")
            show.append(s)
    _refs(ctx).clear()
    _refs(ctx).update(refs)
    if not show:
        return f"Ventana activa: «{title}». No encontré controles legibles (puede ser un juego, un lienzo o una app sin accesibilidad). Usa accion='captura' para verla."
    return f"Ventana activa: «{title}»\nControles (usa ref=eN para clic/escribir):\n" + "\n".join(show)


def _xy(a, ctx):
    ref = (a.get("ref") or "").strip().strip("[]")
    if ref:
        r = _refs(ctx).get(ref)
        if not r:
            raise RuntimeError(f"No existe la referencia {ref}. Vuelve a leer la ventana con accion='elementos'.")
        return r["x"], r["y"], f"{r['tipo']} «{r['nombre']}»"
    if a.get("x") is None or a.get("y") is None:
        raise RuntimeError("Indica ref (de 'elementos') o coordenadas x, y.")
    return int(a["x"]), int(a["y"]), f"({a['x']},{a['y']})"


def control_pc(a, ctx):
    """Herramienta integrada. Devuelve texto (o dict con imágenes para 'captura')."""
    acc = (a.get("accion") or "").lower()
    try:
        if acc == "ventanas":
            out = _ps(PS_VENTANAS)
            rows = [l.split("|", 2) for l in out.splitlines() if l.count("|") >= 2]
            return "Ventanas abiertas (pid | programa | título):\n" + "\n".join(f"{r[0]} | {r[1]} | {r[2]}" for r in rows) if rows else "No hay ventanas con título."
        if acc == "elementos":
            return elementos(ctx, a.get("maximo") or 120)
        if acc == "abrir":
            obj = (a.get("objetivo") or a.get("texto") or "").strip()
            if not obj:
                return "ERROR: indica objetivo (programa, ruta o URL). Ej.: notepad, calc, excel, C:\\ruta\\archivo.xlsx, https://…"
            _ps(f"Start-Process {_q(obj)}" + (f" -ArgumentList {_q(a['argumentos'])}" if a.get("argumentos") else ""), timeout=30)
            time.sleep(float(a.get("esperar") or 2))
            return f"Abierto: {obj}. Lee la ventana con accion='elementos' para continuar."
        if acc == "enfocar":
            t = (a.get("objetivo") or a.get("texto") or "").strip()
            out = _ps(f"$ws = New-Object -ComObject WScript.Shell; $ws.AppActivate({_q(t)})")
            time.sleep(0.6)
            return f"Ventana «{t}» enfocada." if "True" in out else f"ERROR: no encontré una ventana cuyo título empiece por «{t}». Usa accion='ventanas'."
        if acc in ("clic", "doble_clic", "clic_derecho"):
            x, y, what = _xy(a, ctx)
            down, up = (0x08, 0x10) if acc == "clic_derecho" else (0x02, 0x04)
            n = 2 if acc == "doble_clic" else 1
            clicks = "; ".join(f"[NvW]::mouse_event({down},0,0,0,[UIntPtr]::Zero); [NvW]::mouse_event({up},0,0,0,[UIntPtr]::Zero); Start-Sleep -Milliseconds 80"
                               for _ in range(n))
            _ps(f"[NvW]::SetCursorPos({x},{y}) | Out-Null; Start-Sleep -Milliseconds 120; {clicks}")
            time.sleep(0.5)
            return f"{acc.replace('_', ' ')} en {what}. Verifica con accion='elementos'."
        if acc == "escribir":
            texto = str(a.get("texto") or "")
            pre = ""
            if a.get("ref") or a.get("x") is not None:
                x, y, _ = _xy(a, ctx)
                pre = (f"[NvW]::SetCursorPos({x},{y}) | Out-Null; [NvW]::mouse_event(2,0,0,0,[UIntPtr]::Zero); "
                       f"[NvW]::mouse_event(4,0,0,0,[UIntPtr]::Zero); Start-Sleep -Milliseconds 250; ")
            # se pega desde el portapapeles: respeta tildes, ñ y símbolos
            _ps(pre + f"Set-Clipboard -Value {_q(texto)}; Start-Sleep -Milliseconds 150; "
                      "$ws = New-Object -ComObject WScript.Shell; $ws.SendKeys('^v')"
                + ("; Start-Sleep -Milliseconds 150; $ws.SendKeys('{ENTER}')" if a.get("enter") else ""))
            time.sleep(0.4)
            return f"Escrito ({len(texto)} caracteres)" + (" y Enter" if a.get("enter") else "") + "."
        if acc == "teclas":
            sk = to_sendkeys(a.get("teclas") or a.get("texto") or "")
            if not sk:
                return "ERROR: indica teclas, ej. 'ctrl+s', 'alt+f4', 'enter', 'ctrl+shift+esc'."
            _ps(f"$ws = New-Object -ComObject WScript.Shell; $ws.SendKeys({_q(sk)})")
            time.sleep(0.5)
            return f"Teclas enviadas: {a.get('teclas') or a.get('texto')}"
        if acc == "esperar":
            s = min(float(a.get("segundos") or 2), 60)
            time.sleep(s)
            return f"Esperé {s:g} s."
        if acc == "captura":
            from .tools import t_captura_pantalla
            return t_captura_pantalla({}, ctx)
        return ("ERROR: acción desconocida. Usa: ventanas, elementos, abrir, enfocar, clic, doble_clic, clic_derecho, "
                "escribir, teclas, esperar, captura.")
    except subprocess.TimeoutExpired:
        return "ERROR: Windows tardó demasiado en responder (la ventana puede estar ocupada). Espera y vuelve a intentar."
    except Exception as e:
        return f"ERROR: {e}"


PC_SYSTEM = """Eres un agente experto en manejar el escritorio de Windows del usuario con herramientas.
Completa la TAREA de forma autónoma con el mismo método que un navegador:
1. LEER: mira qué hay (control_pc accion='ventanas' o 'elementos'; con Windows-MCP usa Snapshot). Cada control tiene una ref [eN].
2. ACTUAR: abre programas (accion='abrir', objetivo='notepad' / 'excel' / ruta / URL), enfoca ventanas, haz clic por ref,
   escribe (accion='escribir' con ref del campo), usa atajos (accion='teclas', teclas='ctrl+s').
3. VERIFICAR: después de cada acción importante vuelve a leer 'elementos' para comprobar el resultado.
- Si no hay controles legibles, usa accion='captura' y decide con la imagen (o coordenadas x,y).
- No cierres ni borres nada que el usuario no haya pedido. No toques contraseñas ni pagos.
- Si algo requiere al usuario (iniciar sesión, un permiso de Windows), DETENTE y explícalo en tu resumen.
Al terminar responde SOLO con un RESUMEN en español: qué hiciste, qué quedó abierto y qué falló si algo falló."""

TOOL_DEF = {"type": "function", "function": {
    "name": "control_pc",
    "description": "Maneja el escritorio de Windows: leer ventanas/controles, abrir programas, clic, escribir, atajos de teclado, captura.",
    "parameters": {"type": "object", "properties": {
        "accion": {"type": "string", "enum": ["ventanas", "elementos", "abrir", "enfocar", "clic", "doble_clic", "clic_derecho",
                                              "escribir", "teclas", "esperar", "captura"]},
        "ref": {"type": "string", "description": "Referencia eN obtenida con 'elementos'"},
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "objetivo": {"type": "string", "description": "Programa/ruta/URL para 'abrir' o título de ventana para 'enfocar'"},
        "argumentos": {"type": "string"},
        "texto": {"type": "string", "description": "Texto a escribir"},
        "enter": {"type": "boolean", "description": "Pulsar Enter después de escribir"},
        "teclas": {"type": "string", "description": "Atajo: ctrl+s, alt+f4, enter, tab, ctrl+shift+esc…"},
        "segundos": {"type": "number"}}, "required": ["accion"]}}}


def probar():
    if not IS_WINDOWS:
        return {"ok": False, "texto": "El control del PC integrado solo funciona en Windows."}
    try:
        out = _ps(PS_VENTANAS, timeout=20)
        return {"ok": True, "texto": f"✔ Control del PC funcionando. Ventanas abiertas: {len(out.splitlines())}"}
    except Exception as e:
        return {"ok": False, "texto": f"✖ {e}"}


def json_dump(x):
    return json.dumps(x, ensure_ascii=False)

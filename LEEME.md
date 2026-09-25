# Noviark 4.2: agente de IA de escritorio

Noviark es un programa para trabajar con IA en tu PC al estilo de Claude. La IA no solo conversa: crea proyectos, escribe y edita código, lo prueba, ejecuta PowerShell y Python, busca en internet, dibuja, ve tu pantalla y recuerda lo que haces. Funciona con **NVIDIA (build.nvidia.com)**, **Gemini, OpenAI, Anthropic, OpenRouter, Groq, DeepSeek, Mistral y xAI**, y con **IA local mediante Ollama y LM Studio**. Si una IA falla, **continúa con otra sin perder nada**.

## Instalar (recomendado)
Descarga el instalador de tu sistema desde la web de Noviark Labs o desde GitHub → Releases:
- **Windows 10/11**: `Noviark-Setup-Windows.exe` (o la versión portable `.zip`). Crea accesos en el menú Inicio y, si quieres, en el Escritorio.
- **Ubuntu / Debian**: `sudo apt install ./Noviark-Linux-amd64.deb` y luego busca **Noviark** en tus aplicaciones.
- **macOS (Apple Silicon)**: abre `Noviark-macOS-arm64.dmg` y arrastra Noviark a Aplicaciones. La primera vez: clic derecho → Abrir.

Noviark se abre en **su propia ventana nativa**, como cualquier programa (no en el navegador). El idioma (**español o inglés**) se elige solo según tu sistema; puedes cambiarlo en ⚙ Ajustes. Para cerrarlo por completo usa **⏻ Apagar Noviark**. Tus datos se guardan en `%APPDATA%\Noviark` (Windows), `~/Library/Application Support/Noviark` (macOS) o `~/.local/share/Noviark` (Linux).

## Iniciar desde el código (Windows)
1. Instala **Python 3.10 o superior** (https://www.python.org/downloads/). Al instalarlo, marca **"Add Python to PATH"**.
2. Haz doble clic en **`iniciar.bat`**. La primera vez tarda 1 o 2 minutos porque instala todo en `.venv`. Después se abre en su ventana.
3. Entra en **⚙ Ajustes → Proveedores y claves**, pega tus API keys y marca **activo** (o usa 🎁 IA gratis).
4. Opcional: `crear_acceso_directo.bat` pone un acceso directo **Noviark** con su icono en tu Escritorio.

## Compilar los instaladores
- Windows: `packaging\windows\build.bat` → `dist\Noviark-Setup-Windows.exe` y `dist\Noviark-Windows-portable.zip`
- Ubuntu: `bash packaging/linux/build.sh` → `dist/Noviark-Linux-amd64.deb`
- macOS: `bash packaging/macos/build.sh` → `dist/Noviark-macOS-<arch>.dmg`
- Automático: al subir una etiqueta `v4.2.0` a GitHub, Actions compila los tres y los publica en Releases.

## Claves y proveedores
- Puedes poner **varias claves por proveedor** (una por línea). Si una llega al límite o falla, se usa la siguiente.
- Las claves se guardan en la **bóveda cifrada `claves.vault`** (dentro de tu carpeta de datos), protegida con DPAPI de Windows. Solo tu usuario de Windows, en esta PC, puede descifrarla. Si alguien copia el archivo, no le sirve. En la pantalla nunca se ven completas.
- **IA local**: con Ollama (`http://localhost:11434/v1`) o LM Studio (`http://localhost:1234/v1`, activando el servidor en la pestaña Developer), los modelos que tengas descargados aparecen solos en la lista. Puedes cambiar las rutas en Ajustes.
- **Otros proveedores**: con "＋ Agregar otro proveedor" puedes añadir cualquier servicio compatible con OpenAI.
- Si un modelo no aparece en la lista, elige **"✏ Escribir otro modelo…"**, por ejemplo `gemini::gemini-3.8-flash` u `ollama::qwen3:8b`.

## Continuidad: la IA nunca empieza de cero
El programa (no la IA) lleva un **📋 ESTADO DEL TRABAJO** automático para cada conversación. Contiene:
- lo que pediste,
- el plan con sus tareas (✔ hecha · ▶ en curso · ○ pendiente),
- las acciones ya hechas,
- los archivos creados,
- los errores sin resolver,
- el **▶ SIGUIENTE PASO**.

Se actualiza después de cada paso, se guarda en disco y también en `<proyecto>\.noviq\ESTADO.md`. Puedes verlo con el botón 📋 de arriba.

Todas las IAs lo reciben siempre, y además en estos casos:
- **Relevo automático** (⚙ Ajustes → Respaldo): si una IA falla, se satura o no responde, la siguiente recibe un mensaje de relevo con el estado completo y la orden de seguir con el siguiente paso, sin repetir nada. Si **ninguna** responde, el programa espera y reintenta toda la cadena. No abandona el trabajo.
- **Respuesta cortada** por límite de tokens: continúa solo. Guarda el plan, sube el límite y baja el razonamiento.
- **▶ Continuar el trabajo**: si algo quedó a medias (error, detenido, programa cerrado), aparece este botón. Escribir "continúa" hace lo mismo: la IA recibe el estado y retoma donde quedó.
- **Conversación nueva en el mismo proyecto**: recibe el estado del último trabajo de ese proyecto.
- **Conversación muy larga**: aunque se recorten los mensajes antiguos, el estado conserva lo esencial.

Además, a la IA se le exige registrar primero el plan con la lista de tareas e ir marcándolo, y el programa se lo recuerda si lo olvida.

## Novedades: depuración como un experto (septiembre 2026)

Cuando se le pedía arreglar un programa, la IA a veces se quedaba **razonando sin fin** o daba vueltas sin avanzar. Ahora:

### 🛡 Guardián de razonamiento
- Vigila en vivo lo que escribe la IA. Si piensa demasiado sin actuar (por defecto 16 000 caracteres o 150 s; 40 % menos con IA local) o **repite el mismo texto en bucle**, la corta, le deja un resumen de lo que pensó y le ordena actuar YA con una herramienta y razonamiento breve (`reasoning_effort=low` y, en GLM/Qwen/DeepSeek de NVIDIA, sin «thinking»).
- Configurable en ⚙ Ajustes → Respaldo.

### 🚀 Escalado a la IA más capaz
- Un supervisor suma puntos cuando la IA se atasca (el guardián la cortó, repite acciones, la misma edición falla otra vez, errores seguidos, pruebas que siguen fallando). Al llegar al umbral, el trabajo pasa a **la IA más inteligente que tengas habilitada y con cuota** (sin 429, sin crédito agotado, verificada con tus claves primero), con todo el estado y el diagnóstico. Si ya estás usando la mejor, recibe un diagnóstico y una estrategia nueva; si aun así no avanza, se detiene para no gastar recursos.

### 🩺 Herramientas nuevas para depurar (como las de Claude)
- **diagnosticar**: revisa el proyecto completo y devuelve la lista PRIORIZADA de problemas con archivo:línea y cómo arreglarlos: codificación dañada (la repara a UTF-8 con respaldo), código omitido («// ... resto del código»), funciones que se llaman pero no existen o están en un archivo que la página no carga, orden de los `<script>`, `getElementById` de ids que no existen, librerías (THREE, jQuery, Phaser…) usadas sin cargarlas, módulos ES abiertos con doble clic, sintaxis, nombres y dependencias, y abre la página en un navegador invisible.
- **probar_web**: abre la web o el juego en Edge/Chrome **invisible** (sin instalar nada) y reporta errores de JavaScript con archivo:línea, archivos que no cargan, la consola, una captura (la IA la ve) y si la pantalla o el canvas quedan vacíos. Simula teclas, clics, arrastrar el mouse, rueda y texto, e indica si la imagen cambió (¿los controles funcionan?).
- **Diagnóstico automático**: si dices «no funciona», «revisa», «arregla»…, Noviark diagnostica el proyecto antes de que la IA empiece y le entrega los errores reales como punto de partida.
- El **agente de pruebas final** también abre las webs en el navegador invisible antes de dar el trabajo por terminado.

### ✏️ Archivos más seguros
- **Corregido**: los archivos en ANSI (guardados por PowerShell) se leían como UTF-16 y la IA veía «caracteres chinos», creía que el archivo estaba dañado y lo reescribía. Ahora la codificación se detecta bien y se avisa.
- **editar_archivo** tolera lo que suelen equivocar las IAs pequeñas: números de línea copiados, espacios, sangría, líneas en blanco, escapes dobles y pequeñas diferencias (≥ 90 %). Si falla, muestra las líneas reales con sus números para copiar o usar `desde_linea/hasta_linea`. Nuevo modo `despues_de_linea` para insertar.
- **escribir_archivo** avisa si un archivo se encoge de golpe (¿se borró código?) o si quedó con «...» en vez de código.
- **PowerShell** ya no puede escribir archivos de código con here-strings (`Set-Content @"…"@`), que rompían comillas, `$variables` y la codificación; guarda en UTF-8 y respalda los archivos que un comando menciona, así **deshacer_cambio** siempre puede volver atrás (también con copias de trabajos anteriores).

## Novedades de la versión 4.2

### ✅ La lista de modelos muestra solo los que funcionan (y primero los mejores)
- Arriba aparece «⭐ Los mejores que funcionan con tus claves» (ya probados), y cada modelo tiene una línea en palabras simples: muy inteligente, programa bien, rápido, gratis, ve imágenes… y para qué sirve.
- Si tienes **varias API keys** (por ejemplo dos cuentas de NVIDIA), Noviark prueba cada modelo con todas y usa la clave que funcione con ese modelo. En ⚙ Ajustes → Proveedores, «🩺 Probar cada clave» dice cuál funciona. Al cambiar tus claves se vuelve a probar todo.
- Un **agente verificador** (sin IA) prueba en segundo plano, con un mensaje mínimo y respetando los límites gratuitos, qué modelos responden de verdad con tu cuenta (NVIDIA lista muchos que tu cuenta no puede usar). Cada modelo queda ✅ verificado, ❔ sin verificar o ⛔ no operativo con su motivo.
- Por defecto se ocultan los que no funcionan («✅ Solo los que funcionan»); «🔎 Verificar todos» los vuelve a probar.
- Al final de la lista aparecen las IAs gratis que aún no conectaste, con **🔑 Conseguir clave gratis** y un campo para pegarla ahí mismo.

### 🆓 Más IA gratis
- **Sin cuenta ni clave**: Kilo Gateway (modelos «:free»), LLM7 y OVHcloud AI Endpoints: se activan con un clic.
- **Con cuenta gratis (sin tarjeta)**: Z.ai (GLM Flash), Cloudflare Workers AI, Cohere, Aion Labs, Pollinations, Ollama Cloud (modelos grandes procesados en su nube), Vercel AI Gateway, además de los que ya había.
- **Tu servidor GPU gratis en la nube (Kaggle)**: Noviark genera un cuaderno listo; Kaggle pone 2 GPU T4 (32 GB) y la IA corre allá, no en tu PC.

### 🧠 Plan en vivo que puedes editar
Mientras la IA diseña el plan lo ves en el panel lateral (pestaña 🧠 Plan). Al terminar tienes **30 segundos** para revisarlo: si no haces nada se aprueba solo; si empiezas a editar (tareas, tecnología, archivos) la cuenta se detiene hasta que pulses «Aprobar». También puedes descartarlo.

### ✍ Escritura en vivo y enlaces clicables
- Pestaña **✍ En vivo**: ves lo que la IA va escribiendo en cada archivo (o el código/comando que prepara) mientras lo escribe.
- Las rutas de tu PC que aparecen en las respuestas (C:\...) se pueden pulsar: los archivos se abren en el visor y las carpetas en el explorador (Ctrl+clic = Explorador de Windows).

### 🗂 Cada proyecto con su pantalla y su propia IA
Al elegir un proyecto se abre su pantalla: sus chats (con los que están trabajando), acciones (nuevo chat, archivos, probar y corregir, estado) y **la IA de ese proyecto**. Cada proyecto puede usar una IA distinta y todos pueden trabajar a la vez. Pulsar Enter mientras la IA trabaja ya no la detiene.

### 🧰 Herramientas nuevas para la IA
- **ejecutar_linux** (Linux/WSL dentro de Windows, apt como root), **contenedor** (Docker aislado), **entorno** (entornos virtuales .venv / Node, qué está instalado, instalar Linux), **instalar_herramienta** (agente instalador con winget/apt/pip/npm), **puntos_restauracion** (se crean solos antes de cada trabajo; volver atrás si algo se rompe, sin tocar tu .git), **peticion_http** (probar APIs y servidores).
- **Pruebas como un programador**: el agente de pruebas ahora **ejecuta el programa** (prueba de humo). Si arranca y sigue funcionando (ventana o servidor) sin errores = OK; si falla, pasa a la IA el archivo y la línea para corregirlo solo.
- **Agente de seguridad**: detecta claves API escritas en el código y pide moverlas a un .env.

### ⚖ Decisor «System One» (inspirado en Jev, septiembre 2026)
Decisiones rápidas y tipadas en los puntos clave: ¿este comando es peligroso?, ¿el pedido necesita plan?, ¿qué tan complejo es?, ¿qué tipo de error es? Lo peligroso (borrar carpetas, formatear, apagar, git push --force…) **se pregunta siempre**, aunque estés en ⚡ Todo automático. El modo «🛡 Auto seguro» ahora solo pregunta lo riesgoso. Si pones una clave de **Jev (TypeSafe)** se usa ese modelo; sin clave decide con reglas locales gratis.

## Novedades de la versión 4.1 (y 4.0)

### 🧠 Modo vanguardia: siempre los modelos gratis más inteligentes
- En la lista de modelos: **«🧠 Usar siempre los más inteligentes gratis»** prueba los modelos gratuitos de mayor razonamiento que tengas conectados, pone el mejor que responda como principal y los siguientes como respaldo (de empresas distintas, para que si una se agota siga otra).
- **Cerebro planificador**: antes de construir un programa, el modelo más inteligente diseña el plan completo (tecnología, archivos, tareas, pruebas) con razonamiento alto. Luego la IA de trabajo (aunque sea local) lo ejecuta paso a paso. Se configura en 🎁 IA gratis → Modo vanguardia.
- Etiquetas en la lista: 🚀 vanguardia, 🧠 razonamiento muy alto, 🆓 gratis. El globo informativo muestra también el razonamiento y el costo.

### 🩺 IAs no operativas: motivo y solución
- Si un modelo o proveedor falla, Noviark dice **por qué** y **cómo arreglarlo**: 🔑 clave inválida o faltante, ⛔ modelo no disponible para tu cuenta (el error de NVIDIA «Function not found for account»), 💳 sin crédito, ⏳ límite alcanzado, ⬇ modelo local no descargado, 💾 no cabe en tu memoria, 🔌 Ollama/LM Studio cerrado.
- Esos modelos aparecen **tachados con el motivo** en la lista y Noviark los **salta solo**, pasando al siguiente modelo que funcione **sin perder el trabajo** (se reintentan solos más tarde).
- «🩺 Verificar» en la lista de modelos comprueba cuáles responden de verdad. Una barra arriba avisa si alguna clave dejó de funcionar.
- Arreglado: el 404 de NVIDIA ya no se confunde con «no acepta herramientas».

### ⏳ Ver qué está haciendo la IA (con cronómetro)
Debajo del chat se ve la fase actual y cuánto lleva: 📦 cargando el modelo en memoria (IA local), 📖 leyendo el contexto, 💭 pensando, ✍ respondiendo, 🛠 usando una herramienta. Si la carga tarda demasiado, avisa que el modelo puede ser muy grande para tu PC.

### ⚡ Varios proyectos a la vez
Cada conversación trabaja en su propio hilo: puedes dejar una IA trabajando en un proyecto, abrir otro proyecto (o chat) y trabajar con otra IA al mismo tiempo. Las que siguen trabajando tienen un punto verde en la barra lateral; al volver a ellas ves su progreso en vivo. Te avisa cuando una termina o necesita tu permiso. En la pantalla de proyectos: filtro «Trabajando ahora».

### 🧬 Agentes que aprenden solos
Cuando algo falla y la IA lo arregla, Noviark guarda qué error era y qué lo solucionó. La próxima vez que aparezca ese error (en cualquier proyecto y con cualquier IA) le pasa la solución que ya funcionó; las lecciones más probadas se vuelven reglas. También aprende qué paquete instalar para cada módulo de Python. Todo es a prueba de fallos y se puede revisar o borrar en **🧬 Aprendizaje**.

### 🖥 Control del PC y ⏰ tareas programadas
- La IA puede manejar tu escritorio con el **mismo método que el navegador**: lee la ventana (cada botón o campo tiene una referencia), actúa (abrir programas, clic, escribir, atajos) y verifica. Funciona sin instalar nada; opcionalmente activa **Windows-MCP** (más completo) en 🖥 PC y tareas. Siempre pide permiso antes de actuar, salvo en ⚡ Todo automático.
- **Tareas programadas**: una vez, cada día, ciertos días o cada N minutos. También puedes pedírselo a la IA («cada lunes a las 9 revisa mi proyecto y corre las pruebas»). Se ejecutan mientras Noviark esté abierto; activa «Iniciar Noviark con Windows» para que siempre lo esté.

### 🗂 Proyectos a pantalla completa
La pantalla de proyectos ocupa toda la ventana, con vista de tarjetas o lista, estadísticas y filtro de los que están trabajando.

### 🎁 IA gratis (legal)
Botón **🎁 IA gratis** en la barra lateral:
- **OpenRouter** se conecta **con un clic**: inicias sesión en su web y Noviark recibe la clave solo. Por defecto muestra solo los modelos «:free».
- Para **NVIDIA, Gemini, Groq, Cerebras, Mistral y Hugging Face** hay un botón que abre la página oficial para crear la cuenta y la clave gratuita. La pegas y Noviark la guarda cifrada, activa el proveedor y lo prueba.
- Si activas varios, el **respaldo automático** pasa de uno a otro cuando alguno llega a su límite gratuito.
- Noviark **no** automatiza las webs de pago (ChatGPT, Claude.ai, Gemini web…): va contra sus condiciones y podrían bloquear tus cuentas.

### 💻 IA local que ya no pierde el hilo (Ollama y LM Studio)
**Por qué la IA local empezaba de cero:** Ollama usa por defecto un contexto de solo **4096 tokens**. Las instrucciones, las herramientas y el historial no cabían, Ollama recortaba el inicio de la conversación y el modelo olvidaba el plan. Noviark lo resuelve así:
- **Contexto a la medida de tu equipo:** Noviark habla con Ollama por su API nativa y fija el contexto (`num_ctx`) en cada petición. Lo calcula según tu **VRAM (16 GB)**, tu **RAM (32 GB)**, el tamaño del modelo y lo que ocupa su memoria por token. Con LM Studio lee el contexto cargado y, si el modelo no está cargado, lo carga con uno adecuado.
- **Modo compacto paso a paso** (automático con IA local):
  - la IA trabaja **una tarea a la vez**;
  - al terminar cada tarea, el orquestador «limpia la mesa» y le da solo lo necesario para la siguiente: el estado, el mapa del código y la tarea;
  - si se queda sin actuar, se lo recuerda;
  - si repite la misma acción, la frena (detector de bucles).
- **Memoria compacta y selectiva:**
  - un **mapa del código** ultracompacto (funciones y clases con su número de línea), hecho sin IA a partir del código;
  - el **ESTADO del trabajo** siempre al inicio;
  - solo los últimos resultados de herramientas completos: los anteriores se resumen en una línea (enmascarado de observaciones: según un estudio de JetBrains en NeurIPS 2025, ahorra ~50 % de tokens sin perder calidad);
  - herramientas reducidas a 15 con descripciones cortas (≈1.900 tokens en vez de ≈4.600).
- **Medidor de contexto** bajo el chat: cuántos tokens usa cada petición y de cuántos dispone el modelo.
- **⚙ Ajustes → IA local:** VRAM, RAM, contexto, razonamiento, pasos, y el botón **⚡ Optimizar Ollama para mi GPU**. Ese botón activa flash attention, caché KV q8 (la mitad de memoria), un solo modelo a la vez y keep-alive de 30 min. Luego hay que reiniciar Ollama.

**Modelos recomendados para 16 GB VRAM + 32 GB RAM:**
- **qwen3-coder:30b**: el mejor para programar en local. Es MoE, así que aunque use algo de RAM va bien.
- **gpt-oss:20b** y **devstral**: alternativas.
- **qwen3-vl:4b**: ayudante de visión local.
- **deepseek-r1** solo para razonar: gasta muchos tokens pensando y usa mal las herramientas.

### 🧰 Agentes auxiliares sin IA (scripts que trabajan por la IA)
- **🧪 Agente de pruebas:** revisa sintaxis (Python, JS, JSON, PowerShell), nombres no definidos (pyflakes), archivos enlazados que no existen en HTML y dependencias faltantes, y ejecuta las pruebas (pytest y los comandos del proyecto). Entrega un **reporte mínimo**: archivo:línea, 3 líneas de código, la causa y una pista concreta. Si falla una prueba, señala también **la función probada**, que es donde suele estar el error. Revisa solo los archivos recién cambiados tras cada paso y todo el proyecto al final: si algo falla, le pasa el reporte a la IA para que corrija solo esas líneas (hasta 4 rondas).
- **📦 Agente de dependencias:** instala solo los módulos que faltan (sabe que `cv2` es `opencv-python`, `PIL` es `pillow`, etc.).
- **🗺 Agente indexador:** mantiene el mapa del código en `.noviq/indice.json` y solo vuelve a leer los archivos que cambiaron.
- **🧭 Orquestador:** guía a la IA local tarea por tarea.
- **🔁 Detector de bucles:** detiene a la IA si repite lo mismo sin avanzar.
- Siguen activos el **agente ejecutor de código**, el **agente navegador** y el **analizador visual**.

### 📂 Proyectos que ya tienes en tu PC
Botón **▦ → 📂 Abrir proyecto existente** o **Elegir…** (abre el selector de carpetas de Windows). Noviark detecta el tipo (Python, Node, web, C#, Java, Android, Flutter, Arduino, PHP) y cómo ejecutarlo y probarlo. La IA trabaja ahí igual que en un proyecto propio. Si el proyecto tiene su propio `.venv`, Noviark usa ese Python. Tus archivos no se mueven. Con ✖ lo quitas de Noviark sin borrar nada.

### ▦ Pantalla de proyectos
Todos tus proyectos, **los más recientes primero**, con búsqueda, orden y filtro (creados en Noviark o existentes en tu PC). Desde cada tarjeta: 💬 Trabajar, ↩ Último chat, 📁 Archivos, 🧪 Probar (la IA revisa y corrige todo), 📂 carpeta y ✎ instrucciones.

### 📁 Explorador de archivos y editor
- En el panel derecho, la pestaña **📁 Archivos** muestra el árbol del proyecto. Puedes **arrastrar y soltar** para mover, y con clic derecho: abrir, editar, renombrar, crear, enviar a la papelera, mostrar en el Explorador o «pedir a la IA que lo revise».
- **✏ Editar** abre un editor de código real (colores por lenguaje, números de línea, cierre de paréntesis, buscar con Ctrl+F). **Ctrl+S** guarda y deja antes una copia de respaldo.

### 🎈 Elegir modelo con globo informativo
Pulsa el nombre del modelo, arriba a la izquierda. Al pasar el mouse sobre cada uno aparece un globo con:
- para qué sirve;
- ★ programación, inteligencia y velocidad;
- consumo de tokens;
- si usa herramientas y si ve imágenes;
- tamaño y si **cabe en tu GPU**;
- contexto.

Arriba del listado hay atajos **«¿Cuál elijo?»**: mejor para programar, para programar en local, agente autónomo, ver imágenes, razonar, y rápido y económico.

## Novedades de la versión 3.0

### 👥 Equipo de IAs
- **`planificar_en_equipo`**: tres IAs (arquitecto, experto en calidad y riesgos, desarrollador pragmático) proponen planes a la vez, si es posible con modelos de proveedores distintos. La IA principal, que hace de coordinadora, combina lo mejor de cada una en un plan final.
- **`trabajar_en_equipo`**: la coordinadora reparte las tareas independientes entre varios agentes que trabajan **en paralelo**, cada uno con su propio modelo y **sus archivos asignados**, para que no se pisen. Al final ella integra, prueba y corrige.
- En ⚙ Ajustes → Agentes eliges cuántos agentes trabajan en paralelo (1-4).

### 🤖 Agente ejecutor de código
Si la IA escribe el código en el chat en vez de usar herramientas, el agente ejecutor reconoce cada bloque (inicio, fin, lenguaje y nombre de archivo), **guarda los archivos** en el proyecto (creándolo si hace falta) y **ejecuta los comandos** con tu permiso. Luego devuelve los resultados a la IA para que siga con su plan. Si el código es solo un fragmento de un archivo que ya existe, no lo pisa. Se configura en ⚙ Ajustes → Agentes.

### 🌐 Control de Chrome y Edge
En 🔌 MCP pulsa **«Activar Google Chrome»** o **«Activar Microsoft Edge»**. Necesitas **Node.js** (https://nodejs.org, versión LTS). Después:
- la IA delega las tareas web en un **agente navegador**: abre páginas, hace clic, llena formularios y lee datos. Funciona aunque la IA principal no sepa usar herramientas, porque usa un modelo auxiliar que sí sabe. También ahorra tokens: las ~25 herramientas del navegador solo se envían a ese agente.
- **Plan de respaldo**: si no hay control de navegador o falla, la IA te pide los pasos con **🙋 La IA necesita tu ayuda**. Tú los haces, pegas capturas (Ctrl+V) y respondes.

### 👁 Visión automática para cualquier modelo
Si el modelo que usas **no puede ver imágenes**, el programa lo detecta y un modelo con visión (Gemini, GLM-5.3, Llama-4, GPT-4o…) analiza la captura a fondo: qué es, el texto exacto de los errores, la causa probable y posibles soluciones. Ese resumen se le envía a tu IA. Una imagen cuesta miles de tokens y el resumen unos cientos, y cada análisis se guarda para no repetirlo. Puedes fijar el modelo de visión en ⚙ Ajustes → Agentes.

### ✏️ Corrección quirúrgica de archivos
- **`localizar_error`**: lee la traza del error (Python, JS/TS, C#, Java, PowerShell, PHP…) y muestra el archivo y la línea exacta con el código alrededor.
- **`mapa_codigo`**: lista las funciones y clases de cada archivo con su número de línea, para saber qué tocar sin leerlo todo.
- **`editar_archivo`**: cambia solo lo necesario. Admite varias ediciones en una llamada, rangos de líneas y tolera diferencias de sangría.
- **Protección**: no deja reescribir por completo un archivo grande que ya existe; obliga a editar solo las partes con errores.
- **Copias de respaldo** automáticas antes de cada cambio, y **`deshacer_cambio`** para volver atrás.

## Proyectos
- Cuando pides un programa, la IA crea su carpeta con **PowerShell** en **Documentos\Noviq_Proyectos\<Nombre>**. Cada tipo de proyecto (python, web, node, java, csharp, arduino, android, datos, documentos) lleva sus subcarpetas, README, .gitignore y git.
- Cada proyecto guarda en su carpeta oculta `.noviq`:
  - `memoria.md`: decisiones, estado y cómo ejecutarlo. La IA lo va actualizando.
  - `bitacora.md`: registro de todo lo que se hizo en el proyecto.
- Con ✎, junto al nombre del proyecto, puedes darle **instrucciones propias** (ej. "usa Tkinter y comenta en español").

## Herramientas de la IA
| | |
|---|---|
| 🗂 crear_proyecto / cambiar_proyecto | Carpeta propia para cada proyecto |
| 📄 escribir_archivo / ✏️ editar_archivo | Crea archivos completos y hace cambios puntuales, mostrando las diferencias |
| 📖 leer_archivo | Código, PDF, Word, Excel e imágenes |
| 📁 listar / 🔍 buscar_archivos / buscar_en_archivos | Explorar y buscar texto, como grep |
| 📦 mover_o_copiar / 🗑 eliminar | Eliminar envía a la **Papelera de reciclaje** |
| ⚡ ejecutar_powershell | Salida en vivo. Los servidores pueden ir en segundo plano |
| 🐍 ejecutar_python | Gráficos, Excel, Word, PDF, datos. Muestra los archivos que crea |
| ⚙ procesos | Ver la salida de los procesos en segundo plano o detenerlos |
| 🩺 diagnosticar | Lista priorizada de problemas reales del proyecto (codificación, código incompleto, HTML↔JS, sintaxis, navegador) |
| 🌐 probar_web | Prueba webs y juegos en un navegador invisible: errores, captura, teclas, clics y mouse |
| 🧪 probar_proyecto | Sintaxis, nombres, dependencias, pruebas y (en webs) el navegador invisible |
| 🔎 buscar_en_internet / 🌐 leer_pagina_web / ⬇ descargar_archivo | Internet |
| 🎨 generar_imagen | Dibuja con FLUX de NVIDIA |
| 🖥 captura_pantalla | La IA ve tu pantalla (con modelos que tienen visión) |
| ↗ abrir | Abre archivos o páginas en su programa o en el navegador |
| ✅ actualizar_tareas | Lista de tareas visible mientras trabaja |
| 🧠 memoria | Memoria del usuario y del proyecto |
| 🔌 MCP | Cualquier servidor MCP (mismo formato que Claude Desktop) |

**Vista previa**: las páginas HTML, imágenes, Markdown y código se ven en el panel derecho con 👁 Ver.

## Permisos (selector arriba a la derecha)
- **🔒 Preguntar**: pide permiso antes de PowerShell, Python, eliminar, capturas o escribir fuera de la carpeta de proyectos.
- **🛡 Auto**: solo pregunta antes de PowerShell, Python y eliminar.
- **⚡ Todo automático**: no pregunta nada. Úsalo con cuidado.

También puedes pulsar "Permitir siempre en esta conversación".

## Modelos que no soportan herramientas
El programa lo detecta solo. Si un modelo rechaza las herramientas nativas, cambia al **modo por texto** (funciona con cualquier modelo) y lo recuerda. También reconoce el razonamiento en `<think>` de DeepSeek-R1, Qwen y otros.

## Servidores MCP
En **🔌 MCP** pegas la configuración (igual que en `claude_desktop_config.json`), por ejemplo:
```json
{ "mcpServers": {
    "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/TU_USUARIO/Desktop"] }
} }
```
Para servidores con `npx` necesitas Node.js y para los de `uvx`, uv.

## Si venías de «Rurak» o «NVIDIA Chat»
Copia la carpeta `datos` de la versión anterior dentro de la carpeta de Noviark: conservas tus claves (la bóveda sigue funcionando), tus conversaciones y tu memoria. La carpeta de proyectos se renombra sola a `Noviq_Proyectos`, y en cada proyecto `.noviq` pasa a `.noviq`.

## Archivos del programa
- `datos/claves.vault`: claves cifradas. **No lo compartas.**
- `datos/config.json`: ajustes (sin claves).
- `datos/conversaciones/`: historial.
- `datos/memoria.md`: tu memoria personal.
- `datos/mcp.json`: servidores MCP.

## Problemas comunes
- **401/403**: clave incorrecta o vencida. **404**: el modelo ya no existe; elige otro.
- **429**: límite de uso. Pon varias claves o configura el respaldo.
- **Ollama/LM Studio "no está abierto"**: abre el programa. En LM Studio, además, inicia el servidor.
- **Imagen bloqueada**: el filtro de NVIDIA bloquea algunas palabras comunes; la IA reintenta con otras.
- **Puerto ocupado**: `set NVIDIA_CHAT_PORT=7861` antes de iniciar.

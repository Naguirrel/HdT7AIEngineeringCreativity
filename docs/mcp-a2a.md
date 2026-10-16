# Integracion MCP y A2A — Parachute S.A.

## Estado de esta entrega

Implementacion agregada al ZIP original. La sintaxis Python fue comprobada;
la ejecucion con SDKs, las pruebas pytest y una conversacion con el proveedor
LLM estan **pendientes de verificacion**. El entorno de desarrollo no pudo
instalar las dependencias: pip no encontro distribuciones accesibles para MCP
ni A2A. No se generaron resultados de pruebas ni videos ficticios.

La documentacion historica del README describe la hoja HDT6; sus resultados no
prueban esta integracion. Tampoco se hicieron commits, push ni cambios al repositorio
remoto: el ZIP recibido no incluye .git.

## Arquitectura

Terminal A2A → servidor A2A → supervisor central → especialistas → MCP HTTP → servicios.

- `src/protocols/terminal.py`: cliente A2A real del SDK. Descubre la Agent Card,
  muestra las skills y conserva el contextId entre mensajes. No importa Runner,
  herramientas de negocio ni configuracion LLM.
- `src/protocols/a2a_server.py`: publica un agente con skills FAQ, clima y reservas;
  serializa mensajes de la misma conversacion y mantiene historiales separados.
- `src/protocols/remote_system.py`: reutiliza instrucciones y fabricas de los tres
  especialistas existentes. Sustituye sus cuatro herramientas por proxies que
  llaman al cliente `MCPServerStreamableHttp` del OpenAI Agents SDK. Los IDs MCP
  se inyectan fuera del modelo y no se incluyen en sus esquemas ni historial.
- `src/protocols/mcp_server.py`: unico servidor de herramientas; mantiene el
  contexto de negocio, las aprobaciones y un calendario comun a las conversaciones.
  Reutiliza los servicios, politicas y funciones del proyecto original.

La reserva automatica y el grounding de `finish_turn` tambien se ejecutan en
MCP. Esto evita tener un segundo calendario o crear citas directamente desde
el proceso A2A. Los logs `business_execution` incluyen herramientas invocadas
por esos hooks, ademas de las invocaciones MCP directas.

Las tres arquitecturas y CLIs anteriores se conservan para las evaluaciones
historicas. **Para esta tarea se utiliza la nueva terminal A2A**: ejecutar las
CLIs anteriores no demuestra la integracion. El sistema expuesto por A2A utiliza
la arquitectura centralizada con sus tres especialistas, no un bot de eco.

## Versiones

El adaptador MCP apunta a `mcp==2.2.0`, ya presente en el lock original.
A2A se fija en `a2a-sdk==0.3.24` (protocolo A2A 0.3) y utiliza sus clases
`A2AStarletteApplication`, `ClientFactory`, `Message` y `AgentCard`.
Las paginas `/latest/` de A2A ahora muestran APIs 1.0 incompatibles. No mezclar
esos ejemplos con este codigo ni actualizar solo el paquete A2A sin migrar
servidor y cliente juntos. La consigna no exige una version A2A especifica.
Las versiones aqui fijadas aun necesitan resolverse y verificarse juntas.

## Preparacion en Windows / PowerShell

Trabajar desde la raiz del proyecto, preferiblemente en un entorno nuevo:

```powershell
python -m venv .venv-protocols
.\.venv-protocols\Scripts\Activate.ps1
python -m pip install -r requirements-protocols.txt
python -m pip check
```

Si `pip` falla, detenerse y compartir el error completo; no continuar como si las
dependencias estuvieran instaladas. No sustituir versiones arbitrariamente.
`requirements.lock.txt` conserva el entorno historico: **no incluye A2A**.
Para esta integracion se instala `requirements-protocols.txt`.

Si todavia no existe `.env`, copiar `.env.example` a `.env` y configurar el
proveedor compatible con Chat Completions. No sobrescribir un .env existente.
El servidor A2A lo carga automaticamente (`override=False`): las variables de
entorno ya definidas tienen prioridad. No mostrar el archivo durante el video.
MCP y la terminal no requieren API key.

## Ejecutar en tres terminales

Abrir tres ventanas desde la raiz y activar el mismo entorno en cada una.

**Terminal 1 — MCP:**

```powershell
python -m src.protocols.mcp_server
```

Escucha en `http://127.0.0.1:8001/mcp`, exclusivamente con Streamable HTTP.
No se usa stdio ni el transporte SSE antiguo. Streamable HTTP puede devolver
respuestas SSE como parte de su propio protocolo; eso no cambia el transporte.

**Terminal 2 — A2A:**

```powershell
python -m src.protocols.a2a_server
```

Escucha en `http://127.0.0.1:8000/`. Se puede abrir en el navegador:
`http://127.0.0.1:8000/.well-known/agent-card.json`.
La card debe mostrar un agente Parachute S.A. y tres skills.

**Terminal 3 — cliente:**

```powershell
python -m src.protocols.terminal
```

Debe descubrir el agente y mostrar sus skills. Escribir varias preguntas y
salir con `Bye` o Ctrl-C. La CLI original sigue disponible para evaluaciones
anteriores, pero la que se graba es `src.protocols.terminal`.

Puertos opcionales:

```powershell
python -m src.protocols.mcp_server --port 8101
python -m src.protocols.a2a_server --port 8100 --mcp-url http://127.0.0.1:8101/mcp
python -m src.protocols.terminal --url http://127.0.0.1:8100
```

Estos comandos se ejecutan en terminales separadas, no consecutivamente en una.

## Pruebas automaticas

```powershell
python -m pytest -q -p no:cacheprovider tests/protocols
python -m pytest -q -p no:cacheprovider
```

La suite de protocolos levanta servidores HTTP reales en puertos disponibles,
usa el modelo guionado existente del proyecto y fixtures meteorologicos.
No llama al proveedor LLM ni a Open-Meteo real. Cubre descubrimiento MCP,
consulta FAQ, aislamiento de sesiones, orden de aprobaciones, rechazo de clima
prohibido, confirmacion marginal en dos turnos, finalizacion remota, consultas
combinadas y el camino terminal → A2A → multiagente → MCP.
Si falta A2A, el modulo se omite: **una prueba omitida no cuenta como aprobada**.
El test historico de Git requiere ejecutar la suite dentro del checkout real;
un ZIP extraido sin `.git` no cumple esa precondicion.

Para verificar en el repositorio de GitHub: copiar los archivos agregados sobre
una rama de trabajo del checkout, instalar dependencias y ejecutar las pruebas.
No se cambio el YAML de Promptfoo ni sus assertions; no hace falta una corrida
LLM de evaluaciones para comprobar solo el transporte. Las evaluaciones HDT6
pendientes siguen siendo pendientes.

## Pruebas manuales y video

1. Mostrar las tres terminales y sus comandos de arranque.
2. Mostrar la Agent Card y las tres skills.
3. Preguntar `¿Cual es el limite de peso?`. Verificar respuesta desde FAQ, logs
   A2A `request_received` / `response_ready` y logs MCP `search_faq`.
4. Preguntar por clima para una fecha entre hoy y el horizonte de 15 dias.
   Mostrar `check_jump_day` en MCP. El resultado depende del clima real.
5. Solicitar una reserva con fecha valida, nombre ficticio y correo ficticio.
   Si es IDEAL, deben verse clima → disponibilidad → creacion. Si es MARGINAL,
   solicitar la confirmacion y escribir `Acepto tandem experimentado` en otro
   mensaje; si es PROHIBITED, comprobar que no existe creacion exitosa.
6. Hacer otra pregunta en la misma terminal para demostrar continuidad y salir
   con `Bye`. No grabar API keys ni datos personales reales.

Ejemplo de reserva: `Reserva el FECHA para Ana Ejemplo, ana@example.invalid,
somos 2 personas.` Sustituir FECHA por YYYY-MM-DD vigente.

Para demostrar una reserva reproducible sin depender del clima real, reiniciar
MCP con el modo de prueba explicito:

```powershell
python -m src.protocols.mcp_server --demo
```

El banner indica **DEMO_FIXTURES**, fecha fija 2026-09-17 y clima IDEAL. Usar:
`Reserva el 2026-09-20 para Ana Ejemplo, ana@example.invalid, somos 2 personas.`
A2A y el modelo LLM siguen siendo reales; solo clima/reloj son fixtures.
Explicar esto en el video; no presentar esa fecha pasada como clima real.
La suite automatica verifica MARGINAL y PROHIBITED con otros fixtures.

## Logs y limites

MCP registra herramienta, inicio/final, duracion, errores por tipo y ejecucion
de negocio con estado. A2A registra recepcion, respuesta y errores por tipo.
No se registran mensajes, API keys, nombres ni contactos. Las exportaciones de
trazas del SDK siguen desactivadas.

Servidores locales en loopback, sin autenticacion; usar un proceso/worker por
servidor. No desplegar estas sesiones en memoria con multiples workers.
El calendario se pierde al reiniciar MCP. Las sesiones MCP vencen tras una hora
inactiva; el historial A2A tras 30 minutos. Las sesiones estan limitadas a 128 y
el historial enviado al modelo a los ultimos 20 turnos; el estado de negocio
se conserva hasta que vence la sesion. Los IDs opacos de contexto son para
continuidad y no sustituyen autenticacion en un despliegue publico.

Si falla el proveedor o MCP, se devuelve un mensaje generico y se registra el
tipo de error. No se garantiza recuperacion automatica despues de reiniciar
MCP: reiniciar el cliente para abrir una conversacion nueva.

## Fuentes oficiales

- https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server
- https://py.sdk.modelcontextprotocol.io/run/asgi/
- https://openai.github.io/openai-agents-python/mcp/
- https://a2a-protocol.org/latest/
- https://pypi.org/project/a2a-sdk/0.3.24/

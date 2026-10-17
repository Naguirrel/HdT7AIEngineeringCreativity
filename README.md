# HDT7 — Parachute S.A. con MCP y A2A

La Hoja de Trabajo 7 conecta una terminal A2A con el supervisor central y sus
especialistas. Las herramientas de FAQ, clima, disponibilidad y reservas se
ejecutan en un servidor MCP separado. Ese proceso mantiene el calendario
compartido en memoria y aplica las reglas de negocio antes de crear una cita.

## Estado de esta versión

La integración MCP/A2A está implementada en este proyecto original, pero sus
pruebas y el flujo con proveedor LLM real siguen **pendientes de verificación en
este checkout**. La [guía de MCP y A2A](docs/mcp-a2a.md) describe la arquitectura,
los casos de prueba y el video. Los resultados históricos de HDT6, más abajo,
corresponden a la arquitectura anterior.

## Instalar HDT7 en PowerShell

Abre PowerShell en la raíz de este proyecto y crea un entorno dedicado. El
archivo `requirements-protocols.txt` incluye las dependencias de la aplicación
y agrega `mcp`, `a2a-sdk` y los paquetes de transporte HTTP. Ejecutar con el
Python global o con un `.venv` anterior puede producir `ModuleNotFoundError: No
module named 'mcp'`.

```powershell
python -m venv .venv-protocols
& '.\.venv-protocols\Scripts\python.exe' -m pip install -r requirements-protocols.txt
& '.\.venv-protocols\Scripts\python.exe' -m pip check
```

Comprueba que el módulo se instaló en ese mismo entorno:

```powershell
& '.\.venv-protocols\Scripts\python.exe' -c "import mcp, a2a; print('MCP y A2A disponibles')"
```

El servidor A2A requiere `LLM_API_KEY`, `LLM_BASE_URL` y `LLM_MODEL` válidos.
Configúralos como variables de entorno o en un `.env` local basado en
`.env.example`. No compartas la clave ni sobrescribas un `.env` existente.
MCP y la terminal no necesitan esa clave.

## Ejecutar MCP, A2A y la terminal

Abre tres ventanas de PowerShell en la raíz del proyecto. Usa el ejecutable
del entorno dedicado en cada una y deja abiertos los dos servidores:

```powershell
# Ventana 1: servidor MCP
& '.\.venv-protocols\Scripts\python.exe' -m src.protocols.mcp_server --port 8101

# Ventana 2: servidor A2A; requiere el proveedor LLM configurado
& '.\.venv-protocols\Scripts\python.exe' -m src.protocols.a2a_server --port 8100 --mcp-url http://127.0.0.1:8101/mcp

# Ventana 3: cliente que descubre la Agent Card y conserva la conversación
& '.\.venv-protocols\Scripts\python.exe' -m src.protocols.terminal --url http://127.0.0.1:8100
```

La Agent Card se publica en
`http://127.0.0.1:8100/.well-known/agent-card.json`. Para usar clima IDEAL
simulado y un reloj fijo (`2026-09-17`), agrega `--demo` al comando MCP. Esta
versión original no ofrece `--scripted` ni variantes de `--demo`: A2A sigue
requiriendo un proveedor LLM incluso cuando MCP usa el fixture.

## Pruebas de HDT7

Después de instalar las dependencias, ejecuta:

```powershell
& '.\.venv-protocols\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests/protocols
& '.\.venv-protocols\Scripts\python.exe' -m pytest -q -p no:cacheprovider
```

Estas pruebas no se han ejecutado en este checkout. Su resultado debe revisarse
antes de afirmar que la hoja está completa. Consulta también la
[guía de MCP y A2A](docs/mcp-a2a.md) para las verificaciones manuales.

# HDT6 — Antecedentes y evaluación con Promptfoo

Este repositorio parte del proyecto HDT5 (orquestación multiagente) y lo amplía
para la hoja HDT6. Contiene tres arquitecturas de agentes (centralizada,
jerárquica y descentralizada) que resuelven el mismo problema de Parachute S.A.:
responder FAQs del evento y gestionar citas de salto validando el clima. Las tres
reutilizan el mismo núcleo de dominio, integraciones, herramientas y garantías;
solo cambia la estrategia de orquestación. La hoja HDT6 evalúa con Promptfoo la
arquitectura **centralizada**.

`docs/analisis-arquitecturas.md` y su PDF son el entregable histórico de HDT5 y
se conservan sin cambios.

## Demo en video (HDT5)

[Video demostrativo](https://youtu.be/vHEtqMTmSos) de las tres arquitecturas
contra Groq y Open-Meteo reales, grabado en HDT5 antes de las correcciones de
HDT6.

## Garantías implementadas en código (no solo en prompts)

- **Ninguna cita sin clima y cupo**: `create_appointment` exige una evaluación
  vigente de `check_jump_day` y una aprobación posterior de
  `check_appointment_availability` para la misma fecha, el mismo tamaño de
  grupo, el mismo día local y la misma sesión (estado y traza ordenada).
- **Respuesta veraz**: `finish_turn` elimina cualquier afirmación de cita
  confirmada, creada, registrada o reservada sin un registro real y añade el
  estado verdadero (clima, cupo, confirmación tándem y datos faltantes). Tras una
  creación real, la respuesta se deriva del registro.
- **Finalización determinista**: los datos que da el usuario (fecha, nombre,
  contacto y número de personas) se guardan en el contexto y sobreviven a los
  turnos y a `as_tool()`. Cuando el clima, la confirmación MARGINAL y los datos
  están completos, la reserva se completa con las herramientas reales desde
  `tool_use_behavior` o al cerrar el turno.
- **Confirmación tándem ligada a fechas**: se reconocen fechas ISO (con guiones
  Unicode), `DD/MM/YYYY`, `DD-MM-YYYY` y fechas en español. Una fecha distinta o
  ambigua nunca confirma. Reevaluar el mismo día con resultado MARGINAL conserva
  la confirmación; un cambio de fecha, de día local o de decisión, o un rechazo
  explícito, la revoca.
- **Validación en dominio**: nombre con al menos dos letras y sin caracteres de
  control ni payloads; contacto como correo válido, teléfono de Guatemala
  (8 dígitos, `+502` opcional) o E.164; `party_size` entero ≥ 1; fechas
  normalizadas una sola vez.
- **Capacidad por participantes** (8 por día, también máximo por reserva),
  revalidada de forma atómica. Un duplicado idéntico se reporta como
  `created: false, duplicate: true`; un duplicado con datos distintos es un
  conflicto.
- **Grounding determinista**: teléfonos, correos, URL, fechas, horas, números
  con unidad o moneda y nombres propios de la respuesta deben aparecer en las
  FAQ recuperadas en el turno, en las salidas de herramientas, en los mensajes
  del usuario o en la política publicada. Si no, se responde con el texto FAQ
  literal o con una abstención.
- **Recuperación FAQ** léxica con normalización, plurales, alias controlados,
  términos genéricos excluidos y prioridad de la sección de contacto. El corpus
  no se modificó.
- **Privacidad**: la traza usa HMAC-SHA256 con una clave efímera por sesión
  (nunca exportada). La metadata de Promptfoo solo contiene booleanos de
  identidad. La exportación de trazas del SDK está desactivada. Los errores
  mostrados al usuario son genéricos.
- **Datos meteorológicos inválidos** (NaN, infinito, negativos, nubes > 100 %,
  series vacías, unidades inesperadas) son errores, nunca IDEAL.

## Requisitos

- Python 3.12 y Node.js 22.22.0 o superior (verificado con Node 24.14.1).
- Docker y Docker Compose (opcional).
- Una API key compatible con OpenAI Chat Completions (por ejemplo, Groq) solo
  para ejecutar los agentes y las evaluaciones; las pruebas no la requieren.

## Variables de entorno

| Variable | Requerida | Descripción |
|---|---|---|
| `LLM_API_KEY` | sí (agentes y evals) | API key del proveedor compatible con OpenAI |
| `LLM_BASE_URL` | sí | URL base, p. ej. `https://api.groq.com/openai/v1` |
| `LLM_MODEL` | sí | Modelo del agente, p. ej. `openai/gpt-oss-20b` |
| `LLM_GRADER_MODEL` | para evals | Modelo del grader de `factuality`; el ejemplo es `qwen/qwen3.8-27b`, usado en corridas previas con Groq |
| `FAQ_PATH` | no | Ruta alterna al archivo de FAQs |

Configúralas en un `.env` local (copia de `.env.example`). **Nunca versiones ni
compartas `.env` ni claves**: `.env` está ignorado por Git y excluido del
contexto de Docker (`.dockerignore`). Una prueba automatizada lo verifica. Si
alguna vez construiste y compartiste una imagen Docker antes de este cambio,
rota la clave en el proveedor.

## Instalación

### Dependencias reproducibles

`requirements.txt` fija exactamente las dependencias directas.
`requirements.lock.txt` fija el entorno completo verificado (incluidas las
transitivas, con marcadores de plataforma).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock.txt
npm ci
```

Con Docker: `docker compose build` (instala `requirements.txt`).

### Preparación de PowerShell para Promptfoo

Cada terminal nueva necesita estas variables de sesión:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PROMPTFOO_PYTHON = (Resolve-Path ".\.venv\Scripts\python.exe").Path
$env:PROMPTFOO_CONFIG_DIR = Join-Path (Resolve-Path .venv).Path "promptfoo-state"
$env:PROMPTFOO_DISABLE_TELEMETRY = "1"
$env:TEMP = Join-Path (Resolve-Path .venv).Path "tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
& "$env:PROMPTFOO_PYTHON" -c "import sys, agents; print(sys.executable); print(agents.__file__)"
```

Si `PROMPTFOO_PYTHON` apunta fuera de `.venv`, Promptfoo falla con
`ModuleNotFoundError: No module named 'agents'`.

## Pruebas

```powershell
python -m pytest -q -p no:cacheprovider
npm run eval:validate
npm run test:assertions
```

La suite tiene **468 pruebas** deterministas (dominio, integraciones con
Open-Meteo simulado, herramientas, garantías y flujos reales del Agents SDK de
las tres arquitecturas con un modelo guionizado sin red). Ninguna llama a un LLM
ni a Internet. `test:assertions` evalúa, con el motor de regex de JavaScript que
usa Promptfoo, salidas buenas y malas para cada escenario; también lo ejecuta
pytest.

## Ejecutar cada arquitectura

Cada una abre un chat por terminal (`Bye` o `Ctrl-C` para salir) y requiere
credenciales reales.

```bash
python -m src.agents.centralized.main    # supervisor + especialistas via as_tool()
python -m src.agents.hierarchical.main   # Root -> Knowledge/Booking Manager -> especialistas
python -m src.agents.decentralized.main  # FAQ <-> Weather -> Scheduling via handoffs
```

Con Docker: `docker compose run --rm centralized` (o `hierarchical` o
`decentralized`).

### Alcance de las tres arquitecturas

| | Centralizada | Jerárquica | Descentralizada |
|---|---|---|---|
| Agente de entrada | Central Supervisor | Root Manager | FAQ Agent |
| Delegación | `as_tool()` a 3 especialistas | `as_tool()` a 2 managers, que delegan en especialistas | handoffs |
| Reglas críticas | `ENTRY_AGENT_RULES` | `ENTRY_AGENT_RULES` (Root) + reglas por manager | `ENTRY_AGENT_RULES` (FAQ) + reglas de reserva |
| Garantías de código | compartidas | compartidas | compartidas |
| Evaluada con Promptfoo | **sí** | flujos con modelo guionizado | flujos con modelo guionizado |

## Estructura

```
src/
  config.py              # coordenadas, horizonte, carga de variables
  domain/                # fechas, clima, citas y validaciones puras
  integrations/          # cliente de Open-Meteo (con validación de datos)
  services/              # WeatherService, CalendarService (in-memory), FaqService
  tools/                 # herramientas de negocio trazadas
  agents/
    common/              # contexto, políticas, finalización, veracidad, grounding, CLI
    centralized/         # arquitectura 1 + runner de evaluación
    hierarchical/        # arquitectura 2
    decentralized/       # arquitectura 3
evals/                   # Promptfoo: config, provider, escenarios, fixtures, assertions
tests/                   # unit, integration y agents (incluye modelo guionizado)
data/                    # FAQs oficiales (sin cambios)
```

## Reglas meteorológicas

Política determinista en `src/domain/weather_policy.py` ("peor condición
prevalece"):

| Variable | Ideal | Marginal | Prohibido |
|---|---|---|---|
| Viento en superficie | < 20 km/h | 20-28 km/h | > 28 km/h |
| Ráfagas | - | - | > 35 km/h |
| Precipitación | 0.0 mm | - | > 0.0 mm |
| Cobertura de nubes | < 30 % | 30-75 % | > 75 % |

MARGINAL solo permite tándem con instructor experimentado tras una confirmación
explícita del usuario. PROHIBITED nunca crea una cita. El horizonte válido va de
hoy a hoy + 15 días, en la zona `America/Guatemala`.

## Trazas y observabilidad

`context.get_tool_trace()` devuelve los eventos de las cuatro herramientas de
negocio (`search_faq`, `check_jump_day`, `check_appointment_availability`,
`create_appointment`) con `sequence`, `tool`, `arguments`, `result` y `status`.
Nombre, contacto y consulta FAQ se representan con HMAC por sesión. La metadata
exportada a Promptfoo elimina incluso esos seudónimos. Las delegaciones
`as_tool()` y los handoffs no forman parte de esta traza de negocio. El logging
local (`src/observability.py`) registra eventos `clave=valor` sin secretos ni
texto libre del usuario.

## Smoke test manual (consume cuota)

```bash
python -m scripts.smoke_test docs/smoke-test-output.txt
```

Usa el reloj de Guatemala, la misma finalización (`finish_turn`) que la CLI y la
evaluación, y cierra los clientes. `docs/smoke-test-output.txt` conserva la
corrida de HDT5.

## Evaluaciones con Promptfoo

El provider (`evals/provider.py`) construye el supervisor centralizado real en
cada caso, con contexto, historial, calendario (`calendar_fixture`), reloj fijo
(`2026-09-17`) y cliente meteorológico simulado (`weather_fixture`) nuevos. Nunca
consulta Open-Meteo real. La salida es la respuesta final. La `metadata` incluye
la traza, el contexto FAQ, las fechas consultadas, la confirmación tándem y
`identity_checks`.

### Comandos

```powershell
npm run eval:validate
npm run test:assertions
npm run eval:faq -- --env-file .env
npm run eval:booking -- --env-file .env
npm run eval:marginal -- --env-file .env
npm run eval:prohibited -- --env-file .env
npm run eval -- --env-file .env
npm run eval:report -- --env-file .env
npm run eval:view
```

- Las fases se eligen por `metadata.phase` con `--filter-metadata`, no por
  posición. Para un caso suelto:
  `npm run eval -- --filter-pattern "<descripción>" --env-file .env`.
- La concurrencia está fijada en **1** en `evaluateOptions` y en los scripts.
- El YAML fija `REQUEST_TIMEOUT_MS: 45000` y `maxRetries: 0` para el grader; el
  provider Python usa `timeout: 180000`.
- `eval:report` ejecuta una **nueva** corrida completa (`--no-cache`) y escribe
  `reports/promptfoo-report.html` y `reports/promptfoo-results.json`. Revisa
  esos archivos en busca de secretos antes de versionarlos.

### Casos y métricas

Hay **43 casos**: 14 FAQ y 29 de citas. Fases: `faq` 14, `booking` 16,
`marginal` 7 y `prohibited` 6. Cubren:

- **FAQ:** hechos del evento, lugar reformulado, embarazo, menor de 17 años,
  ropa, contacto, precio y seguro ausentes, fuera de dominio, saludo y
  despedida.
- **Citas:** reserva hoy, ideal, sin fecha, sin contacto, datos inválidos,
  grupo mayor a la capacidad, fecha pasada, hoy + 15 y hoy + 16, MARGINAL por
  viento y por nubes (sin confirmar, confirmado, fecha ISO o textual distinta,
  fecha textual correcta), PROHIBITED por viento, ráfagas, lluvia y nubes,
  error meteorológico, cupo agotado, reserva repetida, cambio de fecha, omisión
  de clima, prompt injection y solicitud combinada de cita y FAQ.

Tipos de assertion:

- `regex`, `contains` y sus negaciones verifican hechos y rechazan respuestas
  malas: confirmación falsa, precio o cobertura inventados, otros teléfonos o
  pesos, conocimiento general.
- La assertion `python` (`evals/assertions/tool_trace.py`) verifica:
  - presencia y ausencia de herramientas, conteos sobre éxitos y creación real;
  - orden como subsecuencia de eventos exitosos (se toleran errores intermedios
    inofensivos), y además que todo `create_appointment` exitoso siga, para la
    misma fecha, a un clima y una disponibilidad exitosos;
  - argumentos, resultados, identidad por booleanos y ausencia de Open-Meteo
    real.
- `factuality` permanece solo en `faq_place_date`: **como máximo 1 llamada al
  grader por corrida completa** (`maxRetries: 0`). No sustituye las
  verificaciones deterministas.
- `latency`: 60 000 ms en FAQ y 180 000 ms por defecto.

### Cómo clasificar resultados

- **ERROR (infraestructura):** cuota (`RateLimitError`), timeouts, worker,
  configuración o credenciales. No es un fallo del agente. El provider reporta
  `Proveedor LLM: …`, `Configuracion: …`, `Escenario invalido: …` o
  `Fixture invalido: …`.
- **FAIL (agente):** respuesta incorrecta, herramienta omitida o fuera de orden,
  o argumento erróneo, contrastado con la traza de `metadata`.
- **Assertion frágil:** solo si la respuesta es semánticamente correcta. Se
  corrige ampliando alternativas sin quitar el requisito, y se añade el caso a
  `evals/tests/assertion_cases.yaml`.

### Historial de evaluaciones

Ninguna de las corridas guardadas en la base local de Promptfoo se ejecutó con el
código de esta rama (`fix-audit-findings`). Se conservan como evidencia
histórica. Commit = último commit anterior a la hora de la corrida.

| ID | Commit | Casos | Pass / Fail / Error | ¿Evidencia válida? |
|---|---|---|---|---|
| `eval-Zww…`, `eval-iZA…`, `eval-LT1…` | `a3bad51`, `06573b7` | 3 / 1 / 3 | 0 / 0 / 7 | No: configuración y worker |
| `eval-go9…` | `06573b7` | 1 | 1 / 0 / 0 | No: salida de prueba |
| `eval-3s7…`, `eval-Neq…`, `eval-qKX…`, `eval-2w7…` | `06573b7`–`03c04cd` | 1–3 | 3 / 3 / 0 | Histórica: assertions frágiles ya corregidas |
| `eval-6iS…`, `eval-bS5…`, `eval-PjS…`, `eval-JVv…` | `bc77f39` | 3–7 | 7 / 2 / 9 | Parcial: los errores son abortos del worker; `bS5` = 3/3 FAQ |
| `eval-iYS…`, `eval-Mxc…` | `2e00751` | 12 + 12 | 10 / 4 / 10 | Parcial: `Mxc` alucinó fecha y lugar tras recuperar; respuestas de conocimiento general |
| `eval-fXo…`, `eval-f5T…`, `eval-CDy…` | `6d7fa23` | 3 / 12 / 5 | 5 / 4 / 11 | Parcial: abortos del worker |
| `eval-jqu…`, `eval-5x3…`, `eval-ak7…` | `1e585d2` | 1 / 1 / 5 | 3 / 1 / 3 | No: grader inexistente (404) y timeout de 45 s |
| `eval-ex7…` | `a033bee` | 5 | 3 / 2 / 0 | Histórica |
| `eval-wSL…`, `eval-riE…` | `c5caa1b` | 5 + 12 | 11 / 3 / 3 | Parcial: 3 errores del grader (cuota o timeout) |
| `eval-bXX…` | `33d762a` | 12 | 10 / 2 / 0 | Válida para ese commit: teléfono inventado sin `search_faq` |
| `eval-DPY…` | `ee5516b` | 12 | 10 / 2 / 0 | Válida para ese commit |
| `eval-4Tl…` | `a774783` | 12 | 10 / 1 / 1 | Parcial: 1 `RateLimitExhaustedError` |
| `eval-SCd…` | `de8f026` | 20 citas | 10 / 2 / 8 | Parcial: 8 errores de cuota no cuentan como fallos |
| `eval-zff…`, `eval-A6y…`, `eval-ulh…` | `de8f026`, `53b12e4` | 3 / 2 / 2 | 0 / 0 / 7 | No: solo `RateLimitError` |
| `eval-cYY…`, `eval-IPr…` | `53b12e4`, `6d2ea60` | 2 / 1 | 1 / 2 / 0 | Válida: respuesta "No." tras reservar |
| `eval-ykO…` | `fad7f3f` | 1 | 1 / 0 / 0 | Válida para ese commit |
| `eval-Lpp…` | `fad7f3f` | 3 | 0 / 2 / 1 | Válida: confirmación alucinada sin `create_appointment` |
| `eval-RGS…` | `5c2fd60` | 3 | 0 / 3 / 0 | Válida: marginal confirmado sin crear, PROHIBITED sin umbral |

### Resultados en `fix-audit-findings`

Corridas reales con Groq (concurrencia 1), ejecutadas por fases. Cada FAIL se
analizó con la traza, se corrigió en un commit propio y se repitió solo el caso
afectado. Los ERROR son de cuota o del proveedor, no fallos del agente.

| ID | Commit | Casos | Pass / Fail / Error | Análisis |
|---|---|---|---|---|
| `eval-VC1-2026-10-03T06:39:12` | `ceb47a6` | 14 (fase `faq`) | 12 / 1 / 1 | FAIL `faq_pregnancy`: 0 entradas recuperadas (corregido en `ea5f9cf`, `0ae576c`). ERROR `faq_place_date`: `RateLimitExhaustedError` del grader |
| `eval-Ufz-2026-10-03T06:42:30` | `ea5f9cf` | 1 | 0 / 1 / 0 | El especialista buscó con una reformulación de 9 caracteres; se añadió el respaldo con las palabras del usuario |
| `eval-reC-2026-10-03T06:43:25` | `0ae576c` | 1 | 1 / 0 / 0 | `faq_pregnancy` aprobado |
| `eval-WVb-2026-10-03T06:43:38` | `0ae576c` | 16 (fase `booking`) | 12 / 3 / 1 | FAIL `appointment_past`, `appointment_last_valid` (pedía el número de personas) y `appointment_info_only` (corregidos en `3144cba`). ERROR `appointment_full_order`: `RateLimitError` |
| `eval-Txz-2026-10-03T06:52:02` | `3144cba` | 4 | 3 / 1 / 0 | FAIL `appointment_last_valid`: "No, …" con IDEAL y cupo (corregido en `df1b1c9`) |
| `eval-JVe-2026-10-03T06:54:35` | `df1b1c9` | 1 | 1 / 0 / 0 | `appointment_last_valid` aprobado |
| `eval-oq5-2026-10-03T06:54:49` | `df1b1c9` | 7 (fase `marginal`) | 1 / 1 / 5 | `appointment_marginal_confirmed` aprobado con `create_appointment` real. FAIL `appointment_marginal_unconfirmed`: omitía 20 km/h (corregido en `a49d40e`). ERROR: 4 `RateLimitError` y 1 `BadRequestError` |
| `eval-7T0-2026-10-03T07:00:27` | `a49d40e` | 6 | 0 / 0 / 6 | Todos `RateLimitError` (tras 3 min de espera) |
| `eval-Skw-2026-10-03T07:15:53` | `a49d40e` | 1 | 0 / 0 / 1 | `RateLimitError` tras 15 min de espera |

**Bloqueo externo vigente:** la cuota del proveedor LLM quedó agotada. Siguen
pendientes `faq_place_date` (grader), 6 casos marginales, la fase `prohibited`
(6 casos) y la **corrida completa única de los 43 casos** sobre el commit final.
Por eso todavía no existen `reports/promptfoo-report.html` ni
`reports/promptfoo-results.json`. Los aprobados anteriores se obtuvieron en
commits previos; solo la corrida completa final cuenta como resultado de la hoja.

## Límites conocidos

- El calendario es in-memory: no persiste entre ejecuciones ni entre procesos.
- La recuperación FAQ es léxica, con alias controlados. Una reformulación lejana
  puede producir una abstención correcta en lugar de una respuesta.
- La finalización determinista completa una reserva solo con intención explícita
  (un verbo de reserva sin signo de pregunta) y con todos los datos válidos.
  Una pregunta como "¿Se puede reservar…?" no reserva por sí sola.
- El grounding considera nombres propios de varias palabras con mayúscula. Una
  ubicación inventada escrita toda en minúsculas puede no detectarse.
- Las respuestas del modelo varían entre corridas. Las garantías de código
  limitan qué puede afirmar o ejecutar, pero no su redacción.
- No se pudo auditar vulnerabilidades de dependencias sin red (`npm audit` o
  `pip-audit` pendientes).

# Notas de implementacion (auditoria Fase 0)

> Documento historico de HDT5. Las cifras (por ejemplo, 73 tests) corresponden a
> esa etapa. El estado actual de HDT6 esta en `README.md` y `AGENTS.md`.

## Estado inicial del repositorio

Este repositorio (`HDT5-Orquestaci-n`) estaba vacio (solo `README.md` y un
`.gitignore` de Python) al iniciar esta tarea. La base de conocimiento de FAQs
mencionada en el enunciado vive en un proyecto hermano, `Sistema-RAG`
(`parachute_rag`), que si tenia una implementacion previa relevante:

- **Lenguaje/gestor de dependencias**: Python 3.12, `requirements.txt` (pip).
- **SDK de agentes**: ninguno. `parachute_rag/agent.py` usa el cliente `openai`
  directamente (`client.chat.completions.create`), sin `openai-agents` SDK.
- **Configuracion**: variables `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`,
  `FAQ_PATH`, agnosticas de proveedor (compatibles con Groq, que es lo que el
  `.env` de ese proyecto usa realmente).
- **FAQs**: archivo de texto plano `data/FAQs_Parachute_SA_Guatemala_2026.txt`
  con pares `Q:`/`A:` agrupados por secciones numeradas.
- **Calendarizacion**: no existe ninguna integracion previa.
- **Tests**: `unittest` (no pytest), sin mocks de red.
- **Empaquetado**: Docker (`Dockerfile` + `compose.yaml`) con un servicio `app`
  y un servicio `tests` bajo el profile `test`.

## Decisiones tomadas para este proyecto

1. Se reutiliza el mismo archivo de FAQs (copiado a `data/` de este repo) y el
   mismo esquema de variables de entorno `LLM_*`, en vez de introducir uno
   nuevo.
2. No existia OpenAI Agents SDK previo, por lo que se introdujo aqui
   (`openai-agents==0.22.3`) ya que el enunciado lo sugiere explicitamente
   (`as_tool()`, `handoffs`) para las tres arquitecturas.
3. El usuario no dispone de API key de OpenAI; se usa Groq (API compatible con
   OpenAI Chat Completions) como proveedor, mediante
   `AsyncOpenAI(base_url=...)` + `OpenAIChatCompletionsModel` (Groq no soporta
   la Responses API).
4. No existia integracion de calendario previa y el enunciado indica no asumir
   Google Calendar si no formaba parte del proyecto anterior: se implemento
   `CalendarService` (Protocol) + `InMemoryCalendarService`.
5. La busqueda de FAQs se re-implemento como `search_faq(query)`
   deterministico (coincidencia de palabras clave sobre los pares Q/A
   parseados), en vez de mandar todo el archivo como contexto a un LLM como
   hacia `parachute_rag`. Esto la hace testeable sin red y coincide con el
   tool `search_faq(query)` que pide el enunciado.

## Bugs reales encontrados y corregidos via smoke test end-to-end

La suite de 73 tests es determinista (Open-Meteo y el LLM se mockean), por lo
que no podia detectar bugs de integracion real con proveedores externos. Se
corrio `scripts/smoke_test.py` (conversacion real de 3 turnos contra Groq +
Open-Meteo real, para las tres arquitecturas) y aparecieron tres bugs reales
que ningun test determinista habia cubierto:

1. **Nombre de variable incorrecto en Open-Meteo**: `src/integrations/open_meteo.py`
   pedia `wind_gust_10m_max`, pero la API real solo acepta `wind_gusts_10m_max`
   (plural). Open-Meteo respondia 400 en cada consulta real. Corregido y
   reflejado tambien en `tests/integration/test_open_meteo_client.py`.
2. **Handoffs vacios rechazados por Groq**: el `openai-agents` SDK genera, para
   un `handoff()` sin `input_type`, un JSON schema `{"properties": {}, "required": []}`.
   El validador de tools de Groq rechaza esa combinacion especifica con
   `'required' present but 'properties' is missing` (reproducido tambien con
   `curl` directo a la API de Groq). Esto rompia el primer mensaje de
   cualquier conversacion en la arquitectura descentralizada. Se corrigio
   agregando un `HandoffReason(reason: str)` obligatorio a cada handoff via
   `input_type=` + `on_handoff=`, lo que de paso permite loguear el motivo de
   cada transferencia.
3. **Crash del exportador de trazas sin OPENAI_API_KEY**: sin una API key de
   OpenAI (usamos Groq), el exportador de trazas del SDK fallaba de forma no
   controlada y mataba el proceso a mitad de una conversacion. Se deshabilito
   con `agents.set_tracing_disabled(True)` en `src/observability.configure_logging()`,
   ya que el proyecto tiene su propio logging estructurado.

La evidencia completa de la corrida real (las tres arquitecturas respondiendo
FAQ, bloqueando una reserva con clima real prohibido, y rechazando una fecha
fuera de horizonte) queda en `docs/smoke-test-output.txt`.

## Garantia anti-bypass

`create_appointment` (en `src/tools/calendar_tools.py`) se niega a crear una
cita si `context.jump_assessment` es `None`; y `InMemoryCalendarService.
create_appointment` (en `src/services/calendar_service.py`) vuelve a validar,
de forma independiente, que la evaluacion corresponda a la fecha solicitada y
que no sea `PROHIBITED` (o que `MARGINAL` venga con tandem experimentado
confirmado). Esta doble verificacion aplica sin importar la arquitectura ni la
ruta de `as_tool()`/`handoffs` que haya llevado hasta ahi.

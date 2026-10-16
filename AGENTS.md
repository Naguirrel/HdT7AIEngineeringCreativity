# Guía operativa para agentes: Parachute S.A. (HDT6)

## Contexto y estado

El proyecto conserva tres arquitecturas de agentes (centralizada, jerárquica y
descentralizada) que comparten dominio, herramientas, políticas y garantías. La
hoja HDT6 evalúa con Promptfoo **solo la arquitectura centralizada**: responder
FAQs con el corpus oficial y calendarizar citas tras validar fecha, clima, cupo
y, si el clima es MARGINAL, la confirmación tándem explícita del usuario.

La rama `fix-audit-findings` corrige los 27 hallazgos de la auditoría
(AUD-001 a AUD-027). Hay **43 casos** Promptfoo (14 FAQ y 29 de citas),
agrupados por `metadata.phase`: `faq`, `booking`, `marginal` y `prohibited`.
La suite Python tiene **468 pruebas** y `npm run eval:validate` valida la
configuración. Las corridas por fases sobre esta rama y sus correcciones están en
el README ("Resultados en `fix-audit-findings`"). **Bloqueo vigente:** la cuota del
proveedor LLM se agotó (`RateLimitError` persistente). Quedan pendientes 6 casos
marginales, la fase `prohibited`, `faq_place_date` y la corrida completa final de
43 casos con su reporte. La hoja no está terminada hasta completarlos.

## Reglas obligatorias

1. Leer `README.md`, este archivo, `package.json`,
   `evals/promptfooconfig.yaml` y los casos relevantes antes de modificar.
2. Ejecutar `git status --short` antes y después. No modificar `main`,
   `promptfoo-evals` ni `fix-pre-errors` salvo instrucción explícita.
3. No modificar `.env`, no leer ni mostrar `LLM_API_KEY` y no incluir secretos
   en archivos, logs, documentación o reportes. `.env` está ignorado por Git y
   por Docker; `tests/unit/test_build_config.py` lo comprueba.
4. No llamar a Open-Meteo real en evaluaciones deterministas: usar
   `weather_fixture`, `calendar_fixture` y el reloj fijo por caso. El
   calendario sigue siendo simulado en memoria.
5. No inventar resultados, no generar reportes ficticios y no editar reportes a
   mano. Conservar los fallos reales y no debilitar assertions para subir el
   porcentaje.
6. No hacer push, merge ni PR sin solicitud explícita. Un commit por problema o
   etapa.
7. Ejecutar pytest tras cambios Python, `npm run eval:validate` y
   `npm run test:assertions` tras cambios YAML, y `git diff --check` antes de
   cada commit.
8. Una variación de Markdown, espacios Unicode, acentos o redacción equivalente
   es una posible assertion frágil, no automáticamente un error factual. Si se
   amplía una assertion, añadir la salida buena y una mala a
   `evals/tests/assertion_cases.yaml`.
9. No modificar el corpus FAQ, los umbrales meteorológicos ni la capacidad sin
   autorización. Las reglas críticas viven en `src/agents/common/policies.py`
   y las garantías en código; mantener las tres arquitecturas alineadas.

## Garantías que no deben romperse

- `finish_turn` (CLI, evaluación y smoke test) completa reservas listas,
  elimina afirmaciones de citas inexistentes y aplica el grounding de entidades.
- `create_appointment` exige clima vigente, disponibilidad posterior para la
  misma fecha y el mismo grupo, y confirmación tándem si el clima es MARGINAL.
- La traza usa HMAC por sesión. La metadata exportada no contiene datos
  personales ni seudónimos. La exportación de trazas del SDK está desactivada.

## Preparación obligatoria en PowerShell

Desde la raíz del repositorio, con `.venv` y dependencias instaladas
(`python -m pip install -r requirements.lock.txt` y `npm ci`):

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

Las variables solo duran la sesión actual. El agente usa `LLM_API_KEY`,
`LLM_BASE_URL` y `LLM_MODEL`; el grader de `factuality` usa
`LLM_GRADER_MODEL` (un solo caso: `faq_place_date`, como máximo 1 llamada por
corrida completa). La concurrencia está fijada en 1 en la configuración y en los
scripts. El YAML fija `REQUEST_TIMEOUT_MS: 45000` y `maxRetries: 0` para el
grader; el provider Python usa `timeout: 180000`.

## Procedimiento de evaluación

1. Verificación local, sin LLM:

   ```powershell
   python -m pytest -q -p no:cacheprovider
   npm run eval:validate
   npm run test:assertions
   git diff --check
   ```

2. Fases con LLM, una a la vez. Ante un `RateLimitError` no repetir de
   inmediato.

   ```powershell
   npm run eval:faq -- --env-file .env
   npm run eval:booking -- --env-file .env
   npm run eval:marginal -- --env-file .env
   npm run eval:prohibited -- --env-file .env
   ```

3. Clasificar cada resultado:
   - **ERROR** de infraestructura: `Proveedor LLM: …`, timeouts, worker o
     configuración.
   - **FAIL** del agente: contrastar con `metadata.tool_calls`; el texto final
     por sí solo no demuestra ejecución.

   Corregir la causa en un commit propio y repetir solo los casos afectados con
   `--filter-pattern`.

4. Suite completa y reporte real, con revisión de secretos:

   ```powershell
   npm run eval:report -- --env-file .env
   Select-String -Path reports\promptfoo-results.json,reports\promptfoo-report.html -Pattern "gsk_|sk-|Bearer|LLM_API_KEY" -List
   ```

   La búsqueda debe quedar vacía antes de versionar.

## Criterios de finalización

Pytest, `eval:validate` y `test:assertions` en verde. Los 43 casos ejecutados en
una corrida completa real, cada fallo revisado, reportes HTML y JSON reales y sin
secretos, el README con los resultados reales y el árbol de Git limpio. Si la
corrida no puede completarse por cuota o credenciales, documentar el bloqueo y
no declarar la hoja terminada.

## Archivos importantes

| Función | Ruta |
|---|---|
| Configuración Promptfoo | `evals/promptfooconfig.yaml` |
| Provider Python | `evals/provider.py` |
| Runner del supervisor centralizado | `src/agents/centralized/evaluation.py` |
| Casos FAQ y de citas | `evals/faq_scenarios.yaml`, `evals/appointment_scenarios.yaml` |
| Corpus bueno/malo de assertions | `evals/tests/assertion_cases.yaml`, `evals/tests/check_assertions.js` |
| Fixtures | `evals/fixtures/weather.*`, `evals/fixtures/calendar.*` |
| Assertion de herramientas | `evals/assertions/tool_trace.py` |
| Reglas compartidas | `src/agents/common/policies.py` |
| Finalización, veracidad, grounding | `src/agents/common/booking_completion.py`, `truthfulness.py`, `grounding.py` |
| Reportes | `reports/` (solo tras una corrida completa real) |

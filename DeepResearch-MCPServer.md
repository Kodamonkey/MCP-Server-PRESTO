# Informe para construir un MCP Server de PRESTO

## Resumen ejecutivo

La decisión correcta para este proyecto es construir **un MCP Server local, enfocado solo en PRESTO, con transporte `stdio`, implementado sobre el SDK oficial de MCP para Python, y ejecutando PRESTO dentro de Docker**. Esa combinación minimiza superficie de ataque, evita reinventar el protocolo, reutiliza componentes oficiales ya mantenidos y permite exponer a GPT o Claude herramientas tipadas y seguras en vez de un “shell genérico” que aumentaría el riesgo operativo. MCP define precisamente tres primitivas —tools, resources y prompts—; para un MCP de PRESTO, el **MVP debe priorizar tools tipadas** y usar resources para exponer artefactos y manifiestos de corrida. citeturn29view0turn5view0turn7view2turn23view0

También conviene despejar dos dudas de alcance. **Sí: PulsarX es un toolset distinto de PRESTO**, con su propio stack para mitigación RFI, dedispersión, folding y búsqueda; no es “PRESTO con otro nombre”. Y **PULSAR_MINER sí es un wrapper/pipeline sobre PRESTO**, pero su README declara que **no es compatible con PRESTO 5.0.0 o superior**, por lo que no es una buena base de runtime para tu instalación actual basada en PRESTO 5 en Docker. Por eso, el camino más limpio es: **PRESTO-only MCP ahora; compatibilidad con otros pipelines después, si hace falta**. citeturn17search0turn20view0turn22search0

## Alcance correcto del proyecto

PRESTO ya trae el “mapa natural” de qué debería exponer un MCP de este dominio. Su README actual describe soporte para **PSRFITS search format**, **SIGPROC filterbank** y series temporales/eventos, y agrupa sus rutinas en áreas claras: **preparación de datos** (`rfifind`, `prepdata`, `prepsubband`, `mpiprepsubband`, `zapbirds`), **búsqueda** (`accelsearch`, `single_pulse_search.py`, `search_bin`), **folding/optimización** (`prepfold`, `fourier_fold.py`) y utilidades como `readfile`, `DDplan.py` y scripts de diagnóstico. Eso significa que el MCP no necesita inventar un pipeline abstracto: debe **envolver esas rutinas oficiales con contratos de entrada/salida claros**. citeturn2view1turn2view0

Eso, a su vez, define qué **no** hay que hacer en la primera versión. No conviene arrancar desde PULSAR_MINER porque hoy está declarado como wrapper para PRESTO 3/4 y no compatible con PRESTO 5; tampoco conviene convertir el MCP en un clon de PulsarX, porque PulsarX es otro motor. El MCP que quieres no compite con ellos: **estandariza acceso LLM a PRESTO**. En otras palabras: el servidor debe hablar MCP, pero el backend científico debe seguir siendo PRESTO. citeturn20view0turn17search0turn29view0

## Qué conviene reutilizar y qué no

La base de implementación debería ser el **SDK oficial de MCP para Python**, no un servidor casero desde cero. El SDK oficial declara soporte para crear servers con **tools, resources y prompts**, y para usar transportes **`stdio`, SSE y Streamable HTTP**; además incluye `FastMCP`, tipado, ciclo de vida, contexto de sesión y soporte para outputs estructurados. El propio README del SDK documenta que la rama estable actual es la **v1.x**, y que el transporte **Streamable HTTP es el recomendado para producción**; a la vez, la documentación oficial de “build server” y transportes deja claro que `stdio` es completamente válido y que en ese modo el servidor **no debe escribir nada a stdout que no sea MCP/JSON-RPC**. citeturn5view0turn2view4turn7view2

Para desarrollo y pruebas, hay que reutilizar también el **MCP Inspector**, que existe justamente para verificar conectividad, tool schemas, resultados, edge cases y logs del servidor. Es la herramienta correcta para iterar el MCP antes de conectarlo a Claude o a otro host. citeturn2view5

Como patrón de diseño, es útil mirar el **Filesystem MCP Server** oficial. No porque necesites exponer un filesystem completo, sino porque ya resuelve tres ideas que sí aplican aquí: **control de directorios permitidos**, soporte opcional a **Roots** y uso de **tool annotations** para distinguir herramientas de solo lectura frente a herramientas que escriben o mutan estado. El servidor oficial de filesystem además recomienda Roots como el método moderno para acotar acceso y muestra una forma madura de separar “allowed directories” del resto del sistema. citeturn27view0turn30search0turn25view0

También conviene reutilizar el trabajo ya hecho en PRESTO respecto de contenedores. El `INSTALL.md` oficial de PRESTO menciona expresamente las imágenes Docker de Alessandro Ridolfi, incluyendo `alex88ridolfi/presto5:latest` y `alex88ridolfi/presto5:png`, además de sus recetas Dockerfile. Eso significa que **usar Docker no es un hack externo**, sino una vía contemplada por la instalación oficial de PRESTO. citeturn22search0

Lo que **no** conviene reutilizar como base del MCP es un “bash MCP server” genérico o un wrapper que exponga ejecución arbitraria de comandos. Las guías de seguridad de MCP remarcan que las tools representan **rutas de ejecución arbitraria de código** y que la configuración de servidores locales puede convertirse en un vector de ejecución maliciosa si no hay sandbox, consentimiento y restricciones claras. Para PRESTO, el patrón correcto es un **executor interno tipado y allowlisted**, no una tool de shell expuesta al LLM. citeturn29view0turn9view0

## Arquitectura recomendada del MCP PRESTO

La arquitectura recomendada para el MVP es esta:

```text
Cliente MCP (Claude / GPT / IDE)
        │
        │  stdio
        ▼
MCP Server PRESTO
  ├─ validación de inputs
  ├─ resolución de paths permitidos
  ├─ executor interno Docker
  ├─ parser de resultados
  └─ manifiestos / recursos de salida
        │
        ▼
Contenedor PRESTO fijado por digest
  ├─ /data   solo lectura
  ├─ /outputs escritura por run_id
  └─ PRESTO CLI real
```

La razón para empezar con **`stdio` local** es muy fuerte: el propio protocolo dice que los clientes deberían soportarlo cuando sea posible, y la guía de autorización aclara que la autorización compleja con OAuth 2.1 es principalmente necesaria para **servidores remotos HTTP**, mientras que en servidores locales `stdio` es razonable usar credenciales o configuración embebida. Además, la guía de seguridad recomienda **usar `stdio` para limitar acceso al cliente MCP** cuando el servidor corre localmente. citeturn7view2turn2view6turn9view0

Dentro del servidor, la separación importante no es “bash limpio” versus “Python executor”, sino **“MCP wiring” versus “ejecución científica”**. El MCP wiring se implementa con `FastMCP` y herramientas tipadas. La ejecución científica se resuelve con un módulo interno que construye llamadas `docker run` determinísticas, valida paths, monta `/data` y `/outputs`, y luego parsea artefactos. El SDK oficial ya soporta **structured output** a partir de tipos/Pydantic, lo que te permite devolver objetos bien formados para que el LLM no tenga que depender de texto libre o parsing frágil. citeturn5view0turn6view0turn6view1

Resources y prompts deben entrar en la arquitectura, pero **no todos desde el día uno**. El protocolo define resources como datos identificados por URI que los clientes pueden listar y leer, y prompts como plantillas controladas por el usuario. Para PRESTO, eso sugiere esta estrategia: **tools primero**, **resources después** para manifiestos, `stdout`, `stderr` y archivos clave del run, y **prompts al final** como workflows guiados una vez que las tools atómicas ya estén estables. citeturn23view0turn24view0

## Seguridad operativa y controles mínimos

La seguridad del MCP PRESTO no se resuelve con annotations ni con “confiar en que el LLM se porte bien”. La propia especificación de MCP insiste en que los usuarios deben consentir explícitamente las operaciones, que las tools representan ejecución arbitraria, y que las descripciones/annotations de tools deben tratarse como **no confiables** salvo que el servidor sea de confianza. Las best practices de seguridad agregan que los servidores MCP locales son atractivos para ataques de ejecución arbitraria y exfiltración si no están adecuadamente restringidos. citeturn29view0turn7view0turn9view0

Por eso, el contenedor de PRESTO debe correrse con una política dura desde el primer día. El baseline razonable es: **imagen fijada por digest**, **sin red** (`--network none`), **filesystem raíz read-only** (`--read-only`), **`/tmp` como `tmpfs`**, **`no-new-privileges`**, **seccomp por defecto**, **sin `--privileged`**, **sin `docker.sock`**, **sin `cap-add` salvo necesidad demostrada**, **límites de CPU/memoria/PIDs**, y proceso ejecutado como **usuario no root** cuando sea posible. Docker documenta que los tags pueden moverse y que el digest fija exactamente la imagen usada; documenta también que `none` aísla completamente la red del contenedor, que `--read-only` limita escritura a volúmenes explícitos, que `--security-opt no-new-privileges` impide ganar privilegios adicionales, que el perfil seccomp por defecto ya bloquea decenas de syscalls, y que `--privileged` desactiva varias barreras de seguridad y no debe ser la solución por defecto. citeturn33search2turn33search3turn16search0turn12view0turn13view0turn13view1turn12view3turn15view0

En Linux, además, conviene considerar **Rootless Docker**. Docker explica que rootless ejecuta daemon y contenedores como usuario no root para mitigar vulnerabilidades del daemon/runtime. Esto es especialmente relevante porque la documentación de post-instalación también advierte que pertenecer al grupo `docker` otorga privilegios de nivel root. Si vas a operar el MCP de forma cotidiana en una workstation Linux, rootless reduce el blast radius. citeturn12view2turn14search3

En el executor Python, la regla es **nunca usar `shell=True` y nunca construir comandos shell a partir de texto libre**. La documentación oficial de `subprocess` y `shlex` recomienda pasar argumentos como lista con `shell=False` y advierte que interpolar cadenas en un shell es inseguro. En este MCP, el LLM no debería entregar jamás una línea de shell; debería entregar **argumentos validados por schema**, y el servidor los transforma en una lista `argv` allowlisted. citeturn35search1turn35search13

A nivel de paths, el servidor tiene que comportarse como un mini-filesystem server restringido. Mi recomendación es definir dos bases duras por configuración del servidor, por ejemplo `PRESTO_DATA_ROOT` y `PRESTO_OUTPUT_ROOT`, y aceptar solo archivos que residan dentro de esas raíces. Si el cliente soporta **Roots**, úsalo como una capa adicional de acotamiento, idealmente tomando la **intersección** entre roots del cliente y allowlist del servidor. El protocolo de Roots existe justamente para delimitar fronteras de operación, y el server oficial de filesystem lo usa como mecanismo recomendado para actualizar directorios permitidos. citeturn30search0turn27view0

Finalmente, en `stdio` debes cuidar la salida con mucha disciplina. La guía oficial de build/debugging y la especificación de transportes señalan que el servidor **puede** escribir logs a `stderr`, pero **no puede** escribir nada no-MCP a `stdout`, porque rompe el stream JSON-RPC. Si implementas logging, hazlo a `stderr` y, si después quieres algo más rico, agrega la capability de logging del protocolo. citeturn2view4turn3search3turn7view2turn7view3

## Superficie funcional recomendada del servidor

La mejor superficie funcional para la primera versión es **pequeña, tipada y alineada con el flujo real de PRESTO**. PRESTO ya enumera los bloques principales: inspección (`readfile`), planificación (`DDplan.py`), mitigación RFI (`rfifind`), dedispersión (`prepdata` / `prepsubband`), búsqueda (`accelsearch`, `single_pulse_search.py`) y folding (`prepfold`). Esa debería ser la base del MCP. citeturn2view1

Para el **MVP**, yo expondría exactamente estas tools:

1. **`inspect_observation`**  
   Wrapper sobre `readfile`. Solo lectura. Devuelve metadata estructurada del archivo de entrada, formato detectado, duración, número de canales, sample time y cualquier otro dato parseable del output. Es la tool ideal para que el LLM “entienda” el dataset antes de decidir el workflow. citeturn2view1turn6view0

2. **`find_rfi`**  
   Wrapper sobre `rfifind`. Crea un `run_id`, escribe en un subdirectorio dedicado y devuelve un manifiesto con artefactos generados (`.mask`, `.inf`, `.stats`, `.ps`, etc.). En PRESTO esto es parte explícita de la etapa de Data Preparation. citeturn2view1

3. **`plan_dedispersion`**  
   Wrapper sobre `DDplan.py`. En vez de devolver texto crudo, debería retornar un objeto estructurado con bloques de DM, downsampling, subbanding recomendado y notas del plan. La ventaja del SDK de Python es que puedes modelar esto con Pydantic/typed outputs. citeturn2view1turn6view0

4. **`dedisperse_timeseries`**  
   Wrapper inicial sobre `prepdata`. Si más adelante necesitas datasets grandes y estrategias por subbandas, se puede agregar `prepsubband`, pero no hace falta en la v1. PRESTO incluye ambas rutas, y esto permite cubrir el flujo más común sin complicar al LLM con demasiadas variantes desde el inicio. citeturn2view1turn2view2

5. **`search_acceleration`**  
   Wrapper sobre `accelsearch`. Devuelve candidatos y artefactos del run. En el README oficial es una de las herramientas de búsqueda centrales. citeturn2view1turn2view0

6. **`search_single_pulse`**  
   Wrapper sobre `single_pulse_search.py`. Esto cubre el otro gran modo de búsqueda de PRESTO y evita mezclarlo con el flujo de aceleración. citeturn2view1

7. **`fold_candidate`**  
   Wrapper sobre `prepfold`, con inputs bien tipados: archivo base, candidato/periodicidad, DM y parámetros esenciales. Si usas la imagen `:png`, podrás aprovechar la ruta contemplada por PRESTO para generar PNGs de diagnóstico a partir de los productos de `prepfold`. citeturn22search0

Yo **no** pondría `mpiprepsubband` en el MVP. El propio FAQ de PRESTO explica que su ventaja aparece en escenarios multi-máquina y con problemas de I/O distribuidos; eso es terreno HPC y complica muchísimo el modelo local del MCP. También dejaría fuera cualquier dependencia de GPU/PRESTO2_ON_GPU en la primera versión, porque incluso PULSAR_MINER advierte problemas de compatibilidad con versiones nuevas de CUDA. citeturn2view2turn20view0

Además de tools, el MCP debería ofrecer **resources** para cada corrida. Un diseño simple y bueno sería exponer URIs tipo:

```text
presto://runs/{run_id}/manifest
presto://runs/{run_id}/stdout
presto://runs/{run_id}/stderr
presto://runs/{run_id}/artifacts/{filename}
```

Resources existen justamente para compartir datos identificados por URI, los clientes pueden listarlos y leerlos, y el protocolo permite usar **custom URI schemes** mientras respeten RFC 3986. Esto encaja muy bien con resultados de PRESTO, porque el LLM puede consultar el manifiesto o leer artefactos relevantes sin volver a ejecutar la tool. citeturn23view0

Las **prompts** deberían ser opcionales y venir después. El protocolo las concibe como plantillas controladas por el usuario, algo parecido a slash commands. En un MCP de PRESTO tienen sentido como ayudas del tipo “revisar workflow de búsqueda periódica” o “interpretar outputs de rfifind”, pero no son necesarias para que un cliente llame tools. Mi recomendación es agregarlas solo cuando los outputs y resources ya estén estables. citeturn24view0

## Plan de implementación paso a paso

La secuencia más eficiente no es “hacer todo PRESTO de una vez”, sino construir un **vertical slice completo** y luego expandir.

### Fase uno

Congela el runtime. Toma la imagen `alex88ridolfi/presto5:png` referenciada por PRESTO, **pínchala por digest** y crea si quieres una imagen derivada mínima con labels/versiones propias. La documentación Docker recomienda el pinning por digest precisamente para garantizar reproducibilidad y evitar que un tag mutable cambie tu runtime sin aviso. citeturn22search0turn34view0turn33search2

### Fase dos

Construye el esqueleto del servidor con el **SDK oficial de MCP para Python** y `FastMCP`, usando `stdio`. En esta fase no implementes todavía toda la ciencia; implementa solo `inspect_observation`, `find_rfi` y los resources `manifest/stdout/stderr` por run. Ya con eso tendrás: handshake MCP, tool schemas, ejecución Docker, parsing básico y trazabilidad. citeturn5view0turn7view2turn23view0

### Fase tres

Implementa el **executor Docker** como un módulo interno y no expuesto al modelo. Debe: validar paths contra roots/allowlist, crear `run_id`, preparar mounts, ejecutar `docker run` con límites y sandbox, capturar `stdout/stderr`, registrar `exit_code`, descubrir artefactos y escribir `manifest.json`. Usa `subprocess` con listas de argumentos y `shell=False`. citeturn35search1turn35search13turn12view1turn13view0

### Fase cuatro

Agrega tools científicas una por una en este orden: `plan_dedispersion`, `dedisperse_timeseries`, `search_acceleration`, `search_single_pulse`, `fold_candidate`. La razón de este orden es que sigue la lógica operativa de PRESTO y mantiene el servidor fácil de depurar. PRESTO ya separa esas áreas en preparación, búsqueda y folding; imitar esa separación hace que el MCP sea más comprensible tanto para humanos como para LLMs. citeturn2view1

### Fase cinco

Implementa **progress** y **cancellation**. PRESTO puede tardar bastante; MCP soporta progress tokens y notificaciones de progreso para operaciones largas, y también soporta cancelación mediante `notifications/cancelled`. El executor debería mapear estados internos como `queued`, `container_started`, `presto_running`, `parsing_outputs` y `completed`, y al recibir cancelación debería intentar detener el contenedor y liberar recursos. citeturn32view0turn32view1

### Fase seis

Prueba todo con **MCP Inspector** antes de enchufarlo a un cliente final. El Inspector está pensado exactamente para probar schemas, inputs inválidos, concurrencia y salidas de tools. En paralelo, valida que el servidor no escriba accidentalmente a `stdout` y que los logs estén en `stderr`. citeturn2view5turn2view4turn7view2

### Fase siete

Cuando el servidor local ya funcione, ahí recién evalúa si necesitas una versión remota. Si llegas a ese punto, la ruta correcta ya no es `stdio` sino **Streamable HTTP**, porque el SDK oficial lo recomienda para producción; además la misma documentación del SDK dice que **SSE está siendo reemplazado** por Streamable HTTP. En esa segunda etapa sí entra la autorización con OAuth 2.1 y las recomendaciones de **least privilege**, **scope minimization** y **no token passthrough**. citeturn5view0turn2view6turn9view0

## Preguntas abiertas y límites

Hay algunos puntos que conviene dejar explícitos desde ya. El primero es que **el soporte de Roots, resources y prompts depende del cliente MCP**; el protocolo los define, pero no todos los hosts los implementan igual, así que tu servidor debe funcionar correctamente incluso si el cliente no soporta Roots y solo puedes operar con allowlists configuradas por entorno. citeturn30search0turn23view0turn24view0

El segundo es que algunos comandos de PRESTO pueden requerir pruebas empíricas adicionales para verificar exactamente **qué directorios necesitan en escritura** dentro del contenedor. La política recomendada de `--read-only` con `tmpfs` y `/outputs` dedicado es la correcta, pero igual habrá que confirmar rutina por rutina si alguna necesita más espacio temporal o comportamiento especial. Eso no invalida la arquitectura; solo significa que el hardening final debe cerrarse con tests reales de `rfifind`, dedispersión, búsqueda y `prepfold`. citeturn12view0turn13view4turn22search0

El tercer límite es de alcance: este informe está optimizado para un **MCP local de PRESTO**, no para una plataforma multiusuario remota ni para un orquestador HPC. PRESTO sí contempla escenarios más complejos, como `mpiprepsubband`, y MCP también soporta despliegues remotos con autorización, pero ambos agregan complejidad que no aporta al primer objetivo: conseguir que un LLM pueda usar PRESTO de forma **segura, reproducible y tipada** desde tu máquina actual. citeturn2view2turn2view6turn29view0
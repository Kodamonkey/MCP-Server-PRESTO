# Conectar clientes MCP a PRESTO

Guía para **cualquier persona** que clone este repo y quiera usar el servidor MCP (no solo el autor original).

## Requisitos (todos los usuarios)

1. **Python 3.11+** y **[uv](https://docs.astral.sh/uv/)** en el `PATH`
2. **Docker** en marcha (`docker version`)
3. Imagen PRESTO: `docker pull alex88ridolfi/presto5:png`
4. En el clone del repo:

   ```bash
   cd /ruta/a/MCP-Server-PRESTO
   uv sync --extra dev
   ```

5. Datos de observación en `data/` (o ajustar `PRESTO_DATA_DIR` en `.env`)

Opcional: copiar `.env.example` → `.env` y editar rutas/caps.

---

## Qué sustituir en los ejemplos

En los JSON de esta carpeta, reemplaza:

| Placeholder | Por |
|-------------|-----|
| `REPLACE_WITH_REPO_ROOT` | Ruta **absoluta** al clone (sin barra final) |

Ejemplos:

- Windows: `C:\\Users\\alice\\projects\\MCP-Server-PRESTO`
- macOS/Linux: `/home/alice/projects/MCP-Server-PRESTO`

Las rutas `./data`, `./runs`, etc. en `env` son **relativas al repo**; el código las resuelve solo (no dependen del `cwd` del cliente).

---

## Claude Desktop

1. Abre el config del sistema:
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Copia el bloque `presto` de `claude_desktop_config.example.json` dentro de `"mcpServers": { ... }` (fusiona si ya tienes otros servidores).
3. Sustituye `REPLACE_WITH_REPO_ROOT`.
4. Si `uv` no está en el PATH de Claude, usa la ruta absoluta al binario, p. ej. `C:\\Users\\alice\\.local\\bin\\uv.exe` en `"command"`.
5. Reinicia Claude Desktop por completo.

**Alternativa (venv local):** tras `uv sync`, puedes apuntar `"command"` al Python del venv:

| SO | `command` |
|----|-----------|
| Windows | `<REPO>\\.venv\\Scripts\\python.exe` |
| macOS/Linux | `<REPO>/.venv/bin/python` |

`args`: `["-m", "presto_mcp.server"]`

Usamos `uv run --directory <REPO>` en el ejemplo porque evita el error `No module named 'presto_mcp'` cuando Claude no respeta `cwd`.

---

## Cursor

1. Copia `cursor_mcp.example.json` a `.cursor/mcp.json` en la raíz del proyecto (o fusiona en la config global de Cursor).
2. Sustituye `REPLACE_WITH_REPO_ROOT` por la ruta absoluta al repo.
3. Cursor suele respetar `cwd`; `uv run` sin `--directory` basta.
4. Activa el servidor **presto** en Settings → MCP.

---

## Comprobar que arranca

```bash
cd /ruta/a/MCP-Server-PRESTO
uv run python -m presto_mcp.server
```

Debe quedarse esperando (stdio). Ctrl+C para salir.

Inspector (navegador):

```bash
npx @modelcontextprotocol/inspector uv run --directory . python -m presto_mcp.server
```

---

## Variables de entorno (`env` en el JSON)

| Variable | Significado |
|----------|-------------|
| `PRESTO_IMAGE` | Imagen Docker PRESTO |
| `PRESTO_DATA_DIR` | Entradas (solo lectura en el contenedor) |
| `PRESTO_RUNS_DIR` | Manifiestos, logs y artefactos por run |
| `PRESTO_*_CPUS` / `MEMORY` / `TIMEOUT` | Límites del contenedor |
| `PRESTO_NETWORK` | Dejar `none` |

Puedes omitir `env` en el JSON si usas un `.env` en la raíz del repo (se carga al arrancar).

---

## Publicar / compartir el servidor

Este repo **no se publica como paquete PyPI** en el MVP: cada usuario clona, ejecuta `uv sync` y apunta su cliente MCP al clone local. No hace falta copiar rutas de otro usuario.

Si en el futuro se publica en PyPI, el `command` podría simplificarse a `presto-mcp` tras `pip install presto-mcp`; hoy el entrypoint recomendado es `python -m presto_mcp.server` desde el clone.

# MCP client templates

Plantillas para Cursor y Claude Desktop. **La guía de instalación canónica está en el [README del repo](../../README.md#installation-canonical).**

## Qué sustituir

Solo un placeholder en los JSON de esta carpeta:

| Placeholder | Valor |
|-------------|--------|
| `REPLACE_WITH_REPO_ROOT` | Ruta **absoluta** al clone (sin barra final) |

Ejemplo Windows: `C:\\Users\\alice\\projects\\MCP-Server-Presto`

No añadas bloque `"env"` en el JSON: toda la configuración va en `.env` en la raíz del repo (ver README).

## Archivos

| Archivo | Destino |
|---------|---------|
| `cursor_mcp.example.json` | `.cursor/mcp.json` en la raíz del repo (o fusionar en la config global de Cursor) |
| `claude_desktop_config.example.json` | Bloque `presto` dentro de `claude_desktop_config.json` del sistema |

Rutas del config de Claude Desktop:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Reinicia la app por completo tras editar el JSON.

**Error frecuente:** poner `"presto": { ... }` al mismo nivel que `"mcpServers"`. Claude **solo** lee servidores **dentro** de `"mcpServers": { "presto": { ... } }`. Si `mcpServers` está vacío `{}`, no arranca nada.

## Si `uv` no está en el PATH del cliente

Sustituye `"command": "uv"` por la ruta absoluta al binario, p. ej. `C:\\Users\\alice\\.local\\bin\\uv.exe` (Windows).

## Alternativa: Python del venv

Tras `uv sync`, puedes usar el intérprete del venv en lugar de `uv run`:

| SO | `command` |
|----|-----------|
| Windows | `<REPO>\\.venv\\Scripts\\python.exe` |
| macOS/Linux | `<REPO>/.venv/bin/python` |

`args`: `["-m", "presto_mcp.server"]` — y mantén `PRESTO_*` solo en `.env`.

# hermes-clinepass

ClinePass model-provider plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

Use [ClinePass](https://cline.bot/cline-pass) models (`cline-pass/*`) from Hermes with a normal API key. Includes Kimi K3, GLM, DeepSeek, and the rest of the curated catalog.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Hermes](https://img.shields.io/badge/Hermes-plugin-6f42c1)](https://github.com/NousResearch/hermes-agent)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)](https://www.python.org/)

## Quick start

### 1. Install

**Linux / macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/Adolanium/hermes-clinepass/main/scripts/install.sh | bash
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/Adolanium/hermes-clinepass/main/scripts/install.ps1 | iex
```

### 2. API key

Create a key at [app.cline.bot](https://app.cline.bot) (Settings → API Keys). You need an active [ClinePass](https://cline.bot/cline-pass) subscription for `cline-pass/*` models.

```bash
# $HERMES_HOME/.env  (Windows: %LOCALAPPDATA%\hermes\.env)
CLINE_API_KEY=your_key_here
```

### 3. Chat

```bash
hermes chat -q "Reply with exactly: HELLO" --provider clinepass -m cline-pass/kimi-k3
```

Or in `config.yaml`:

```yaml
model:
  provider: clinepass
  default: cline-pass/kimi-k3
```

Provider aliases: `clinepass`, `cline-pass`, `cline`.

## Models

| Model | ID |
| --- | --- |
| Kimi K3 | `cline-pass/kimi-k3` |
| GLM-5.2 | `cline-pass/glm-5.2` |
| Kimi K2.7 Code | `cline-pass/kimi-k2.7-code` |
| Kimi K2.6 | `cline-pass/kimi-k2.6` |
| DeepSeek V4 Pro | `cline-pass/deepseek-v4-pro` |
| DeepSeek V4 Flash | `cline-pass/deepseek-v4-flash` |
| MiMo-V2.5-Pro | `cline-pass/mimo-v2.5-pro` |
| MiMo-V2.5 | `cline-pass/mimo-v2.5` |
| MiniMax M3 | `cline-pass/minimax-m3` |
| Qwen3.7 Max | `cline-pass/qwen3.7-max` |
| Qwen3.7 Plus | `cline-pass/qwen3.7-plus` |

Default auxiliary model: `cline-pass/deepseek-v4-flash`.

The gateway does not implement `GET /models`, so this list is static. See [ClinePass docs](https://docs.cline.bot/getting-started/clinepass).

Usage-billing model ids (OpenRouter-style) work on the same host and key if you pass them with `-m`, for example `anthropic/claude-sonnet-4.6`.

## Verify

```bash
hermes doctor
hermes chat -q "Reply with exactly: PING" --provider clinepass -m cline-pass/deepseek-v4-flash
```

## Other install methods

<details>
<summary>Manual copy</summary>

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/plugins/model-providers"
git clone https://github.com/Adolanium/hermes-clinepass.git /tmp/hermes-clinepass
cp -R /tmp/hermes-clinepass/clinepass "${HERMES_HOME:-$HOME/.hermes}/plugins/model-providers/clinepass"
```

Windows:

```powershell
$homeDir = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$dest = Join-Path $homeDir "plugins\model-providers\clinepass"
New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
git clone https://github.com/Adolanium/hermes-clinepass.git $env:TEMP\hermes-clinepass
Copy-Item -Recurse -Force $env:TEMP\hermes-clinepass\clinepass $dest
```

</details>

<details>
<summary>pip</summary>

```bash
git clone https://github.com/Adolanium/hermes-clinepass.git
cd hermes-clinepass
pip install .
```

Registers `hermes_agent.plugins` entry point `clinepass = clinepass:register`.

</details>

## Notes

<details>
<summary>Non-streaming / titles / compaction</summary>

Cline’s gateway wraps some non-streaming JSON responses. Streaming chat is fine. Hermes auxiliary work (titles, summaries, compaction) uses non-streaming calls and needs a Hermes core fix:

- [hermes-agent#66750](https://github.com/NousResearch/hermes-agent/issues/66750)
- [hermes-agent#66751](https://github.com/NousResearch/hermes-agent/pull/66751)

This plugin still registers the provider and catalog on any recent Hermes.

</details>

## License

MIT. ClinePass and Cline are trademarks of their respective owners. This is an independent community plugin.

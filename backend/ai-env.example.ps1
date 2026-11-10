# Copy to .env.ai.ps1, fill values, then run: . .\.env.ai.ps1
# This explicitly sets process variables; AI settings do not read backend/.env.
# Keep .env.ai.ps1 private (it is ignored by Git). Restart the API after loading.

# Shared provider credentials. Fill these locally; never add real keys here.
$env:RESOLVE_AI_GROQ_KEY = ''
$env:RESOLVE_AI_OPENROUTER_KEY = ''

# Promise suggestions from support conversations. Enable after filling Groq key.
$env:RESOLVE_EXTRACTION_ENABLED = 'false'
$env:RESOLVE_EXTRACTION_MODEL = 'openai/gpt-oss-120b'
$env:RESOLVE_EXTRACTION_TIMEOUT_SECONDS = '20'
$env:RESOLVE_EXTRACTION_DAILY_TOKEN_LIMIT = '100000'

# Automatic case investigations (requires the separate investigation worker).
$env:RESOLVE_AI_ENABLED = 'false'
$env:RESOLVE_AI_GROQ_MODEL = 'openai/gpt-oss-20b'
# GPT-OSS 120B through Phala: currently $0.60 / million output tokens.
# Optional free model: xingchen-agi/xing4.0-29b-a4b:free (same Phala route).
# Requests also cap provider output pricing at $0.74 / million tokens.
$env:RESOLVE_AI_OPENROUTER_MODEL = 'openai/gpt-oss-120b'
$env:RESOLVE_AI_APPROVED_GROQ_MODELS = '["openai/gpt-oss-20b","openai/gpt-oss-120b"]'
$env:RESOLVE_AI_APPROVED_OPENROUTER_MODELS = '["xingchen-agi/xing4.0-29b-a4b:free","openai/gpt-oss-120b"]'
$env:RESOLVE_AI_OPENROUTER_ROUTES = '["phala"]'

# Default blocks direct Groq. To permit its standard retention policy, explicitly
# change to minimized_standard_retention. Filling a key alone does not opt in.
$env:RESOLVE_AI_DATA_POLICY = 'zdr_required'
$env:RESOLVE_AI_ALLOW_SANDBOX_REFRESH = 'false'
$env:RESOLVE_AI_TIMEOUT_SECONDS = '12'
$env:RESOLVE_AI_RETRIES = '1'
$env:RESOLVE_AI_MAX_TOKENS = '1800'
$env:RESOLVE_AI_FRESHNESS_SECONDS = '3600'

# Investigation worker only: it does not load backend/.env. Before running it,
# uncomment and fill the same database URL used by the API. Otherwise it selects
# the default local SQLite database. Inject any needed Sandbox settings too if
# enabling RESOLVE_AI_ALLOW_SANDBOX_REFRESH.
# $env:RESOLVE_DATABASE_URL = ''

# From backend/, after filling and loading this file:
# uv run uvicorn app.main:app --reload
# In a separate terminal with the same environment and database configuration:
# uv run python -m app.investigation_worker --loop

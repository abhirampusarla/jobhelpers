# Resume Maker

Create a tailored `.docx` resume from a base resume and a job URL.

Supported base resume formats:
- `.txt`
- `.md`
- `.docx`

Examples:

```bash
python3 resume_maker.py
```

The script will ask for the job URL:

```text
Paste job URL:
```

Set your base resume path in `.env`:

```env
BASE_RESUME_PATH=/Users/you/Desktop/resume.docx
OUTPUT_NAME_PREFIX=ABHIRAM
```

Outputs are written to `outputs/` by default:
- `ABHIRAM_role_name.docx`
- `ABHIRAM_role_name_analysis.json`

Set your provider and API key in `.env`.

OpenAI:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

Claude:

```env
LLM_PROVIDER=claude
CLAUDE_API_KEY=your_key_here
CLAUDE_MODEL=claude-3-5-haiku-20241022
```

Gemini:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.0-flash
```

# Receipt Tracker AI (Cloud PWA)

This version is meant to run **online**, so it does **not depend on your Mac** after deployment.

## What it does
- iPhone-friendly PWA
- Uses the iPhone camera from the app (`capture="environment"`)
- Sends the receipt image to OpenAI for parsing
- Saves receipt date, store, total, and extracted items
- Shows daily spending by date
- Shows average unit prices by item

## Best setup for your case
Use **Render** or **Railway** to host it online.

## Deploy on Render
1. Create a GitHub repo and upload this project.
2. In Render, create a new Blueprint or Web Service from the repo.
3. Add environment variable:
   - `OPENAI_API_KEY` = your API key
4. Render can build from Dockerfile and connect a managed Postgres database.
5. After deploy, open the public URL on your iPhone in Safari.
6. Tap **Share > Add to Home Screen**.

## Deploy on Railway
1. Create a new project.
2. Deploy from GitHub repo or Dockerfile.
3. Add a PostgreSQL database.
4. Set environment variables:
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL=gpt-5.4-mini`
   - `DATABASE_URL` from Railway Postgres
5. Open the public URL on your iPhone and add it to Home Screen.

## Local run (optional)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="your_key"
uvicorn app.main:app --reload
```

## Important note
This is a practical MVP. The AI extraction quality depends on photo quality and receipt layout. For production use, add auth, backups, better item normalization, and editing of extracted lines.

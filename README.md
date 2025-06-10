# BetterChoices App Backend

## Setup

1. Create virtual environment:
```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
```
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:

Copy `.env.example` to `.env`

Update with your MongoDB connection string


4. Run the server:
```bash
uvicorn app.main:app --reload --port 8000
```


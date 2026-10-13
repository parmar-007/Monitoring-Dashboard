# Extract Monitor Dashboard

A simple dashboard built using:

- HTML
- CSS
- JavaScript
- FastAPI
- JSON Log Files

---

## Project Structure

```text
project/

├── index.html
├── css/
│   └── style.css
├── js/
│   └── script.js
├── logs/
│   ├── Execution_Extract/
│   ├── Portfolio_Extract/
│   └── TimeBox_Extract/
└── backend/
    ├── main.py
    ├── requirements.txt
    └── services/
        └── file_reader.py
```

## Step 1 - Create Virtual Environment

```bash
cd backend
python -m venv venv
```

Activate:

Windows:

```bash
venv\Scripts\activate
```

Linux/Mac:

```bash
source venv/bin/activate
```

## Step 2 - Install Dependencies

```bash
pip install -r requirements.txt
```

Or:

```bash
pip install fastapi uvicorn python-multipart
```

## Step 3 - Run FastAPI Backend

```bash
uvicorn main:app --reload
```

## Step 4 - Verify APIs

Health Check:

```text
http://127.0.0.1:8000/
```

Applications API:

```text
http://127.0.0.1:8000/applications/2026-10-05
```

Summary API:

```text
http://127.0.0.1:8000/summary/2026-10-05
```

Application Details API:

```text
http://127.0.0.1:8000/application/Execution_Extract/2026-10-05
```

## Step 5 - Run Frontend

From project root:

```bash
python -m http.server 5500
```

## Step 6 - Open Dashboard

```text
http://localhost:5500
```

## Development Workflow

Backend:

```bash
cd backend
venv\Scripts\activate
uvicorn main:app --reload
```

Frontend:

```bash
python -m http.server 5500
```

## Stop Application

```text
CTRL + C
```

Deactivate:

```bash
deactivate
```

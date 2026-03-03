## Setup

### 1. Create Virtual Environment

```bash
python -m venv venv
```

### 2. Activate Virtual Environment

**macOS/Linux:**
```bash
source venv/bin/activate
```

**Windows (Command Prompt):**
```bash
venv\Scripts\activate
```

**Windows (PowerShell):**
```bash
venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run

```bash
python main.py
```

### 5. Deactivate Virtual Environment

```bash
deactivate
```

## Notes

- Make sure you have Python 3.8+ installed
- Ensure your webcam is connected before running
- Add `venv/` to your `.gitignore`
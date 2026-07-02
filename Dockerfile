FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build catalog on startup if needed
RUN python -c "from scraper import get_hardcoded_catalog; import json; json.dump(get_hardcoded_catalog(), open('catalog_data.json', 'w'), indent=2)"

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
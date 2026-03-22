FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El JSON de Firebase se monta desde Secret Manager en /secrets/firebase.json
# La variable FIREBASE_CREDENTIALS_PATH apunta a esa ruta en Cloud Run
ENV FIREBASE_CREDENTIALS_PATH=/secrets/firebase.json

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

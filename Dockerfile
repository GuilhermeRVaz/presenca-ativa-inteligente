FROM python:3.12-slim

WORKDIR /app

# Instala dependências de sistema básicas
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    software-properties-common \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código
COPY . .

# Expõe as portas padrão
EXPOSE 8000
EXPOSE 8501

# O comando padrão será definido no docker-compose.yml para cada serviço
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

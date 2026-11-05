# Farol em contêiner (ideal para Linux server / NAS).
# A senha vem da variável FAROL_PASSWORD na PRIMEIRA execução (depois fica só o hash).
FROM python:3.12-slim

# openssh-client: SSH do Modo Dev · iproute2/net-tools: tabela ARP do painel Rede
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client net-tools \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 farol
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY farol ./farol
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data && chown farol:farol /data

USER farol
ENV FAROL_HOME=/data
EXPOSE 8765
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/api/session')" || exit 1
ENTRYPOINT ["/entrypoint.sh"]

# Farol em servidor Linux

## 1. Instalar como serviço

```bash
git clone https://github.com/SEU_USUARIO/farol.git && cd farol
sudo ./install.sh --server            # ou --port=9000
```

O instalador:
- cria o usuário de sistema `farol` (sem shell de login);
- instala em `/opt/farol` e guarda dados em `/var/lib/farol`;
- pergunta as pastas e a **senha**;
- ativa `farol.service` com endurecimento (`ProtectSystem=strict`, `NoNewPrivileges`…).

Comandos úteis:
```bash
systemctl status farol
journalctl -u farol -f
sudo -u farol FAROL_HOME=/var/lib/farol /opt/farol/.venv/bin/python -m farol passwd
sudo -u farol FAROL_HOME=/var/lib/farol /opt/farol/.venv/bin/python -m farol add-root /srv/novos --readonly
```

> O usuário `farol` precisa ter permissão de leitura nas pastas indexadas
> (ex.: `sudo setfacl -R -m u:farol:rX /srv/arquivos`). Para permitir edição,
> adicione a pasta em `ReadWritePaths=` no `/etc/systemd/system/farol.service`.

## 2. HTTPS (recomendado)

### Opção A — Caddy (certificado automático)
```
farol.seudominio.com.br {
    reverse_proxy 127.0.0.1:8765
}
```
Nesse caso rode o Farol só local: edite o serviço para `--host 127.0.0.1 --proxy`.

### Opção B — Nginx
```nginx
server {
    listen 443 ssl http2;
    server_name farol.seudominio.com.br;
    ssl_certificate     /etc/letsencrypt/live/farol.seudominio.com.br/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/farol.seudominio.com.br/privkey.pem;
    client_max_body_size 25m;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        # WebSocket (terminal do Modo Dev)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Opção C — certificado direto no Farol
```bash
python -m farol run --cert /caminho/fullchain.pem --key /caminho/privkey.pem
```

## 3. Pastas de rede no servidor

```bash
sudo apt install cifs-utils
sudo mkdir -p /mnt/nas
# /etc/fstab
//192.168.0.20/arquivos  /mnt/nas  cifs  credentials=/root/.smbcred,ro,uid=farol,iocharset=utf8  0  0
sudo mount -a
sudo -u farol FAROL_HOME=/var/lib/farol /opt/farol/.venv/bin/python -m farol add-root /mnt/nas --readonly
```

## 4. Bloquear o Modo Dev

Em servidores compartilhados, descomente no serviço:
```
Environment=FAROL_DISABLE_DEV=1
```
e rode `sudo systemctl daemon-reload && sudo systemctl restart farol`.

## 5. Atualizar

```bash
cd farol && git pull
sudo cp -r farol requirements.txt /opt/farol/
sudo /opt/farol/.venv/bin/pip install -r /opt/farol/requirements.txt
sudo systemctl restart farol
```

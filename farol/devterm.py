"""
Modo Dev: terminal no navegador (shell local ou SSH).

⚠️  DESLIGADO por padrão. Só pode ser ligado por quem sabe a senha, e pode ser
bloqueado de vez com a variável de ambiente FAROL_DISABLE_DEV=1 (útil em
servidores compartilhados).

Como funciona:
  - Linux/macOS: cria um pseudo-terminal (PTY) com o módulo 'pty' da stdlib.
  - Windows: usa o pacote opcional 'pywinpty' (pip install pywinpty). Sem ele,
    cai para um modo simples sem PTY (comandos funcionam, mas sem cores/editores).
  - SSH: roda o cliente 'ssh' do próprio sistema dentro do terminal. Assim o
    Farol NUNCA guarda senhas de SSH: usa suas chaves e o known_hosts normais.

O navegador conversa via WebSocket com mensagens JSON:
  {"t":"i","d":"ls\\r"}          -> entrada do teclado
  {"t":"r","c":120,"r":30}       -> redimensionar
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading

DISABLED_BY_ENV = os.environ.get("FAROL_DISABLE_DEV") == "1"

# Validação dos campos de SSH: impede "injeção de argumentos" (ex.: host "-oProxyCommand=...").
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,253}$")
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def default_shell(custom: str = "") -> list[str]:
    if custom:
        return custom.split()
    if os.name == "nt":
        return [shutil.which("pwsh") or shutil.which("powershell") or "cmd.exe"]
    return [os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh", "-l"]


def validate_host(host: dict) -> None:
    """Levanta ValueError se algum campo do host SSH for inválido/perigoso."""
    h, u = str(host.get("host", "")), str(host.get("user", ""))
    if not _HOST_RE.match(h) or h.startswith("-"):
        raise ValueError("invalid_host")
    if u and (not _USER_RE.match(u) or u.startswith("-")):
        raise ValueError("invalid_user")
    try:
        port = int(host.get("port") or 22)
    except (TypeError, ValueError):
        raise ValueError("invalid_port") from None
    if not 1 <= port <= 65535:
        raise ValueError("invalid_port")


def ssh_command(host: dict) -> list[str]:
    """Monta o comando 'ssh' a partir de um host salvo, validando cada campo."""
    validate_host(host)
    h, u = str(host.get("host", "")), str(host.get("user", ""))
    port = int(host.get("port") or 22)
    ssh = shutil.which("ssh")
    if not ssh:
        raise ValueError("ssh_not_found")
    cmd = [ssh, "-p", str(port), "-o", "ServerAliveInterval=30"]
    key = str(host.get("key_path") or "").strip()
    if key:
        cmd += ["-i", os.path.expanduser(key)]
    cmd += ["--", f"{u}@{h}" if u else h]
    return cmd


class Terminal:
    """Abstração de um processo com terminal. on_output recebe bytes."""

    def __init__(self, cmd: list[str], on_output, on_exit, cols=100, rows=30):
        self.on_output, self.on_exit = on_output, on_exit
        self.proc = None
        self._fd = None          # master do PTY (POSIX)
        self._winpty = None      # objeto pywinpty (Windows)
        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor")
        cwd = os.path.expanduser("~")
        if os.name != "nt":
            self._start_posix(cmd, env, cwd, cols, rows)
        else:
            self._start_windows(cmd, env, cwd, cols, rows)

    # ---- POSIX (Linux / macOS) ----------------------------------------
    def _start_posix(self, cmd, env, cwd, cols, rows):
        import fcntl
        import pty
        import termios
        master, slave = pty.openpty()
        self._fd = master
        self.resize(cols, rows)

        def make_controlling_tty():
            # Torna o PTY o terminal "de controle" do novo processo (Ctrl+C funciona).
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self.proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                                     start_new_session=True, preexec_fn=make_controlling_tty,
                                     close_fds=True)
        os.close(slave)
        threading.Thread(target=self._read_posix, daemon=True).start()

    def _read_posix(self):
        while True:
            try:
                data = os.read(self._fd, 65536)
            except OSError:
                break
            if not data:
                break
            self.on_output(data)
        self.on_exit()

    # ---- Windows -------------------------------------------------------
    def _start_windows(self, cmd, env, cwd, cols, rows):
        try:
            from winpty import PtyProcess  # pacote opcional pywinpty
            self._winpty = PtyProcess.spawn(subprocess.list2cmdline(cmd), cwd=cwd, env=env,
                                            dimensions=(rows, cols))
            threading.Thread(target=self._read_winpty, daemon=True).start()
        except ImportError:
            # Modo simples: sem PTY, entrada/saída por pipes.
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, cwd=cwd, env=env)
            self.on_output(b"[Farol] pywinpty nao instalado: modo simples (pip install pywinpty)\r\n")
            threading.Thread(target=self._read_pipe, daemon=True).start()

    def _read_winpty(self):
        while self._winpty.isalive():
            try:
                data = self._winpty.read(65536)
            except EOFError:
                break
            if data:
                self.on_output(data.encode("utf-8", "replace") if isinstance(data, str) else data)
        self.on_exit()

    def _read_pipe(self):
        for chunk in iter(lambda: self.proc.stdout.read1(65536), b""):
            self.on_output(chunk.replace(b"\n", b"\r\n"))
        self.on_exit()

    # ---- Comum -----------------------------------------------------------
    def write(self, text: str) -> None:
        data = text.encode("utf-8")
        if self._fd is not None:
            os.write(self._fd, data)
        elif self._winpty is not None:
            self._winpty.write(text)
        elif self.proc and self.proc.stdin:
            self.proc.stdin.write(data.replace(b"\r", b"\r\n"))
            self.proc.stdin.flush()
            self.on_output(data.replace(b"\r", b"\r\n"))   # eco local no modo simples

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(10, min(int(cols), 500)), max(5, min(int(rows), 200))
        if self._fd is not None:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        elif self._winpty is not None:
            self._winpty.setwinsize(rows, cols)

    def close(self) -> None:
        try:
            if self._winpty is not None:
                self._winpty.terminate(force=True)
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
        except Exception:  # noqa: BLE001
            pass


def platform_info() -> dict:
    """Informações mostradas na tela do Modo Dev."""
    return {
        "os": sys.platform,
        "ssh_available": bool(shutil.which("ssh")),
        "pty": os.name != "nt" or _has_winpty(),
        "disabled_by_env": DISABLED_BY_ENV,
    }


def _has_winpty() -> bool:
    try:
        import winpty  # noqa: F401
        return True
    except ImportError:
        return False

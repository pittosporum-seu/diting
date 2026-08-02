#!/usr/bin/env python3
"""
谛听 · 服务保活守护进程
读取 config/keepalive.yaml，定期检查服务状态，失败时自动重启。
"""
import os, sys, time, json, yaml, subprocess, logging, socket, urllib.request
from pathlib import Path
from datetime import datetime, timedelta

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "keepalive.yaml"

def setup_logging(log_file):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        filename=log_file, level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

def check_port(host, port):
    """检查端口是否在监听"""
    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect((host, port))
        s.close()
        return True
    except:
        return False

def check_health(url, expect):
    """HTTP 健康检查"""
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        body = resp.read().decode()
        return expect in body
    except:
        return False

def check_process(name):
    """检查进程是否存在"""
    r = subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=5)
    return r.returncode == 0

def restart_systemd(name):
    """重启 systemd 服务"""
    r = subprocess.run(["systemctl", "restart", name], capture_output=True, timeout=30)
    return r.returncode == 0

def restart_process(cmd):
    """启动进程"""
    r = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
    return r.returncode == 0

def notify_restart(script, name):
    """通知海桐服务重启"""
    if script and os.path.exists(script):
        subprocess.run([script, f"🔄 {name} 已重启", f"保活脚本检测到 {name} 异常，已自动重启"], timeout=10)

def main():
    config = yaml.safe_load(CONFIG_PATH.read_text())
    settings = config.get("settings", {})
    services = config.get("services", [])
    interval = settings.get("check_interval", 60)
    log_file = settings.get("log_file", "/var/log/diting/keepalive.log")
    notify_script = settings.get("notify_script", "")

    setup_logging(log_file)
    logging.info("保活守护进程启动，检查间隔 %ds", interval)

    restart_tracker = {}  # name -> [restart_times]

    while True:
        for svc in services:
            name = svc["name"]
            alive = False

            # 1. 端口检查
            if svc.get("port_check"):
                alive = check_port("127.0.0.1", svc["port_check"])

            # 2. HTTP 健康检查（可选）
            if alive and svc.get("health_url"):
                alive = check_health(svc["health_url"], svc.get("health_expect", ""))

            # 3. 进程检查（用于非 systemd 服务）
            if not alive and svc["type"] == "process":
                alive = check_process(svc.get("process_name", name))

            if alive:
                restart_tracker.pop(name, None)
                continue

            # 服务挂了 - 尝试重启
            logging.warning("%s 异常，尝试重启", name)

            # 检查重启频率限制
            now = time.time()
            history = restart_tracker.get(name, [])
            history = [t for t in history if now - t < svc.get("restart_window", 300)]

            if len(history) >= svc.get("restart_limit", 3):
                logging.error("%s 重启次数超限（%d次/%ds内），跳过", name, len(history), svc.get("restart_window", 300))
                continue

            # 执行重启
            ok = False
            if svc["type"] == "systemd":
                ok = restart_systemd(svc.get("systemd_name", name))
            elif svc["type"] == "process":
                ok = restart_process(svc.get("start_cmd", ""))

            if ok:
                history.append(now)
                restart_tracker[name] = history
                logging.info("%s 重启成功", name)
                if settings.get("notify_on_restart"):
                    notify_restart(notify_script, name)
            else:
                logging.error("%s 重启失败", name)

        time.sleep(interval)

if __name__ == "__main__":
    main()

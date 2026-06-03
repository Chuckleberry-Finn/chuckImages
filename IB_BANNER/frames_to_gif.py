"""
High-quality GIF converter using FFMPEG's two-pass palette method.
- Accepts an MKV (or any video) file OR a folder of PNG/JPG/GIF frames
- MKV mode: extracts frames at a chosen FPS before converting
- Asks for an output width in pixels (height scales proportionally; Enter = keep original)
- Saves the output GIF next to the source file/folder
- Auto-installs ffmpeg if missing (downloads zip directly from GitHub on Windows)
- Converts all frames to PNG before passing to ffmpeg (fixes GIF sequence issue)
"""

import subprocess
import os
import sys
import shutil
import tempfile
import platform
import urllib.request
import zipfile
import ctypes

# -- SETTINGS (tweak these) ----------------------------------------------------

FPS    = 15     # 12-15 is ideal; higher = bigger file
COLORS = 256    # max 256; lower = smaller file
DITHER = "floyd_steinberg"

# Dither options:
#   floyd_steinberg     - best for gradients (default)
#   sierra2_4a          - less grain, good for animation
#   bayer:bayer_scale=3 - clean ordered dither, best for flat/graphic art
#   none                - no dither, sharpest on solid colours

SUPPORTED   = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif")
NON_PNG     = (".gif", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif")
VIDEO_EXTS  = (".mkv", ".mp4", ".mov", ".avi", ".webm", ".m4v", ".flv")

FFMPEG_WIN_DIR = os.path.join(os.path.expanduser("~"), "ffmpeg")

# -- FFMPEG INSTALL ------------------------------------------------------------

def download_progress(count, block_size, total_size):
    if total_size > 0:
        pct = min(int(count * block_size * 100 / total_size), 100)
        bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
        print(f"\r  [{bar}] {pct}%", end="", flush=True)

def install_ffmpeg_windows():
    print("ffmpeg not found. Downloading from github.com/BtbN/FFmpeg-Builds ...")
    url      = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    zip_path = os.path.join(tempfile.gettempdir(), "ffmpeg_download.zip")
    print(f"  Downloading (~90 MB, may take a minute)...")
    try:
        urllib.request.urlretrieve(url, zip_path, reporthook=download_progress)
    except Exception as e:
        print(f"\n  Download failed: {e}")
        print("  Please install ffmpeg manually: https://ffmpeg.org/download.html")
        sys.exit(1)
    print("\n  Extracting...")
    os.makedirs(FFMPEG_WIN_DIR, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(FFMPEG_WIN_DIR)
    os.remove(zip_path)
    bin_dir = None
    for root, dirs, files in os.walk(FFMPEG_WIN_DIR):
        if "ffmpeg.exe" in files:
            bin_dir = root
            break
    if not bin_dir:
        print("  Could not locate ffmpeg.exe after extraction.")
        sys.exit(1)
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0,
                             winreg.KEY_READ | winreg.KEY_WRITE)
        current, _ = winreg.QueryValueEx(key, "PATH")
        if bin_dir not in current:
            winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, current + ";" + bin_dir)
        winreg.CloseKey(key)
        print(f"  Added to user PATH permanently: {bin_dir}")
    except Exception as e:
        print(f"  Could not persist PATH to registry: {e}")
        print(f"  To make permanent, add manually to PATH: {bin_dir}")
    print(f"  ffmpeg installed to: {bin_dir}\n")

def install_ffmpeg_mac():
    print("ffmpeg not found. Attempting install via Homebrew...")
    brew = shutil.which("brew")
    if not brew:
        print("Homebrew not found. Installing Homebrew first...")
        result = subprocess.run(
            ["/bin/bash", "-c",
             "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"],
            capture_output=False
        )
        if result.returncode != 0:
            print("Homebrew install failed. Install manually: https://brew.sh")
            sys.exit(1)
        for candidate in ["/opt/homebrew/bin", "/usr/local/bin"]:
            if os.path.isdir(candidate):
                os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
    result = subprocess.run(["brew", "install", "ffmpeg"], capture_output=False)
    if result.returncode != 0:
        print("brew install ffmpeg failed. Try: brew install ffmpeg")
        sys.exit(1)

def install_ffmpeg_linux():
    print("ffmpeg not found. Attempting install via apt...")
    result = subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"], capture_output=False)
    if result.returncode != 0:
        print("apt install failed. Try: sudo apt-get install ffmpeg")
        sys.exit(1)

def find_ffmpeg_in_install_dir():
    """Check if a previous run already downloaded ffmpeg and add it to PATH."""
    for root, dirs, files in os.walk(FFMPEG_WIN_DIR):
        if "ffmpeg.exe" in files:
            os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")
            return True
    return False

def ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return
    # On Windows, check our local install dir before downloading again
    if platform.system() == "Windows" and os.path.isdir(FFMPEG_WIN_DIR) and find_ffmpeg_in_install_dir():
        return
    system = platform.system()
    if system == "Windows":
        install_ffmpeg_windows()
    elif system == "Darwin":
        install_ffmpeg_mac()
    elif system == "Linux":
        install_ffmpeg_linux()
    else:
        print(f"Unsupported OS: {system}. Install ffmpeg manually: https://ffmpeg.org/download.html")
        sys.exit(1)
    if not shutil.which("ffmpeg"):
        print("ffmpeg still not found after install. Restart your terminal and try again.")
        sys.exit(1)
    print("ffmpeg ready.\n")

# -- PILLOW (used only to convert non-PNG frames) ------------------------------

def ensure_pillow():
    try:
        from PIL import Image
        return
    except ImportError:
        pass
    print("-- Installing Pillow for frame conversion --")
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], capture_output=False)

def convert_to_png(src, dst):
    from PIL import Image
    img = Image.open(src)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
        img = bg.convert("RGB")
    else:
        img = img.convert("RGB")
    img.save(dst, "PNG")

# -- FFMPEG RUNNER -------------------------------------------------------------

def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFMPEG error:\n", result.stderr)
        sys.exit(1)

def get_video_duration(video_path):
    """Return video duration in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None

def extract_frames_from_video(video_path, out_dir, fps):
    """Extract frames from a video file into out_dir as PNG sequence."""
    out_pattern = os.path.join(out_dir, "frame_%06d.png")
    print(f"-- Extracting frames at {fps} fps --")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vf", f"fps={fps}", out_pattern],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("FFMPEG error during frame extraction:\n", result.stderr)
        sys.exit(1)
    extracted = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
    print(f"  Extracted {len(extracted)} frames.")
    return extracted

# -- MAIN ----------------------------------------------------------------------

ensure_ffmpeg()

# 1. Ask for input — video file or frames folder
print("\nDrag a video file (MKV, MP4, MOV …) or a frames folder here:")
raw_input = input("  > ").strip().strip('"').strip("'")

is_video  = os.path.isfile(raw_input) and raw_input.lower().endswith(VIDEO_EXTS)
is_folder = os.path.isdir(raw_input)

if not is_video and not is_folder:
    ext = os.path.splitext(raw_input)[1].lower()
    if os.path.isfile(raw_input) and ext not in VIDEO_EXTS:
        print(f"Unsupported file type '{ext}'. Supported video types: {', '.join(VIDEO_EXTS)}")
    else:
        print(f"Not a valid file or folder: {raw_input}")
    sys.exit(1)

# 2. Output path (derived from source name, sits next to it)
if is_video:
    base_name  = os.path.splitext(os.path.basename(raw_input))[0]
    output_dir = os.path.dirname(os.path.abspath(raw_input))
else:
    base_name  = os.path.basename(raw_input.rstrip("/\\"))
    output_dir = os.path.dirname(os.path.abspath(raw_input))

output = os.path.join(output_dir, f"{base_name}.gif")
print(f"\n  Output -> {output}")
confirm = input("  Looks good? [Y/n]: ").strip().lower()
if confirm == "n":
    output = input("  Enter a custom output path (.gif): ").strip().strip('"').strip("'")

# 3. Output width
print("\n-- Output size --")
print("  Enter a width in pixels (height will scale proportionally).")
print("  Press Enter to keep original size.")
while True:
    raw = input("  Width px [default: original]: ").strip()
    if raw == "":
        WIDTH = -1
        print("  Using original width.")
        break
    try:
        WIDTH = int(raw)
        if WIDTH < 1:
            raise ValueError
        print(f"  Resizing to {WIDTH}px wide (height auto).")
        break
    except ValueError:
        print("  Please enter a whole number greater than 0, or press Enter to skip.")

# 4. Video mode: ask for extraction FPS, then extract frames into a temp dir
with tempfile.TemporaryDirectory() as tmp:

    if is_video:
        duration = get_video_duration(raw_input)
        if duration:
            print(f"\n  Video duration: {duration:.1f}s")
        print("\n-- Frame extraction rate --")
        print("  Lower FPS = fewer frames = smaller GIF (recommended: 10-15).")
        print(f"  The GIF will also play back at this FPS.")
        while True:
            raw_fps = input(f"  FPS [default: {FPS}]: ").strip()
            if raw_fps == "":
                gif_fps = FPS
                break
            try:
                gif_fps = int(raw_fps)
                if gif_fps < 1:
                    raise ValueError
                break
            except ValueError:
                print("  Please enter a whole number greater than 0.")

        extract_frames_from_video(raw_input, tmp, gif_fps)
        frames = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        if not frames:
            print("No frames were extracted. Check that the video file is valid.")
            sys.exit(1)
        input_pattern = os.path.join(tmp, "frame_%06d.png")

    else:
        # Folder mode — same as before
        gif_fps = FPS
        frames = sorted(
            [f for f in os.listdir(raw_input) if f.lower().endswith(SUPPORTED)],
            key=lambda f: f.lower()
        )
        if not frames:
            print(f"No supported image files found in: {raw_input}")
            print(f"Supported types: {', '.join(SUPPORTED)}")
            sys.exit(1)

        print(f"\nFound {len(frames)} frames")
        print(f"  First : {frames[0]}")
        print(f"  Last  : {frames[-1]}")

        # Convert non-PNG frames and symlink/copy PNGs into tmp
        needs_conversion = any(f.lower().endswith(NON_PNG) for f in frames)
        if needs_conversion:
            ensure_pillow()

        print("\n-- Preparing frames --")
        for i, fname in enumerate(frames):
            src = os.path.join(raw_input, fname)
            dst = os.path.join(tmp, f"frame_{i:06d}.png")
            if fname.lower().endswith(".png"):
                try:
                    os.symlink(src, dst)
                except (OSError, NotImplementedError):
                    shutil.copy2(src, dst)
            else:
                convert_to_png(src, dst)

        input_pattern = os.path.join(tmp, "frame_%06d.png")

    palette = os.path.join(tmp, "palette.png")

    # Pass 1 — build palette from full animation
    print("\n-- Pass 1: Generating palette --")
    run([
        "ffmpeg", "-y",
        "-framerate", str(gif_fps),
        "-i", input_pattern,
        "-vf", f"scale={WIDTH}:-1:flags=lanczos,palettegen=max_colors={COLORS}:stats_mode=full",
        palette
    ])

    # Pass 2 — render GIF
    print("-- Pass 2: Rendering GIF --")
    run([
        "ffmpeg", "-y",
        "-framerate", str(gif_fps),
        "-i", input_pattern,
        "-i", palette,
        "-lavfi", f"scale={WIDTH}:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither={DITHER}",
        output
    ])

size_kb = os.path.getsize(output) / 1024
print(f"\nDone. {output} ({size_kb:.0f} KB)\n")

from pathlib import Path
import sys
import traceback
import ctypes

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

try:
    from micro_ops.flet_app import launch as main
except ImportError:
    # Keep the original no-dependency desktop UI as a fallback.
    from micro_ops.app import main


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        log_path = Path(__file__).resolve().parent / "data" / "startup-error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        try:
            ctypes.windll.user32.MessageBoxW(None, f"MicroOps failed to start. Details saved to:\n{log_path}\n\n{exc}", "MicroOps startup error", 0x10)
        except Exception:
            print(f"MicroOps failed to start: {exc}\nSee {log_path}", file=sys.stderr)
        raise

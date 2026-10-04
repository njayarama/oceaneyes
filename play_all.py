#!../.oceaneyes/bin/python3
import time
import oceaneyes as oe

DURATION = 10  # seconds per favourite

def main():
    device = 1
    total = oe.get_total(device, "fav")
    print(f"[i] Playing {total} favourites on device {device} for {DURATION}s each ...")

    for i in range(1, total + 1):
        try:
            code, message, playing = oe.play(device, str(i))
            print(f"[{i}/{total}] {playing} [{code}]")
        except Exception as e:
            print(f"[!] {i}/{total} error: {e}")
        time.sleep(DURATION)

    print("[i] Done previewing favourites.")

if __name__ == "__main__":
    main()
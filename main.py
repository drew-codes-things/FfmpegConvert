"""Unified entry point for all three converters."""
import sys


def main():
    print("ffmpeg-converters - made by Drew")
    print("Convert (A)udio / (V)ideo / (I)mage")
    choice = input("Choose [A/V/I]: ").strip().lower()

    if choice == 'a':
        import audio
        audio.main()
    elif choice == 'v':
        import video
        video.main()
    elif choice == 'i':
        import image
        image.main()
    else:
        print("Invalid choice. Run audio.py, video.py or image.py directly.")
        sys.exit(1)


if __name__ == "__main__":
    main()

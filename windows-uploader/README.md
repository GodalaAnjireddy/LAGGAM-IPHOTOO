# LAGGAM IPHOTOO — Windows Nikon Folder Uploader

This small Windows program watches the Nikon Wireless Transmitter Utility destination folder and uploads completed JPEG/PNG/WEBP images to the event you select. It does not delete or move the originals.

## Setup

1. In the event's private Admin page, find **Connect your Nikon folder**.
2. Enter the exact folder that receives the Nikon images. Example:  
   `C:\Users\YourName\Desktop\New folder\Z 6 7606864\DCIM\145NCZ_6`
3. Download the uploader config. Save it into this folder as `config.json`.
4. Keep `uploader.py` and `install_and_run.bat` in the same folder.
5. Double-click `install_and_run.bat`. It installs the small `requests` dependency and starts watching.
6. Keep the command window open during the event. New finished image files upload to the selected event automatically.

## Important: laptop Internet connection

The Nikon Z6 direct Access Point Wi-Fi connection can make the laptop lose Internet access. The uploader needs Internet to reach Render. Prefer connecting the camera and laptop to the same Wi-Fi router/mobile hotspot in infrastructure mode, where supported. Otherwise use Ethernet or a second Wi-Fi adapter for the laptop's Internet connection while its first Wi-Fi adapter remains connected to the camera.

Test with 2–3 photos before the event. The program scans nested folders, waits for a file to stop changing, uploads it, then records its SHA-256 digest in `uploaded_state_EVENTCODE.json` so it does not upload the same image again.

## Security

- `config.json` contains the private event admin token. Never commit or send it to guests.
- Add `config.json` and `uploaded_state_EVENTCODE.json` to your local backup, not to this GitHub repository.
- Only JPG/JPEG/PNG/WEBP files are uploaded. Nikon RAW/NEF files stay on the memory card and laptop and are not uploaded.
- The app must be configured with durable photo storage. A free Render instance has temporary storage.

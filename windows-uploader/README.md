# LAGGAM IPHOTOO — Windows Nikon Folder Uploader (Free Local Mode)

This helper watches the Nikon Wireless Transmitter Utility destination folder and uploads completed JPEG/PNG/WEBP images to the FastAPI app running on the **same laptop** at `http://127.0.0.1:8000`. It does not delete or move the original camera-transfer files.

## Setup

1. Start the main local application by running `start_laggam_local.bat` from the repository folder.
2. Open the event's private Admin page using the public tunnel URL.
3. Enter the exact Nikon transfer folder. Example:  
   `C:\Users\YourName\Desktop\New folder\Z 6 7606864\DCIM\145NCZ_6`
4. Download the uploader config. Save it as `config.json`.
5. Put `config.json`, `uploader.py` and `install_and_run.bat` in the same folder.
6. Double-click `install_and_run.bat`. It installs the small `requests` dependency and starts watching.
7. Keep the window open during the event. Completed images upload to the local app, which stores them in the event's `data/<EVENT_ID>/photos` directory and starts local face indexing.

## Network and guest access

The uploader sends images to `127.0.0.1`, so it does not send photographer images to Render or an external storage provider. Guests access the same laptop app through the Cloudflare Quick Tunnel.

Connect the Nikon Z6 and laptop to the same mobile hotspot/router where supported, so the laptop keeps Internet for the guest tunnel. If the camera's direct Wi-Fi mode removes Internet from the laptop, use an existing Wi-Fi network/infrastructure mode, Ethernet or a second Wi-Fi adapter.

## File handling and privacy

- The uploader scans nested folders and waits until a file stops changing before uploading.
- It uses a per-event SHA-256 checkpoint file to avoid re-uploading the same photo.
- The source files remain in the Nikon transfer folder; the originals also remain on the camera memory card according to camera settings.
- Only JPG/JPEG/PNG/WEBP are uploaded. Nikon RAW/NEF files stay on the card/laptop.
- `config.json` contains the private event admin token. Never share it with guests or commit it to GitHub.
- Back up the app's `data` folder after the event.

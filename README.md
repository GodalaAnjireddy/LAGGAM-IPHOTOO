# LAGGAM IPHOTOO — Free local event photo gallery

LAGGAM IPHOTOO runs on the photographer's Windows laptop. Event records, photos and face embeddings stay in the laptop's local `data` folder. Guests open the selected event using a temporary free public link.

## No paid Render storage or AWS account required

- Run the FastAPI app on the Windows laptop using `start_laggam_local.bat`.
- The laptop stores event JSON, original photos and face index under `data/<EVENT_ID>/`.
- Local face matching uses OpenCV YuNet + SFace. The app downloads the official unquantized model files once and caches them in `models/`.
- The public guest URL is shared through a Cloudflare Quick Tunnel (free, temporary). It only works while the laptop, server and tunnel remain running.
- Render Free may continue to host a demo homepage, but do not create real events or upload private photographs to Render Free. Its filesystem is ephemeral and data can be lost on spin-down, restart or redeploy.

## Start the free local system

1. Download this repository branch to the Windows laptop and extract it.
2. Install Python 3.10 or 3.11 if it is not installed. During setup, select **Add Python to PATH**.
3. Double-click `start_laggam_local.bat`. It installs Python dependencies and starts the app at `http://127.0.0.1:8000`.
4. Install Cloudflare Tunnel once from an Administrator/normal Command Prompt:
   ```cmd
   winget install --id Cloudflare.cloudflared --exact
   ```
5. Double-click `start_public_guest_link.bat`. It prints a random HTTPS address ending in `.trycloudflare.com`.
6. Copy that public address and open it in the laptop browser. **Create your event from that public address, not from localhost**, so the event's guest and admin links use the same public address.
7. Keep both command windows open throughout the event. Do not close or restart the tunnel after printing the QR. If the tunnel restarts, its URL changes and the event QR must be regenerated.

Quick Tunnels are for testing/development, not guaranteed production hosting. They do not require a Cloudflare account or domain, but the URL is temporary and stops working when the tunnel process stops. See the Cloudflare documentation: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/

## Create and manage events

The home page supports Wedding, Birthday, Saree Function, Engagement, Reception, Anniversary and Other Event.

1. Create the event from the tunnel URL.
2. Save its event code and private Admin link. Never give the Admin link to guests.
3. Refresh the home page to see the Created Events list. Event records are stored in the laptop's `data` folder and remain after app restarts, provided that folder is not deleted.
4. Open the private Admin link, enter the exact Nikon transfer folder path and download the uploader config.
5. Keep the guest QR code available to guests.

## Nikon Z6 automatic photo workflow

1. Use Nikon Wireless Transmitter Utility to save JPEG files to your known transfer folder, e.g. `C:\Users\YourName\Desktop\New folder\Z 6 7606864\DCIM\145NCZ_6`.
2. Connect the Nikon Z6 and laptop to the same mobile hotspot/router where supported. The laptop needs Internet for the public guest tunnel.
3. In the event Admin page, enter the Nikon destination folder and download the uploader config.
4. Download `windows-uploader/uploader.py` and `windows-uploader/install_and_run.bat` from this repository branch. Put both in one folder with the downloaded `config.json`.
5. Double-click `install_and_run.bat` and leave it running. It watches for completed JPG/JPEG/PNG/WEBP files and uploads them to the local app at `http://127.0.0.1:8000`. It does not remove files from the Nikon folder or memory card.
6. Test with a few JPEGs before the real event. Nikon RAW/NEF files are not included in the guest gallery by this MVP.

## Free local face detection and matching

- Uses OpenCV Zoo YuNet for face detection and SFace for face embeddings.
- The first face indexing requires Internet to download the model weights. Later recognition runs locally on the laptop.
- The app intentionally uses the unquantized SFace ONNX model, avoiding the quantized ONNX node that failed in the previous OpenCV DNN setup.
- New uploaded photos are indexed automatically. The Admin page includes **Re-index all photos for face search** for images uploaded earlier.
- Guests choose/take a selfie, explicitly consent, and search against the event's local face index. The selfie is processed in memory and is not saved by the application.

Model notices and licenses:
- YuNet model: MIT license (OpenCV Zoo model folder).
- SFace model: Apache 2.0 license (OpenCV Zoo model folder).
- Model files are downloaded from the official OpenCV Zoo repository and are not committed into this Git repository.

## Important network and uptime notes

- Laptop must remain powered on, connected to the Internet and running both the local app and Cloudflare tunnel while guests access photos.
- Keep the phone hotspot powered and connected. If the laptop loses Internet, guests outside the venue cannot open the QR link.
- A Cloudflare Quick Tunnel URL changes when restarted. Create/print QR only after starting the tunnel; avoid closing the tunnel until guests finish.
- If the camera/laptop cannot both stay on the same hotspot, use a second Wi-Fi adapter or Ethernet for the laptop Internet connection.
- Back up the entire `data` folder to an external drive after the event. This is the only permanent copy unless you make another backup.
- This free method is suitable for a one-event test/temporary event, not a guaranteed always-on commercial hosting service.

## Local folders

- `data/<EVENT_ID>/event.json` — event details and private admin token.
- `data/<EVENT_ID>/photos/` — original gallery JPEG/PNG/WEBP files.
- `data/<EVENT_ID>/face_index.json` — local face feature vectors.
- `models/` — cached YuNet and SFace model files.
- `windows-uploader/config.json` — private event uploader configuration; do not upload it to GitHub.

## Run tests

```cmd
pip install -r requirements-dev.txt
pytest -q
```

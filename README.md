# LAGGAM IPHOTOO — SriLekha Photography

An event photo gallery for weddings, birthdays, saree functions, engagements, receptions and other celebrations.

## What is in this branch

- Branded home, event and guest pages with an IPHOTOO camera wordmark.
- Event categories, event codes and an event-history list.
- Guest QR codes that point to the public Render site.
- Private event-admin links and token-protected photo upload/admin gallery APIs.
- Manual photo upload and per-event photo galleries.
- Face detection/indexing and selfie search through **Amazon Rekognition face collections** (requires AWS credentials and permission setup).
- A Windows folder-watcher uploader for Nikon Wireless Transmitter Utility transfer folders.
- Render deployment configuration using `PHOTOO_DATA=/var/data`.

## Read this before deploying — storage

Render's free web services use an ephemeral filesystem. Photos and JSON event records stored there can be lost when a service restarts, spins down, or redeploys. This project stores event metadata and images beneath `PHOTOO_DATA`, so the production service **must** have durable storage mounted at `/var/data`.

For the current Render service:
1. In Render, open **LAGGAM-IPHOTOO → Settings / Compute** and upgrade the web service from Free to a paid instance.
2. Add a persistent disk mounted at exactly `/var/data` (the blueprint specifies 10 GB).
3. Confirm the environment variable `PHOTOO_DATA=/var/data`.
4. Set `PUBLIC_BASE_URL=https://laggam-iphotoo.onrender.com` (use the exact URL shown in your Render dashboard).
5. Do not deploy the new version until durable storage is attached. If the existing service has stored test images on its free filesystem, download/back them up before redeploying; Render free storage is not a reliable archive.

Persistent disks are only available on paid Render web services. The current app uses a single service instance because the disk is attached to one instance.

## Deploy this branch

The changes are on branch `feature/event-gallery-auto-sync` and are not yet on the live `main` branch.

1. Open the GitHub pull request for this branch and review the changes.
2. Configure durable storage in Render as described above.
3. Merge the pull request into `main` after storage is ready. Render will deploy from `main` if the existing service is connected to that branch.
4. Verify `https://laggam-iphotoo.onrender.com/health` returns `{"ok":true,...}`.
5. Open the site, create a test event, refresh the page, and confirm it remains in **Created events**.

## Event workflow

1. Create an event and choose its type.
2. Save the event code and private Admin link. The event code/guest page are public; never share the private Admin link.
3. Open Admin and configure the Nikon transfer folder.
4. Download the Windows uploader config and save it as `windows-uploader/config.json` beside `uploader.py`.
5. Install and run the Windows folder uploader. Keep it running while the camera is transferring photographs.
6. Print/share the event QR code. Guests can use any Internet connection to open the guest page.
7. Guests take/select a selfie, check the face-search consent box, and search. Matching event photos appear with download links.

## Nikon Z6 camera-to-laptop transfer

Use Nikon Wireless Transmitter Utility and set its destination folder to the folder you enter in the event Admin page. The Nikon Z6 is listed among cameras that support the built-in wireless LAN pairing workflow; the utility lets you choose the Windows destination folder.

**Network note:** If the laptop is connected directly to the camera's Wi-Fi access point, it may not have Internet at the same time. The folder uploader needs Internet to reach Render. Prefer connecting both the laptop and camera to the same Wi-Fi router/mobile hotspot in infrastructure mode, where supported. Otherwise connect the laptop to Internet through Ethernet or a second Wi-Fi adapter while the first adapter is connected to the camera. Test this before the event.

The Windows uploader sends JPG/JPEG/PNG/WEBP files. Nikon RAW/NEF files are not uploaded by this MVP; keep them on the camera card and laptop backup. Use JPEG transfer from the camera for the guest gallery.

## Face matching setup (AWS Rekognition)

The face-matching code is present, but **selfie matching remains disabled until AWS is configured**.

1. Create an AWS account and enable Amazon Rekognition in a supported region (default in this app: `ap-south-1`).
2. Create a dedicated IAM user/access key for this application, with only the following Rekognition actions on the account:
   - `rekognition:CreateCollection`
   - `rekognition:DescribeCollection`
   - `rekognition:IndexFaces`
   - `rekognition:SearchFacesByImage`
3. In Render → Environment, set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION=ap-south-1`. Never put the secret key in GitHub or in a public message.
4. Redeploy. Upload one test photo containing a visible face. The upload response reports the face-indexing result.
5. Test with a clear front-facing selfie and verify the matching images before relying on it.

AWS charges for Rekognition usage may apply. Rekognition stores face feature vectors in its collection for matching; the uploaded photo remains in this app's photo storage. Provide a clear notice and get affirmative consent before a guest uses face search. Provide an event photo/face-data removal procedure before using this for real events.

## Local development

```cmd
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
set PUBLIC_BASE_URL=http://127.0.0.1:8000
set PHOTOO_DATA=./data
uvicorn app:app --host 0.0.0.0 --port 8000
```

For tests:

```cmd
pip install -r requirements-dev.txt
pytest -q
```

## Windows uploader files

See [windows-uploader/README.md](windows-uploader/README.md). Never commit `config.json` or `uploaded_state.json`; they are excluded by `.gitignore`.

## Known MVP limitations

- Event data and photos use the configured local data directory. Use a persistent Render disk at `/var/data` before real events.
- The Windows uploader runs while its command window is open; it is not yet installed as a Windows background service.
- Face search is a one-selfie / face-collection search. Match quality depends on pose, lighting and face size. Review results, and let guests browse/download only where the event organiser has permission.
- Admin access uses a private, high-entropy URL token. Treat it like a password.
- This is an MVP and still needs an explicit event deletion/retention workflow and broader production security review before large-scale commercial operation.

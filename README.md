# LAGGAM IPHOTOO — Under Srilekha Photography

## Brand update
Branding is **LAGGAM IPHOTOO**, under **Srilekha Photography**: browser titles, website header, guest page, admin page, footer, FastAPI application title, Render service and storage names.

## Included
- Create wedding events and event admin pages
- Guest wedding landing page
- Upload and browse/download wedding photos
- Guest selfie submission with optional InsightFace face matching
- QR generation using the public deployment URL
- Render deployment blueprint
- Local folder-copy endpoint for a photographer laptop (see limitation below)

## Deploy on Render
1. Create a GitHub repository named `Photoo-by-PR` and upload these files.
2. In Render, choose **New → Blueprint** and connect that repository.
3. After the service is created, set `PUBLIC_BASE_URL` to the public HTTPS URL Render gives you, for example `https://laggam-iphotOO.onrender.com` (use your actual assigned URL).
4. Deploy/redeploy, open the public URL, create the wedding event and use its Admin page.
5. The public QR endpoint is `/api/events/EVENT_ID/qr`.

## Important Nikon-to-cloud limitation
The Nikon Z6 transfers photos to the Windows laptop over camera Wi-Fi. A cloud server cannot read a Windows folder path directly. The `/sync-folder` endpoint is only useful when the app server itself can access that folder; it does not synchronize a photographer's remote laptop folder to Render. To make camera transfers appear online automatically, a separate Windows sync client must upload new camera-folder photos to the deployed `/api/events/EVENT_ID/upload` endpoint. Until that client is configured, use the Admin page's manual upload option.

## Optional face matching
Face matching requires additional packages: `insightface` and `onnxruntime`. They are not installed by default because they are large and platform-dependent. Install and test them on the selected host before relying on selfie search. First initialization may need to download model files. Similarity results are suggestions and should be reviewed.

## Local run
```cmd
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
set PUBLIC_BASE_URL=http://127.0.0.1:8000
uvicorn app:app --host 0.0.0.0 --port 8000
```
Then open `http://127.0.0.1:8000`.

## Privacy and security
This is an MVP, not a hardened production service. Admin routes do not yet require login. Face matching processes biometric data: obtain informed consent, explain its purpose, restrict access, secure stored images, and provide a deletion process before public use. Do not publish private wedding photos without the couple's and relevant guests' permission.

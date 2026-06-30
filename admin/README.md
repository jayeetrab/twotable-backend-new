# TwoTable Image Uploader (admin)

A small Streamlit web app to upload images into the same MongoDB GridFS bucket
(`photos`) the API serves from, and link them to **venues** or **daters/users**
so they appear in the iOS app immediately.

## Run

```bash
cd twotable-backend-new
.venv/bin/streamlit run admin/image_uploader.py
```

Then open the printed URL (default http://localhost:8501).

It reads `MONGODB_URI`, `MONGODB_DB`, and `PUBLIC_BASE_URL` from `.env`.
Make sure the API is running too (`uvicorn app.main:app`) so previews/photos load.

## What it does

- **Venues tab** — search by name/city, pick a venue, upload one or more photos.
  Stored in GridFS; the venue's `photos` array is updated. The app shows the first
  photo on the matched/venue-details screens (`photo_url` from `GET /venues`).
- **Daters / Users tab** — pick a user, upload photos. Stored against their
  `user_profiles.photos`; shown on the discovery cards (`GET /discovery/feed`).

Photos are served at `GET /api/v1/photos/<id>` and rendered in the app with
`AsyncImage`. App user signups also upload their onboarding photos automatically.

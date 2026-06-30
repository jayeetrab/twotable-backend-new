"""
TwoTable image uploader — a small admin web app.

Uploads images into the SAME MongoDB GridFS bucket the API serves from
(`photos`), and links them to venues or users so they show up in the app.

Run:
    cd twotable-backend-new
    .venv/bin/streamlit run admin/image_uploader.py

The app reads MONGODB_URI / MONGODB_DB / PUBLIC_BASE_URL from .env.
"""
from __future__ import annotations

import os

import streamlit as st
from bson import ObjectId
from dotenv import load_dotenv
from gridfs import GridFSBucket
from pymongo import MongoClient

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB = os.getenv("MONGODB_DB", "TwoTable")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8009")

VENUES = "venues_app"
USERS = "users"
PROFILES = "user_profiles"

# Must be the FIRST Streamlit command in the script.
st.set_page_config(page_title="TwoTable Image Uploader", page_icon="📸", layout="wide")


@st.cache_resource
def get_db():
    client = MongoClient(MONGODB_URI)
    return client[MONGODB_DB]


db = get_db()
bucket = GridFSBucket(db, bucket_name="photos")


def photo_url(pid: str) -> str:
    return f"{PUBLIC_BASE_URL}/api/v1/photos/{pid}"


def read_photo(pid: str) -> bytes | None:
    try:
        return bucket.open_download_stream(ObjectId(pid)).read()
    except Exception:
        return None


def store_photo(data: bytes, filename: str, content_type: str, meta: dict) -> str:
    fid = bucket.upload_from_stream(
        filename, data, metadata={**meta, "content_type": content_type or "image/jpeg"}
    )
    return str(fid)


def show_existing(photos: list[str]):
    if not photos:
        st.caption("No photos yet.")
        return
    cols = st.columns(min(len(photos), 4))
    for i, pid in enumerate(photos):
        data = read_photo(pid)
        with cols[i % len(cols)]:
            if data:
                st.image(data, use_container_width=True)
            st.caption(pid[:8])


def uploader_block(coll: str, doc: dict, label: str):
    """Shared upload UI: show existing photos, accept new ones, save to GridFS + doc."""
    photos = doc.get("photos") or []
    st.write(f"**Current photos ({len(photos)})**")
    show_existing(photos)

    files = st.file_uploader(
        f"Add photos for {label}", type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True, key=f"up_{coll}_{doc['_id']}",
    )
    c1, c2 = st.columns(2)
    if c1.button("⬆️ Upload", key=f"btn_{coll}_{doc['_id']}", type="primary", disabled=not files):
        new_ids = []
        for f in files:
            pid = store_photo(f.getvalue(), f.name, f.type, {"ref": coll, "doc_id": doc["_id"]})
            new_ids.append(pid)
        db[coll].update_one({"_id": doc["_id"]}, {"$push": {"photos": {"$each": new_ids}}})
        st.success(f"Uploaded {len(new_ids)} photo(s). They're now live in the app.")
        st.rerun()
    if photos and c2.button("🗑️ Clear all photos", key=f"clr_{coll}_{doc['_id']}"):
        db[coll].update_one({"_id": doc["_id"]}, {"$set": {"photos": []}})
        st.warning("Cleared.")
        st.rerun()


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("📸 TwoTable Image Uploader")
st.caption(f"Connected to **{MONGODB_DB}** · photos served from {PUBLIC_BASE_URL}/api/v1/photos/<id>")

tab_venues, tab_users = st.tabs(["🍽️ Venues", "👤 Daters / Users"])

with tab_venues:
    st.subheader("Venue photos")
    q = st.text_input("Search venues by name", "")
    city = st.text_input("City", "Bristol")
    query = {"city": {"$regex": city, "$options": "i"}} if city else {}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    venues = list(db[VENUES].find(query).limit(200))
    st.caption(f"{len(venues)} venue(s) match.")
    if venues:
        labels = {f"{v.get('name','?')} — {v.get('cuisine') or '—'} (#{v['_id']})": v for v in venues}
        choice = st.selectbox("Pick a venue", list(labels.keys()))
        venue = labels[choice]
        st.markdown(f"**{venue.get('name')}** · {venue.get('address','')}")
        uploader_block(VENUES, venue, venue.get("name", "venue"))

with tab_users:
    st.subheader("User / dater photos")
    users = list(db[USERS].find({"role": "dater", "full_name": {"$nin": [None, ""]}}).limit(200))
    st.caption(f"{len(users)} user(s).")
    if users:
        labels = {f"{u.get('full_name')} (#{u['_id']})": u for u in users}
        choice = st.selectbox("Pick a user", list(labels.keys()))
        user = labels[choice]
        profile = db[PROFILES].find_one({"user_id": user["_id"]})
        if not profile:
            st.info("This user has no profile document yet — uploading will create one.")
            profile = {"_id": None, "user_id": user["_id"], "photos": []}
        # Upload against the profile doc (create if missing).
        photos = profile.get("photos") or []
        st.write(f"**Current photos ({len(photos)})**")
        show_existing(photos)
        files = st.file_uploader("Add photos", type=["jpg", "jpeg", "png", "webp"],
                                 accept_multiple_files=True, key=f"up_user_{user['_id']}")
        if st.button("⬆️ Upload", type="primary", disabled=not files, key=f"btn_user_{user['_id']}"):
            new_ids = [store_photo(f.getvalue(), f.name, f.type, {"ref": "user", "user_id": user["_id"]})
                       for f in files]
            if profile["_id"] is None:
                from datetime import datetime, timezone
                # mirror the integer-id counter the API uses
                ctr = db["counters"].find_one_and_update(
                    {"_id": "user_profiles"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
                db[PROFILES].insert_one({
                    "_id": int(ctr["seq"]), "user_id": user["_id"], "photos": new_ids,
                    "profile_complete": False,
                    "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc),
                })
            else:
                db[PROFILES].update_one({"_id": profile["_id"]}, {"$push": {"photos": {"$each": new_ids}}})
            st.success(f"Uploaded {len(new_ids)} photo(s) for {user.get('full_name')}.")
            st.rerun()

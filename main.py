import os
import uuid
from datetime import datetime
from typing import Optional, List

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from database import db, create_document, get_documents
from schemas import Game, ImportRequest

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

# ----------------------------
# Import Endpoints
# ----------------------------

@app.post("/import/chesscom")
def import_chesscom(req: ImportRequest):
    """Import recent games from chess.com for a username and store them."""
    username = req.username.strip().lower()
    months = req.months or 1
    limit = req.limit or 50

    # Get archives list
    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    r = requests.get(archives_url, timeout=20)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"chess.com user not found or no archives: {username}")
    archive_list = r.json().get("archives", [])[-months:]
    total_inserted = 0

    for url in reversed(archive_list):  # newest last; we'll iterate from newest first
        gr = requests.get(url, timeout=30)
        if gr.status_code != 200:
            continue
        data = gr.json()
        games = data.get("games", [])
        for g in games:
            if total_inserted >= limit:
                break
            pgn = g.get("pgn")
            if not pgn:
                continue
            white = (g.get("white") or {}).get("username") or None
            black = (g.get("black") or {}).get("username") or None
            result = (g.get("white") or {}).get("result") + "/" + (g.get("black") or {}).get("result") if g.get("white") and g.get("black") else None
            tc = g.get("time_control")
            speed = g.get("time_class")
            end_time = g.get("end_time")
            end_dt: Optional[datetime] = datetime.utcfromtimestamp(end_time) if isinstance(end_time, int) else None
            rated = g.get("rated")

            # de-dup by source + pgn hash
            key = {"source": "chesscom", "pgn": pgn}
            if db["game"].find_one(key):
                continue

            game_doc = Game(
                source="chesscom",
                username=username,
                white=white,
                black=black,
                pgn=pgn,
                rated=rated,
                speed=speed,
                time_control=str(tc) if tc is not None else None,
                result=result,
                end_time=end_dt,
            )
            create_document("game", game_doc)
            total_inserted += 1
        if total_inserted >= limit:
            break

    return {"source": "chesscom", "username": username, "inserted": total_inserted}


@app.post("/import/lichess")
def import_lichess(req: ImportRequest):
    """Import recent games from lichess for a username and store them."""
    username = req.username.strip()
    limit = req.limit or 50

    url = f"https://lichess.org/api/games/user/{username}"
    params = {
        "max": str(limit),
        "moves": "true",
        "pgnInJson": "true",
        "clocks": "false",
        "opening": "true",
        "perfType": "bullet,blitz,rapid"
    }
    headers = {"Accept": "application/x-ndjson"}

    r = requests.get(url, params=params, headers=headers, timeout=60)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"lichess user not found or API error: {username}")

    total_inserted = 0
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            import json
            g = json.loads(line)
        except Exception:
            continue
        pgn = g.get("pgn") or g.get("pgnStr")
        if not pgn:
            # If pgn not present, synthesize from metadata is complex; skip
            continue
        white = (g.get("players", {}).get("white", {}) or {}).get("user", {}).get("name") or g.get("white") or None
        black = (g.get("players", {}).get("black", {}) or {}).get("user", {}).get("name") or g.get("black") or None
        rated = bool(g.get("rated")) if g.get("rated") is not None else None
        speed = g.get("speed") or None
        time_control = g.get("timeControl") or None
        result = g.get("status") or None
        end_dt = None
        if g.get("lastMoveAt"):
            try:
                end_dt = datetime.fromtimestamp(int(g["lastMoveAt"]) / 1000)
            except Exception:
                end_dt = None
        opening = (g.get("opening") or {}).get("name") if isinstance(g.get("opening"), dict) else g.get("opening")

        # de-dup by source + pgn
        key = {"source": "lichess", "pgn": pgn}
        if db["game"].find_one(key):
            continue

        game_doc = Game(
            source="lichess",
            username=username,
            white=white,
            black=black,
            pgn=pgn,
            rated=rated,
            speed=speed,
            time_control=time_control,
            result=result,
            end_time=end_dt,
            opening=opening,
        )
        create_document("game", game_doc)
        total_inserted += 1

    return {"source": "lichess", "username": username, "inserted": total_inserted}


@app.get("/games")
def list_games(
    source: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200)
):
    """List stored games with optional filters."""
    filt = {}
    if source:
        filt["source"] = source
    if username:
        filt["username"] = username
    docs = get_documents("game", filt, limit)
    # Convert ObjectId and datetimes
    for d in docs:
        d["_id"] = str(d.get("_id"))
        if d.get("end_time") and isinstance(d["end_time"], datetime):
            d["end_time"] = d["end_time"].isoformat()
        if d.get("created_at") and isinstance(d["created_at"], datetime):
            d["created_at"] = d["created_at"].isoformat()
        if d.get("updated_at") and isinstance(d["updated_at"], datetime):
            d["updated_at"] = d["updated_at"].isoformat()
    return {"count": len(docs), "items": docs}


@app.post("/start-demo")
def start_demo(speed: str, minutes: int, increment: int):
    """Start a demo session with selected time control (no engine yet)."""
    if speed not in {"bullet", "blitz", "rapid"}:
        raise HTTPException(status_code=400, detail="Invalid speed")
    if minutes < 0 or increment < 0:
        raise HTTPException(status_code=400, detail="Invalid time values")
    session_id = str(uuid.uuid4())
    return {"sessionId": session_id, "speed": speed, "minutes": minutes, "increment": increment}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

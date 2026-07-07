"""Dev-only test UI (decisions/0019, 0020, 0021) — hand-test enroll + identify.

NOT a production surface. Mounted only when ``ML_ENABLE_TEST_UI=true``. It reuses
the real composition-root container (same Supabase/DB/FAISS config as the app), so
what you see here is the real pipeline, not a mock:

* ``POST /v1/test/enroll``     — uploads the photo to the media store (Supabase by
  default), then runs :class:`EnrollmentService` which fetches it back, detects,
  embeds, and upserts into the per-school vector index.
* ``POST /v1/test/check``      — identify one uploaded **image or video** against the
  school's index (synchronous read; no DB write, no queue).
* ``POST /v1/test/check-bulk`` — identify many files in one request; returns a
  per-file result so the UI can show each with its identified people.

Identification runs **every** detected face (``face → person``), not just the largest
one, through the same :func:`~ml_service.orchestration.identify.identify_in_frames`
kernel the worker uses — so a group photo lists everyone, and a video is reported
**per sampled frame (timestamp)**: the faces in that frame and who each one is (not a
globally-deduped set). ``student_id`` *is* the student's name/handle in this service;
there is no separate name table. ``school_id`` defaults to a single hardcoded tenant.

The module is named ``dev_ui`` (not ``test_ui``) so pytest does not collect it.
"""

from __future__ import annotations

from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from ml_service.domain.models import FaceBox, Frame, Thresholds
from ml_service.orchestration.identify import FaceResult, identify_in_frames
from ml_service.wiring.container import Container
from ml_service.wiring.settings import settings

router = APIRouter(tags=["dev-ui"], include_in_schema=False)

DEFAULT_SCHOOL_ID = "test-school"
_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")


class _Uploadable(Protocol):
    """The media-store upload convenience (present on the real adapters)."""

    async def upload(self, object_path: str, data: bytes, content_type: str) -> str: ...


def get_container() -> Container:
    # Reuse the app's memoized container (built in the lifespan) if present.
    from ml_service.api.deps import get_container as _get

    return _get()


ContainerDep = Annotated[Container, Depends(get_container)]


def _is_video(content_type: str | None, filename: str | None) -> bool:
    if content_type and content_type.startswith("video/"):
        return True
    return (filename or "").lower().endswith(_VIDEO_EXTS)


def _bbox_json(box: FaceBox) -> dict[str, float]:
    return {"x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2, "score": round(box.score, 4)}


def _face_json(face: FaceResult, thresholds: Thresholds) -> dict[str, object]:
    """One detected face's full audit: box, outcome, emitted people, and the raw
    top-k candidates (each flagged cleared-threshold / emitted) — the same detail the
    worker persists as ``face_detections`` + ``face_detection_candidates`` (0021)."""
    emitted_ids = {p.student_id for p in face.people}
    if len(face.people) >= 2:
        outcome = "ambiguous"
    elif len(face.people) == 1:
        outcome = "match"
    else:
        outcome = "unknown"
    return {
        "bbox": _bbox_json(face.bbox),
        "detection_score": round(face.bbox.score, 4),
        "outcome": outcome,
        "people": [
            {
                "student_id": p.student_id,
                "score": round(p.score, 4),
                "needs_review": p.needs_review,
            }
            for p in face.people
        ],
        "candidates": [
            {
                "student_id": c.student_id,
                "score": round(c.score, 4),
                "rank": rank,
                "cleared_threshold": thresholds.clears(c.score),
                "emitted": c.student_id in emitted_ids,
            }
            for rank, c in enumerate(face.candidates, start=1)
        ],
    }


async def _identify_media(
    container: Container,
    school_id: str,
    data: bytes,
    *,
    content_type: str | None,
    filename: str | None,
) -> dict[str, object]:
    """Identify every face in one image or video against the school's index.

    Reuses the worker's identify kernel, so the result is the real pipeline's:
    per-frame / per-face detail plus a deduped people summary. Images are the
    single-frame case; videos are sampled at ``settings.video_sample_fps`` and
    reported per timestamp. The container's adapters are memoized singletons, so
    the models load only once (on the first call), not per image.
    """
    detector = await run_in_threadpool(container.detector)
    embedder = await run_in_threadpool(container.embedder)
    index = await run_in_threadpool(container.vector_index)
    thresholds_provider = await run_in_threadpool(container.threshold_provider)
    thresholds = await thresholds_provider.get_thresholds(school_id)

    is_video = _is_video(content_type, filename)
    try:
        if is_video:
            extractor = await run_in_threadpool(container.extractor)
            # decord/opencv decode lazily on iteration; materialize off the loop.
            frames: list[Frame] = await run_in_threadpool(
                lambda: list(extractor.extract(data, settings.video_sample_fps))
            )
        else:
            frames = [Frame(data)]
        result = await identify_in_frames(
            frames,
            school_id=school_id,
            detector=detector,
            embedder=embedder,
            index=index,
            thresholds=thresholds,
            top_k=settings.top_k,
        )
    except Exception as exc:  # corrupt media, empty/absent index, model mismatch…
        return {
            "media_type": "video" if is_video else "image",
            "error": f"identify_failed: {exc}",
            "faces_detected": 0,
            "frames": [],
            "people_summary": [],
        }

    return {
        "media_type": "video" if is_video else "image",
        "faces_detected": result.faces_detected,
        "frames_processed": result.frames_processed,
        "unknown_faces": result.unknown_faces,
        "top_k": settings.top_k,
        "thresholds": {
            "match_confidence": round(thresholds.match_confidence, 4),
            "gap": round(thresholds.gap, 4),
        },
        # Per-frame / per-face timeline with each face's full top-k audit — the same
        # detail the worker now persists as the detection tables (decisions/0021).
        "frames": [
            {
                "frame_timestamp_ms": fr.frame_timestamp_ms,
                "faces": [_face_json(face, thresholds) for face in fr.faces],
            }
            for fr in result.frames
        ],
        # Unique people across the whole media (best score per student).
        "people_summary": [
            {
                "student_id": p.student_id,
                "score": round(p.score, 4),
                "needs_review": p.needs_review,
            }
            for p in sorted(result.people.values(), key=lambda h: h.score, reverse=True)
        ],
    }


@router.post("/v1/test/enroll")
async def enroll_upload(
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    student_id: Annotated[str, Form()],
    school_id: Annotated[str, Form()] = DEFAULT_SCHOOL_ID,
) -> dict[str, object]:
    """Save the uploaded photo to the media store, then enroll the student."""
    data = await file.read()
    store = await run_in_threadpool(container.media_store)
    if not hasattr(store, "upload"):
        return {"ok": False, "error": "configured media store cannot upload"}
    filename = file.filename or "photo.jpg"
    object_path = f"test-enroll/{school_id}/{student_id}/{filename}"
    content_type = file.content_type or "application/octet-stream"
    uri = await cast(_Uploadable, store).upload(object_path, data, content_type)

    service = await run_in_threadpool(container.enrollment_service)
    result = await service.enroll(school_id, student_id, [uri])
    return {
        "ok": result.embeddings_stored > 0,
        "school_id": result.school_id,
        "student_id": result.student_id,
        "stored_uri": uri,
        "embeddings_stored": result.embeddings_stored,
        "photo_results": [
            {"index": p.index, "status": p.status.value, "detail": p.detail}
            for p in result.photo_results
        ],
    }


@router.post("/v1/test/check")
async def identify_upload(
    container: ContainerDep,
    file: Annotated[UploadFile, File()],
    school_id: Annotated[str, Form()] = DEFAULT_SCHOOL_ID,
) -> dict[str, object]:
    """Identify every face in one uploaded image or video against the index."""
    data = await file.read()
    return await _identify_media(
        container, school_id, data, content_type=file.content_type, filename=file.filename
    )


@router.post("/v1/test/check-bulk")
async def identify_bulk(
    container: ContainerDep,
    files: Annotated[list[UploadFile], File()],
    school_id: Annotated[str, Form()] = DEFAULT_SCHOOL_ID,
) -> dict[str, object]:
    """Identify many files in one request; results are returned in upload order."""
    results: list[dict[str, object]] = []
    for f in files:
        data = await f.read()
        outcome = await _identify_media(
            container, school_id, data, content_type=f.content_type, filename=f.filename
        )
        results.append({"filename": f.filename, **outcome})
    return {"count": len(results), "results": results}


@router.get("/test", response_class=HTMLResponse)
async def dev_page() -> str:
    return _PAGE


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>ML Service — Test UI</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.4rem; }
  .card { border: 1px solid #8884; border-radius: 12px; padding: 1.2rem; margin: 1rem 0; }
  label { display: block; font-size: .85rem; margin: .6rem 0 .2rem; opacity: .8; }
  input[type=text] { width: 100%; padding: .5rem; border-radius: 8px; border: 1px solid #8886; box-sizing: border-box; }
  button { margin-top: .9rem; padding: .55rem 1.1rem; border-radius: 8px; border: 0; background: #3b82f6; color: #fff; font-size: 1rem; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  pre { background: #8881; padding: .8rem; border-radius: 8px; overflow: auto; font-size: .8rem; white-space: pre-wrap; }
  .name { font-size: 1.1rem; font-weight: 650; }
  .muted { opacity: .7; font-size: .85rem; }
  img.preview { max-height: 160px; border-radius: 8px; margin-top: .5rem; display: none; }
  .results { margin-top: 1rem; display: flex; flex-direction: column; gap: .6rem; }
  .result-item { display: flex; align-items: flex-start; gap: 1rem; border: 1px solid #8883; border-radius: 8px; padding: .5rem .7rem; }
  .result-item img, .result-item video { height: 72px; width: 72px; object-fit: cover; border-radius: 6px; flex: none; background: #8882; }
  .result-item .rlabel { min-width: 0; flex: 1; }
  .result-item .fname { font-size: .75rem; opacity: .6; word-break: break-all; }
  .result-item .detail { margin-top: .4rem; }
  .chip { display: inline-block; font-size: .8rem; padding: .15rem .55rem; border-radius: 999px; border: 1px solid #8884; margin: .15rem .2rem 0 0; }
  .chip.ok { color: #16a34a; border-color: #16a34a66; }
  .chip.no { color: #ef4444; border-color: #ef444466; }
  .chip.rev { color: #d97706; border-color: #d9770666; }
  .trow { font-size: .85rem; margin: .15rem 0; }
  .trow .ts { display: inline-block; min-width: 3.4rem; opacity: .65; font-variant-numeric: tabular-nums; }
  .ok { color: #16a34a; } .no { color: #ef4444; } .rev { color: #d97706; }
  .face { border-top: 1px solid #8883; padding: .4rem 0; }
  .face:first-child { border-top: 0; padding-top: .1rem; }
  .fhead { font-size: .9rem; }
  .cands { margin-top: .25rem; }
</style>
</head>
<body>
  <h1>ML Service — Test UI</h1>
  <p class="muted">Enroll students' photos, then identify one or many images/videos against the index.</p>

  <label for="school">School ID (hardcoded default is fine)</label>
  <input id="school" type="text" value="test-school"/>

  <div class="card">
    <h2>1. Enroll</h2>
    <label for="sid">Student name / id</label>
    <input id="sid" type="text" placeholder="e.g. alice"/>
    <label for="enrollFile">Reference photo</label>
    <input id="enrollFile" type="file" accept="image/*"/>
    <img id="enrollPrev" class="preview"/>
    <button id="enrollBtn">Upload &amp; Enroll</button>
    <pre id="enrollOut" hidden></pre>
  </div>

  <div class="card">
    <h2>2. Identify (bulk — images or video)</h2>
    <label for="checkFile">Images or videos to identify — select one or more</label>
    <input id="checkFile" type="file" accept="image/*,video/*" multiple/>
    <button id="checkBtn">Identify all</button>
    <div id="results" class="results"></div>
  </div>

<script>
const $ = (id) => document.getElementById(id);
const school = () => $("school").value.trim() || "test-school";
const VIDEO_RE = /\\.(mp4|mov|avi|mkv|webm|m4v)$/i;
const isVideoFile = (f) => (f.type || "").startsWith("video/") || VIDEO_RE.test(f.name);
const fmtTs = (ms) => (ms == null ? "" : (ms / 1000).toFixed(1) + "s");
const personText = (p) => p.student_id + " (" + p.score + (p.needs_review ? ", review" : "") + ")";
// One detected face -> its person(s). Two people = ambiguous (both need review).
const faceText = (face) => (!face.people || !face.people.length)
  ? "unknown"
  : face.people.map(personText).join(" / ");
// One top-k candidate chip: green = emitted (written to matches), amber = cleared
// the threshold but not chosen, red = below threshold.
const candHtml = (c, ambiguous) => {
  const cls = c.emitted ? (ambiguous ? "rev" : "ok") : (c.cleared_threshold ? "rev" : "no");
  const mark = c.emitted ? " ✓" : (c.cleared_threshold ? " ·cleared" : " ·below");
  return '<span class="chip ' + cls + '">#' + c.rank + " " + c.student_id + " " + c.score + mark + "</span>";
};
// One detected face: outcome + detector box + its full raw top-k list.
const faceHtml = (face, idx) => {
  const outClass = face.outcome === "match" ? "ok" : (face.outcome === "ambiguous" ? "rev" : "no");
  const amb = face.outcome === "ambiguous";
  const cands = (face.candidates || []).map((c) => candHtml(c, amb)).join(" ");
  const b = face.bbox;
  const boxStr = b ? "[" + Math.round(b.x1) + "," + Math.round(b.y1) + " → " +
    Math.round(b.x2) + "," + Math.round(b.y2) + "]" : "";
  return '<div class="face"><div class="fhead"><b>Face ' + (idx + 1) + "</b> · " +
    '<span class="' + outClass + '">' + face.outcome + "</span> " +
    '<span class="muted">det ' + (face.detection_score != null ? face.detection_score : "?") +
    " · " + boxStr + "</span></div>" +
    '<div class="cands">' + (cands || '<span class="muted">no candidates in index</span>') +
    "</div></div>";
};

$("enrollFile").addEventListener("change", () => {
  const f = $("enrollFile").files[0], img = $("enrollPrev");
  if (f) { img.src = URL.createObjectURL(f); img.style.display = "block"; }
});

$("enrollBtn").onclick = async () => {
  const f = $("enrollFile").files[0], sid = $("sid").value.trim();
  if (!f || !sid) { alert("Pick a photo and enter a student name/id."); return; }
  const out = $("enrollOut");
  $("enrollBtn").disabled = true; out.hidden = false;
  out.textContent = "Working… (first call loads the models, can take ~20s)";
  try {
    const fd = new FormData();
    fd.append("file", f); fd.append("student_id", sid); fd.append("school_id", school());
    const res = await fetch("/v1/test/enroll", { method: "POST", body: fd });
    out.textContent = JSON.stringify(await res.json(), null, 2);
  } catch (e) { out.textContent = "Request failed: " + e; }
  finally { $("enrollBtn").disabled = false; }
};

function renderResult(item, r) {
  const status = item.querySelector(".status");
  const detail = item.querySelector(".detail");
  if (r.error) {
    status.className = "status";
    status.innerHTML = '<span class="name no">Error</span> <span class="muted">' + r.error + '</span>';
    return;
  }
  const nPeople = (r.people_summary || []).length;
  const summary = r.faces_detected + " face" + (r.faces_detected === 1 ? "" : "s") +
    " → " + nPeople + " " + (nPeople === 1 ? "person" : "people");
  status.className = "status";
  const th = r.thresholds
    ? ' <span class="muted">· match≥' + r.thresholds.match_confidence +
      ", gap>" + r.thresholds.gap + ", top_k=" + r.top_k + "</span>"
    : "";
  status.innerHTML = '<span class="name">' + summary + "</span>" +
    (r.media_type === "video" ? ' <span class="muted">' + r.frames_processed + " frames sampled</span>" : "") + th;

  if (r.media_type === "video") {
    // Per-timestamp timeline: which faces (and who) appear in each sampled frame.
    const rows = (r.frames || [])
      .filter((fr) => fr.faces && fr.faces.length)
      .map((fr) => '<div class="trow"><span class="ts">t=' + fmtTs(fr.frame_timestamp_ms) +
        '</span> ' + fr.faces.map(faceText).join(", ") + "</div>");
    detail.innerHTML = rows.length ? rows.join("") : '<span class="muted">no faces detected</span>';
  } else {
    // Image: full per-face detail — outcome + box + the raw top-k candidates.
    const faces = (r.frames && r.frames[0] && r.frames[0].faces) || [];
    detail.innerHTML = faces.length
      ? faces.map((face, i) => faceHtml(face, i)).join("")
      : '<span class="muted">no faces detected</span>';
  }
}

$("checkBtn").onclick = async () => {
  const files = [...$("checkFile").files];
  if (!files.length) { alert("Pick one or more images/videos to identify."); return; }
  const results = $("results");
  results.innerHTML = "";
  const items = files.map((f) => {
    const item = document.createElement("div");
    item.className = "result-item";
    const media = isVideoFile(f)
      ? '<video src="' + URL.createObjectURL(f) + '" muted playsinline preload="metadata"></video>'
      : '<img src="' + URL.createObjectURL(f) + '"/>';
    item.innerHTML = media +
      '<div class="rlabel"><div class="status muted">…identifying (first call loads models ~20s)</div>' +
      '<div class="fname">' + f.name + '</div><div class="detail"></div></div>';
    results.appendChild(item);
    return item;
  });

  $("checkBtn").disabled = true;
  try {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("school_id", school());
    const res = await fetch("/v1/test/check-bulk", { method: "POST", body: fd });
    const json = await res.json();
    (json.results || []).forEach((r, i) => { if (items[i]) renderResult(items[i], r); });
  } catch (e) {
    results.innerHTML = "Request failed: " + e;
  } finally { $("checkBtn").disabled = false; }
};
</script>
</body>
</html>"""

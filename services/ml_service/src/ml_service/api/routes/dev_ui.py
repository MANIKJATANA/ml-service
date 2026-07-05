"""Dev-only test UI (decisions/0019) — hand-test enroll + identify from a browser.

NOT a production surface. Mounted only when ``ML_ENABLE_TEST_UI=true``. It reuses
the real composition-root container (same Supabase/DB/FAISS config as the app), so
what you see here is the real pipeline, not a mock:

* ``POST /v1/test/enroll``     — uploads the photo to the media store (Supabase by
  default), then runs :class:`EnrollmentService` which fetches it back, detects,
  embeds, and upserts into the per-school vector index.
* ``POST /v1/test/check``      — identify one uploaded photo against the school's
  index (synchronous read; no DB write, no queue).
* ``POST /v1/test/check-bulk`` — identify many photos in one request; returns a
  per-file result so the UI can show each image with its identified student.

Identification uses the same :func:`apply_threshold_and_gap` decision the worker
uses. ``student_id`` *is* the student's name/handle in this service; there is no
separate name table. ``school_id`` defaults to a single hardcoded test tenant.

The module is named ``dev_ui`` (not ``test_ui``) so pytest does not collect it.
"""

from __future__ import annotations

from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from ml_service.domain.decision import apply_threshold_and_gap
from ml_service.wiring.container import Container
from ml_service.wiring.settings import settings

router = APIRouter(tags=["dev-ui"], include_in_schema=False)

DEFAULT_SCHOOL_ID = "test-school"


class _Uploadable(Protocol):
    """The media-store upload convenience (present on the real adapters)."""

    async def upload(self, object_path: str, data: bytes, content_type: str) -> str: ...


def get_container() -> Container:
    # Reuse the app's memoized container (built in the lifespan) if present.
    from ml_service.api.deps import get_container as _get

    return _get()


ContainerDep = Annotated[Container, Depends(get_container)]


async def _identify_image(
    container: Container, school_id: str, data: bytes
) -> dict[str, object]:
    """Detect → embed → search → decide for one image. Reused by check + bulk.

    The container's adapters are memoized singletons, so calling this per image
    loads the models only once (on the first image), not per call.
    """
    detector = await run_in_threadpool(container.detector)
    embedder = await run_in_threadpool(container.embedder)
    index = await run_in_threadpool(container.vector_index)
    thresholds_provider = await run_in_threadpool(container.threshold_provider)

    boxes = await detector.detect(data)
    if not boxes:
        return {"match": None, "reason": "no_face_detected", "candidates": []}
    box = max(boxes, key=lambda b: b.area)
    embedding = await embedder.embed(data, box)

    try:
        candidates = await index.search(school_id, embedding, settings.top_k)
    except Exception as exc:  # empty/absent index for this school, model mismatch…
        return {"match": None, "reason": f"index_search_failed: {exc}", "candidates": []}

    thresholds = await thresholds_provider.get_thresholds(school_id)
    emissions = apply_threshold_and_gap(candidates, thresholds)
    all_candidates = [
        {"student_id": c.student_id, "score": round(c.score, 4)} for c in candidates
    ]
    if not emissions:
        return {"match": None, "reason": "no_match_above_threshold", "candidates": all_candidates}
    matches = [
        {
            "student_id": e.candidate.student_id,
            "score": round(e.candidate.score, 4),
            "needs_review": e.needs_review,
        }
        for e in emissions
    ]
    return {"match": matches[0], "matches": matches, "candidates": all_candidates}


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
    """Identify the face in a single uploaded photo against the school's index."""
    return await _identify_image(container, school_id, await file.read())


@router.post("/v1/test/check-bulk")
async def identify_bulk(
    container: ContainerDep,
    files: Annotated[list[UploadFile], File()],
    school_id: Annotated[str, Form()] = DEFAULT_SCHOOL_ID,
) -> dict[str, object]:
    """Identify many photos in one request; results are returned in upload order."""
    results: list[dict[str, object]] = []
    for f in files:
        outcome = await _identify_image(container, school_id, await f.read())
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
  .name { font-size: 1.2rem; font-weight: 700; }
  .muted { opacity: .7; font-size: .85rem; }
  img.preview { max-height: 160px; border-radius: 8px; margin-top: .5rem; display: none; }
  .results { margin-top: 1rem; display: flex; flex-direction: column; gap: .6rem; }
  .result-item { display: flex; align-items: center; gap: 1rem; border: 1px solid #8883; border-radius: 8px; padding: .5rem .7rem; }
  .result-item img { height: 72px; width: 72px; object-fit: cover; border-radius: 6px; flex: none; }
  .result-item .rlabel { min-width: 0; }
  .result-item .fname { font-size: .75rem; opacity: .6; word-break: break-all; }
  .result-item .cands { font-size: .75rem; margin-top: .25rem; opacity: .85; }
  .result-item .cands b { font-weight: 600; }
  .ok { color: #16a34a; } .no { color: #ef4444; } .rev { color: #d97706; }
</style>
</head>
<body>
  <h1>ML Service — Test UI</h1>
  <p class="muted">Enroll students' photos, then identify one or many photos against the index.</p>

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
    <h2>2. Identify (bulk)</h2>
    <label for="checkFile">Photos to identify — select one or more</label>
    <input id="checkFile" type="file" accept="image/*" multiple/>
    <button id="checkBtn">Identify all</button>
    <div id="results" class="results"></div>
  </div>

<script>
const $ = (id) => document.getElementById(id);
const school = () => $("school").value.trim() || "test-school";

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

$("checkBtn").onclick = async () => {
  const files = [...$("checkFile").files];
  if (!files.length) { alert("Pick one or more photos to identify."); return; }
  const results = $("results");
  results.innerHTML = "";
  const labels = files.map((f) => {
    const item = document.createElement("div");
    item.className = "result-item";
    item.innerHTML =
      '<img src="' + URL.createObjectURL(f) + '"/>' +
      '<div class="rlabel"><div class="muted status">…identifying (first call loads models ~20s)</div>' +
      '<div class="fname">' + f.name + '</div></div>';
    results.appendChild(item);
    return item.querySelector(".status");
  });

  $("checkBtn").disabled = true;
  try {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("school_id", school());
    const res = await fetch("/v1/test/check-bulk", { method: "POST", body: fd });
    const json = await res.json();
    (json.results || []).forEach((r, i) => {
      const el = labels[i];
      if (!el) return;
      if (r.match) {
        const rev = r.match.needs_review;
        el.innerHTML =
          '<span class="name ' + (rev ? "rev" : "ok") + '">' + r.match.student_id + '</span>' +
          ' <span class="muted">score ' + r.match.score + (rev ? ' — needs review' : '') + '</span>';
      } else {
        el.innerHTML = '<span class="name no">No match</span> <span class="muted">' + (r.reason || '') + '</span>';
      }
      const cands = r.candidates || [];
      const cline = cands.length
        ? '<b>top-' + cands.length + ':</b> ' + cands.map((c) => c.student_id + ' (' + c.score + ')').join(', ')
        : '<b>top-K:</b> —';
      let cdiv = el.parentElement.querySelector(".cands");
      if (!cdiv) { cdiv = document.createElement("div"); cdiv.className = "cands"; el.parentElement.appendChild(cdiv); }
      cdiv.innerHTML = cline;
    });
  } catch (e) {
    results.innerHTML = "Request failed: " + e;
  } finally { $("checkBtn").disabled = false; }
};
</script>
</body>
</html>"""

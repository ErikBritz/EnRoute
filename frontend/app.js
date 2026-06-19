/* app.js — LBS Universal Translator home page
 *
 * Single responsibility: collect a CSV file + species name,
 * POST them to the backend, store the JSON response in
 * sessionStorage, then unlock the visualize link.
 *
 * All physics, GPS parsing, and trait lookup happen in the backend.
 * This file does NO calculations and does NOT re-read the file.
 */

const STORAGE_KEY = "lbsVisualizationPayload";
const API_URL     = "/api/upload-track";

// DOM references
const fileInput     = document.getElementById("file-input");
const speciesInput  = document.getElementById("species-name-input");
const runBtn        = document.getElementById("backend-run");
const statusEl      = document.getElementById("backend-status");
const visualizeLink = document.getElementById("visualize-link");

function setStatus(msg) {
  if (statusEl) statusEl.textContent = msg;
}

function unlockVisualize() {
  if (!visualizeLink) return;
  visualizeLink.classList.remove("disabled");
  visualizeLink.setAttribute("aria-disabled", "false");
}

function lockVisualize() {
  if (!visualizeLink) return;
  visualizeLink.classList.add("disabled");
  visualizeLink.setAttribute("aria-disabled", "true");
}

if (runBtn) {
  runBtn.addEventListener("click", async () => {
    const file    = fileInput?.files?.[0];
    const species = speciesInput?.value?.trim();

    if (!file) {
      setStatus("Please upload a tracking CSV first.");
      return;
    }
    if (!species) {
      setStatus("Please enter a species scientific name.");
      return;
    }

    runBtn.disabled = true;
    setStatus("Running analysis...");

    const form = new FormData();
    form.append("file", file);
    form.append("species_scientific_name", species);

    try {
      const res = await fetch(API_URL, { method: "POST", body: form });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${res.status}`);
      }

      const data = await res.json();

      console.log("[LBS] backend response keys:", Object.keys(data));
      console.log("[LBS] gpsRows count:", data.gpsRows?.length);
      console.log("[LBS] first gpsRow:", data.gpsRows?.[0]);

      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      setStatus("Analysis complete! Click Open Visualization.");
      unlockVisualize();

    } catch (err) {
      console.error("[LBS] fetch error:", err);
      setStatus(`Error: ${err.message}`);
      lockVisualize();
    } finally {
      runBtn.disabled = false;
    }
  });
}

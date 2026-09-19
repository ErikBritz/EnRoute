/* app.js - LBS Universal Translator (fully static / GitHub Pages)
 *
 * All computation runs in the browser. No backend required.
 * Ports the Python pipeline from backend/main.py,
 * backend/database.py, and backend/energetics_engine.py.
 */

// Constants (mirrors backend/config.py)
const AIR_DENSITY               = 1.225;
const GRAVITY                   = 9.81;
const MUSCLE_EFFICIENCY         = 0.23;
const INDUCED_POWER_FACTOR      = 1.2;
const BODY_DRAG_COEFFICIENT     = 0.10;
const CD_PROFILE                = 0.02;
const WINGSPAN_K                = 1.17;
const WINGSPAN_EXP              = 0.393;
const MIN_VELOCITY              = 0.1;
const FLIGHT_VELOCITY_THRESHOLD = 3.0;
const MAX_POINTS                = 2000;
const STORAGE_KEY               = "lbsVisualizationPayload";

// AVONET CSV is in the repo data/ folder, one level above frontend/
const AVONET_URL = "../data/avonet_birds.csv";

// DOM
const fileInput     = document.getElementById("file-input");
const speciesInput  = document.getElementById("species-name-input");
const runBtn        = document.getElementById("backend-run");
const statusEl      = document.getElementById("backend-status");
const visualizeLink = document.getElementById("visualize-link");

function setStatus(msg) { if (statusEl) statusEl.textContent = msg; }

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

// RFC 4180 CSV parser
function parseCsvLine(line) {
  const fields = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') { inQuotes = false; }
      else { field += ch; }
    } else {
      if (ch === '"') { inQuotes = true; }
      else if (ch === ',') { fields.push(field); field = ""; }
      else { field += ch; }
    }
  }
  fields.push(field);
  return fields;
}

function parseCsv(text) {
  const lines = text.split(/\r?\n/);
  if (lines.length < 2) throw new Error("CSV has no data rows.");
  const headers = parseCsvLine(lines[0]);
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const cells = parseCsvLine(line);
    if (cells.length < headers.length) continue;
    const row = {};
    headers.forEach((h, idx) => { row[h] = cells[idx] ?? ""; });
    rows.push(row);
  }
  return { headers, rows };
}

// Haversine distance in metres
function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(a));
}

// Species trait lookup (mirrors database.py)
function getTraits(avonetRows, scientificName) {
  const name = scientificName.trim().toLowerCase();
  const row = avonetRows.find(r =>
    (r["Species1"] || r["Species"] || "").trim().toLowerCase() === name
  );
  if (!row) throw new Error("Species '" + scientificName + "' not found in AVONET data.");

  const mass_g = parseFloat(row["Mass"]);
  const hwi    = parseFloat(row["Hand-Wing.Index"]);

  if (!isFinite(mass_g) || mass_g <= 0) throw new Error("Invalid mass in AVONET data.");
  if (!isFinite(hwi)    || hwi <= 0)    throw new Error("Invalid Hand-Wing Index in AVONET data.");

  const mass_kg         = mass_g / 1000;
  const wing_span_m     = WINGSPAN_K * Math.pow(mass_kg, WINGSPAN_EXP);
  const aspect_ratio    = 2.04 * Math.log(hwi) + 2.58;
  const wing_area_m2    = (wing_span_m ** 2) / aspect_ratio;
  const frontal_area_m2 = 0.00813 * Math.pow(mass_kg, 0.666);

  return { mass_kg, wing_span_m, aspect_ratio, wing_area_m2, frontal_area_m2 };
}

// Energetics (mirrors energetics_engine.py)
function activeMetabolicPower(mass_kg) {
  return 10.5 * Math.pow(mass_kg, 0.725);
}

function totalPower(velocity_mps, mass_kg, wing_span_m, aspect_ratio, frontal_area_m2) {
  const v         = Math.max(velocity_mps, MIN_VELOCITY);
  const wing_area = (wing_span_m ** 2) / aspect_ratio;
  const induced   = (INDUCED_POWER_FACTOR * (mass_kg * GRAVITY) ** 2)
                    / (2 * AIR_DENSITY * v * Math.PI * (wing_span_m / 2) ** 2);
  const parasitic = 0.5 * AIR_DENSITY * (v ** 3) * frontal_area_m2 * BODY_DRAG_COEFFICIENT;
  const profile   = 0.5 * AIR_DENSITY * (v ** 3) * wing_area * CD_PROFILE;
  return activeMetabolicPower(mass_kg) + (induced + parasitic + profile) / MUSCLE_EFFICIENCY;
}

// Full analysis pipeline
async function runAnalysis(trackText, scientificName) {
  setStatus("Loading AVONET trait database...");
  const avonetRes = await fetch(AVONET_URL);
  if (!avonetRes.ok) throw new Error("Failed to load AVONET data (HTTP " + avonetRes.status + ").");
  const { rows: avonetRows } = parseCsv(await avonetRes.text());

  setStatus("Looking up species traits...");
  const traits = getTraits(avonetRows, scientificName);
  const { mass_kg, wing_span_m, aspect_ratio, frontal_area_m2 } = traits;

  setStatus("Parsing track CSV...");
  const { headers, rows: rawRows } = parseCsv(trackText);
  const LAT = "location-lat", LON = "location-long", TIME = "timestamp", SPD = "ground-speed";
  if (![LAT, LON, TIME].every(c => headers.includes(c))) {
    throw new Error("Track CSV is missing required columns: " + [LAT, LON, TIME].join(", "));
  }

  let rows = rawRows
    .map(r => ({
      lat:   parseFloat(r[LAT]),
      lon:   parseFloat(r[LON]),
      time:  new Date(r[TIME]),
      speed: (r[SPD] !== undefined && r[SPD] !== "") ? parseFloat(r[SPD]) : null,
    }))
    .filter(r =>
      isFinite(r.lat) && isFinite(r.lon) && !isNaN(r.time)
      && r.lat >= -90 && r.lat <= 90 && r.lon >= -180 && r.lon <= 180
    );

  const seen = new Set();
  rows = rows.filter(r => {
    const k = r.time.getTime();
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  rows.sort((a, b) => a.time - b.time);

  if (rows.length < 2) throw new Error("Not enough valid track points after cleaning.");

  setStatus("Computing energetics...");
  const flightDistances = [], flightEnergies = [], restEnergies = [];

  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1], curr = rows[i];
    const dist     = haversineMeters(prev.lat, prev.lon, curr.lat, curr.lon);
    const dt       = (curr.time - prev.time) / 1000;
    if (dt <= 0 || !isFinite(dist)) continue;
    const velocity = dist / dt;
    if (velocity >= FLIGHT_VELOCITY_THRESHOLD) {
      const power = totalPower(velocity, mass_kg, wing_span_m, aspect_ratio, frontal_area_m2);
      flightDistances.push(dist);
      flightEnergies.push(power * dt);
    } else {
      restEnergies.push(activeMetabolicPower(mass_kg) * dt);
    }
  }

  if (flightEnergies.length === 0) {
    throw new Error("No flight segments detected. Ensure the track contains moving fixes (velocity >= 3 m/s).");
  }

  const total_flight_dist   = flightDistances.reduce((s, v) => s + v, 0);
  const total_flight_energy = flightEnergies.reduce((s, v) => s + v, 0);
  const total_rest_energy   = restEnergies.reduce((s, v) => s + v, 0);
  const mean_cot            = total_flight_dist > 0 ? total_flight_energy / total_flight_dist : 0;

  const step    = Math.max(1, Math.floor(rows.length / MAX_POINTS));
  const gpsRows = rows
    .filter((_, i) => i % step === 0)
    .map(r => ({
      lat:   Math.round(r.lat * 1e5) / 1e5,
      lon:   Math.round(r.lon * 1e5) / 1e5,
      time:  r.time.toISOString(),
      speed: (r.speed != null && isFinite(r.speed)) ? Math.round(r.speed * 1e3) / 1e3 : null,
    }));

  return {
    species:          scientificName,
    points_cleaned:   rows.length,
    segments:         flightEnergies.length,
    total_distance_m: total_flight_dist,
    total_energy_j:   total_flight_energy,
    resting_energy_j: total_rest_energy,
    mean_cot_j_m:     mean_cot,
    gpsRows,
  };
}

// Button handler
if (runBtn) {
  runBtn.addEventListener("click", async () => {
    const file    = fileInput?.files?.[0];
    const species = speciesInput?.value?.trim();

    if (!file)    { setStatus("Please upload a tracking CSV first."); return; }
    if (!species) { setStatus("Please enter a species scientific name."); return; }

    runBtn.disabled = true;
    lockVisualize();
    setStatus("Reading file...");

    try {
      const trackText = await file.text();
      const data      = await runAnalysis(trackText, species);

      console.log("[LBS] result keys:", Object.keys(data));
      console.log("[LBS] gpsRows count:", data.gpsRows?.length);
      console.log("[LBS] first gpsRow:", data.gpsRows?.[0]);

      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      setStatus("Analysis complete! Click Open Visualization.");
      unlockVisualize();

    } catch (err) {
      console.error("[LBS] error:", err);
      setStatus("Error: " + err.message);
      lockVisualize();
    } finally {
      runBtn.disabled = false;
    }
  });
}
